"""Interfaz de escritorio del servidor PULSIA Licencias."""
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from urllib.parse import urlsplit

from servidor import Stock, LicenseServer, ROOT
from clasificacion import UNKNOWN, EDITIONS, CHANNELS
from app_usb.widgets import ScrollFrame, scrolled_text

APP_USB = ROOT / 'app_usb'
STATES = ('todos', 'disponible', 'pendiente', 'usada', 'revision', 'baja', 'retirada', 'sin identificar')


def local_date(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime('%d/%m/%Y %H:%M:%S')
    except (ValueError, TypeError):
        return value or ''


def safe_cell(value):
    text = str(value or '')
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text


class ServerApp:
    def __init__(self, root, stock=None):
        self.root = root
        self.stock = stock or Stock()
        self.server = None
        self.server_thread = None
        self.jobs = 0
        self.closing = False
        self.queue = queue.Queue()
        self.inventory_rows = []
        self.assignment_rows = []
        self.event_rows = []
        self.root.title('PULSIA · Servidor de licencias · v0.6')
        self.root.geometry('1220x800')
        self.root.minsize(640, 420)
        self.root.configure(bg='#eef2f6')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background='#eef2f6')
        style.configure('TLabel', background='#eef2f6', foreground='#183147', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 23, 'bold'))
        style.configure('Card.TLabel', font=('Segoe UI', 14, 'bold'), padding=12, background='white')
        style.configure('TButton', padding=(10, 7), font=('Segoe UI', 10))
        style.configure('Treeview', rowheight=28, font=('Segoe UI', 10), background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'), padding=7)
        self.viewport = ScrollFrame(root, min_width=900)
        self.viewport.pack(fill='both', expand=True)
        shell = ttk.Frame(self.viewport.content, padding=20)
        shell.pack(fill='both', expand=True)
        top = ttk.Frame(shell)
        top.pack(fill='x')
        ttk.Label(top, text='PULSIA · Licencias', style='Title.TLabel').pack(side='left')
        self.state_label = ttk.Label(top, text='● Servidor detenido', foreground='#a34725')
        self.state_label.pack(side='right', padx=10)
        ttk.Label(shell, text='Stock centralizado y trazabilidad de las instalaciones CMAR').pack(anchor='w', pady=(3, 14))
        cards = ttk.Frame(shell)
        cards.pack(fill='x', pady=(0, 15))
        self.counters = {}
        self.card_labels = []
        self.card_columns = None
        for name in ('Total', 'Disponibles', 'Pendientes', 'Usadas', 'Revisión', 'Retiradas', 'Sin identificar'):
            var = tk.StringVar(value=f'{name}: 0')
            label = ttk.Label(cards, textvariable=var, style='Card.TLabel')
            self.card_labels.append(label)
            self.counters[name] = var
        cards.bind('<Configure>', lambda e: self.layout_cards(cards, e.width))
        self.tabs = ttk.Notebook(shell)
        self.tabs.pack(fill='both', expand=True)
        self.stock_tab = self.tab('Stock de licencias')
        self.types_tab = self.tab('Stock por tipo')
        self.install_tab = self.tab('Instalaciones')
        self.history_tab = self.tab('Historial')
        self.users_tab = self.tab('Usuarios / técnicos')
        self.config_tab = self.tab('Servidor y app USB')
        self.build_stock()
        self.build_types()
        self.build_installs()
        self.build_history()
        self.build_users()
        self.build_config()
        self.footer = tk.StringVar(value='Preparado')
        self.footer_label = ttk.Label(shell, textvariable=self.footer, wraplength=1100)
        self.footer_label.pack(fill='x', pady=(12, 0))
        shell.bind('<Configure>', lambda e: self.resize_labels(shell, e.width))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        root.after(100, self.poll)
        root.after(3000, self.auto_refresh)

    def layout_cards(self, parent, width):
        columns = 7 if width >= 1365 else 4 if width >= 760 else 3
        if self.card_columns == columns:
            return
        self.card_columns = columns
        for column in range(7):
            parent.columnconfigure(column, weight=1 if column < columns else 0, uniform='cards' if column < columns else '')
        for index, label in enumerate(self.card_labels):
            label.grid(row=index // columns, column=index % columns, sticky='nsew', padx=(0, 6), pady=3)

    def resize_labels(self, parent, width):
        def visit(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Label) and (len(str(child.cget('text'))) > 85 or child is self.footer_label):
                    child.configure(wraplength=max(300, width - 65))
                visit(child)
        visit(parent)

    def tab(self, title):
        frame = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(frame, text=title)
        return frame

    def table(self, parent, columns):
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill='both', expand=True, pady=8)
        tree = ttk.Treeview(wrapper, columns=[c[0] for c in columns], show='headings', selectmode='browse')
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=70, stretch=True)
        vs = ttk.Scrollbar(wrapper, orient='vertical', command=tree.yview)
        hs = ttk.Scrollbar(wrapper, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vs.grid(row=0, column=1, sticky='ns')
        hs.grid(row=1, column=0, sticky='ew')
        wrapper.rowconfigure(0, weight=1)
        wrapper.columnconfigure(0, weight=1)
        for tag, color in [('disponible', '#e9f5ee'), ('pendiente', '#fff3dc'), ('usada', '#e7effa'),
                           ('revision', '#ffe5e5'), ('baja', '#f0f0f0'), ('retirada', '#f0f0f0'), ('sin identificar', '#fff3dc')]:
            tree.tag_configure(tag, background=color)
        return tree

    def search_bar(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill='x')
        ttk.Label(row, text='Buscar').pack(side='left')
        search = tk.StringVar()
        ttk.Entry(row, textvariable=search, width=36).pack(side='left', padx=8)
        state = tk.StringVar(value='todos')
        ttk.Combobox(row, values=STATES, textvariable=state, state='readonly', width=15).pack(side='left', padx=8)
        ttk.Button(row, text='Actualizar', command=self.refresh).pack(side='right')
        search.trace_add('write', lambda *_: self.render())
        state.trace_add('write', lambda *_: self.render())
        return search, state

    def build_stock(self):
        self.stock_search, self.stock_state = self.search_bar(self.stock_tab)
        filters = ttk.Frame(self.stock_tab)
        filters.pack(fill='x', pady=7)
        self.stock_edition = tk.StringVar(value='todas')
        self.stock_channel = tk.StringVar(value='todos')
        for label, var, values in [('Edición', self.stock_edition, ('todas',) + EDITIONS), ('Tipo', self.stock_channel, ('todos',) + CHANNELS)]:
            ttk.Label(filters, text=label).pack(side='left', padx=(0, 7))
            ttk.Combobox(filters, textvariable=var, values=values, state='readonly', width=23).pack(side='left', padx=(0, 12))
            var.trace_add('write', lambda *_: self.render())
        commands = [('Importar XML / ZIP', self.import_xml), ('Importar carpeta', self.import_folder),
                    ('Ver / clasificar licencia', self.classify_license), ('Retirar / habilitar', self.toggle_stock),
                    ('Ver instalación', self.stock_install), ('Exportar CSV', self.export_stock), ('Copia de seguridad', self.backup)]
        for start in (0, 4):
            buttons = ttk.Frame(self.stock_tab)
            buttons.pack(fill='x', pady=(4, 0))
            for text, command in commands[start:start + 4]:
                ttk.Button(buttons, text=text, command=command).pack(side='left', padx=(0, 5))
        self.stock_tree = self.table(self.stock_tab, [('id', 'ID', 60), ('name', 'Archivo XML', 180), ('suffix', 'Últimos 5', 85),
                                  ('edition', 'Edición', 120), ('channel', 'Tipo', 110), ('reference', 'Referencia', 140),
                                  ('state', 'Estado', 100), ('serial', 'Serie del equipo', 140), ('model', 'Modelo', 170), ('date', 'Actualizado', 160)])
        self.stock_tree.bind('<Double-1>', lambda _: self.classify_license())
        ttk.Label(self.stock_tab, text='Sin identificar: clasifique por referencia antes de distribuir. Los datos XML no verifican autenticidad ni activación.').pack(anchor='w')

    def build_types(self):
        ttk.Label(self.types_tab, text='Edición y tipo se cuentan por separado: por ejemplo, Pro / CMAR. Doble clic para filtrar el stock.').pack(anchor='w')
        self.types_tree = self.table(self.types_tab, [('edition', 'Edición', 170), ('channel', 'Tipo', 150), ('total', 'Total', 85),
                                    ('available', 'Disponibles', 100), ('pending', 'Pendientes', 100), ('used', 'Usadas', 85),
                                    ('review', 'Revisión', 85), ('withdrawn', 'Retiradas', 90), ('unknown', 'Sin identificar', 110)])
        self.types_tree.bind('<Double-1>', lambda _: self.filter_type())

    def filter_type(self):
        selection = self.types_tree.selection()
        if selection:
            values = self.types_tree.item(selection[0])['values']
            self.stock_edition.set(values[0])
            self.stock_channel.set(values[1])
            self.stock_state.set('todos')
            self.stock_search.set('')
            self.tabs.select(self.stock_tab)

    def build_installs(self):
        self.install_search, self.install_state = self.search_bar(self.install_tab)
        row = ttk.Frame(self.install_tab)
        row.pack(fill='x', pady=(10, 0))
        for text, cmd in [('Ver detalles', self.install_details), ('Dar de baja y devolver al stock', self.release),
                          ('Exportar CSV', self.export_installs)]:
            ttk.Button(row, text=text, command=cmd).pack(side='left', padx=(0, 6))
        self.install_tree = self.table(self.install_tab, [('id', 'Asignación', 180), ('license', 'Licencia', 75), ('serial', 'Serie', 140),
                                ('model', 'Modelo', 160), ('technician', 'Técnico', 140), ('edition', 'Edición', 110), ('channel', 'Tipo', 110), ('windows', 'Windows', 170), ('state', 'Estado', 100), ('date', 'Fecha', 160)])
        self.install_tree.bind('<Double-1>', lambda _: self.install_details())
        ttk.Label(self.install_tab, text='La baja registra un motivo y conserva el historial. No desinstala la clave del equipo anterior.').pack(anchor='w')

    def build_history(self):
        top = ttk.Frame(self.history_tab)
        top.pack(fill='x')
        ttk.Label(top, text='Importaciones, asignaciones, resultados y bajas · Fechas mostradas en hora local').pack(side='left')
        ttk.Button(top, text='Actualizar', command=self.refresh).pack(side='right')
        self.history_tree = self.table(self.history_tab, [('date', 'Fecha', 170), ('action', 'Acción', 120), ('assignment', 'Asignación', 230), ('detail', 'Detalle', 550)])

    def build_users(self):
        ttk.Label(self.users_tab, text='Estos usuarios se ofrecen al cliente USB como técnicos. Los inactivos no pueden iniciar nuevas instalaciones.').pack(anchor='w')
        row = ttk.Frame(self.users_tab)
        row.pack(fill='x', pady=10)
        for text, action in [('Añadir usuario', self.add_user), ('Cambiar nombre', self.rename_user), ('Activar / desactivar', self.toggle_user), ('Actualizar', self.refresh)]:
            ttk.Button(row, text=text, command=action).pack(side='left', padx=(0, 8))
        self.users_tree = self.table(self.users_tab, [('id', 'ID', 60), ('name', 'Nombre del técnico', 250), ('active', 'Estado', 100),
                                     ('installations', 'Instalaciones', 110), ('created', 'Creado', 170), ('updated', 'Actualizado', 170)])
        self.users_tree.bind('<Double-1>', lambda _: self.rename_user())
        ttk.Label(self.users_tab, text='Cambiar un nombre o desactivar un usuario conserva el nombre original de sus instalaciones y todo su historial.').pack(anchor='w')

    def add_user(self):
        name = simpledialog.askstring('Añadir usuario', 'Nombre del técnico:', parent=self.root)
        if name is not None:
            try:
                self.stock.add_technician(name)
                self.refresh()
                self.footer.set('Usuario creado. Actualice la lista desde el cliente USB.')
            except Exception as e:
                self.error(e)

    def rename_user(self):
        try:
            iid = int(self.selected(self.users_tree))
            row = next(r for r in self.user_rows if r['id'] == iid)
            name = simpledialog.askstring('Cambiar nombre', 'Nombre del técnico:', initialvalue=row['name'], parent=self.root)
            if name is not None:
                self.stock.edit_technician(iid, name=name)
                self.refresh()
                self.footer.set('Nombre actualizado. El historial anterior se conserva.')
        except Exception as e:
            self.error(e)

    def toggle_user(self):
        try:
            iid = int(self.selected(self.users_tree))
            row = next(r for r in self.user_rows if r['id'] == iid)
            self.stock.edit_technician(iid, active=not row['active'])
            self.refresh()
            self.footer.set('Estado del usuario actualizado. El servidor validará la lista vigente al reservar.')
        except Exception as e:
            self.error(e)

    def build_config(self):
        frame = self.config_tab
        config = self.stock.config()
        self.fields = {}
        labels = [('host', 'Escuchar en'), ('port', 'Puerto HTTPS'), ('url', 'Dirección para los USB'),
                  ('cert', 'Certificado servidor'), ('key', 'Clave privada servidor'), ('ca', 'Certificado CA para USB')]
        for key, label in labels:
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=label, width=25).pack(side='left')
            var = tk.StringVar(value=str(config.get(key, '')))
            self.fields[key] = var
            ttk.Entry(row, textvariable=var).pack(side='left', fill='x', expand=True)
            if key in ('cert', 'key', 'ca'):
                ttk.Button(row, text='Examinar', command=lambda k=key: self.choose_file(k)).pack(side='left', padx=(8, 0))
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=10)
        ttk.Button(row, text='Guardar configuración', command=self.save_config).pack(side='left', padx=(0, 8))
        ttk.Button(row, text='Crear certificados LAN', command=self.generate_certs).pack(side='left', padx=(0, 8))
        self.start_button = ttk.Button(row, text='Iniciar servidor', command=self.start_server)
        self.start_button.pack(side='left', padx=(0, 8))
        self.stop_button = ttk.Button(row, text='Detener', command=self.stop_server, state='disabled')
        self.stop_button.pack(side='left')
        ttk.Separator(frame).pack(fill='x', pady=8)
        ttk.Label(frame, text='Aplicación del pendrive · app_usb', font=('Segoe UI', 13, 'bold')).pack(anchor='w', pady=4)
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=8)
        self.compile_button = ttk.Button(row, text='Compilar EXE del cliente', command=self.compile_client)
        self.compile_button.pack(side='left', padx=(0, 8))
        ttk.Button(row, text='Preparar pendrive / carpeta', command=self.prepare_usb).pack(side='left', padx=(0, 8))
        ttk.Button(row, text='Abrir carpeta app_usb', command=self.open_usb_folder).pack(side='left')
        ttk.Label(frame, wraplength=1050, text='Compile en Windows con Internet. Después, prepare el USB: se copian el EXE, su configuración y la CA pública. Los equipos cliente no necesitan Python. No se copian bases de datos ni claves privadas.').pack(anchor='w', pady=4)
        console_frame, self.console = scrolled_text(frame, height=7, state='disabled', font=('Consolas', 9))
        console_frame.pack(fill='both', expand=True, pady=8)

    def choose_file(self, key):
        value = filedialog.askopenfilename(parent=self.root)
        if value:
            self.fields[key].set(value)

    def config_values(self):
        values = self.stock.config()
        for key, var in self.fields.items():
            values[key] = var.get().strip()
        values['port'] = int(values['port'])
        parsed = urlsplit(values['url'])
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError('Use una URL HTTPS sin rutas: https://nombre-servidor:8443')
        return values

    def save_config(self):
        try:
            if self.server:
                raise ValueError('Detenga el servidor antes de cambiar su configuración.')
            self.stock.save_config(self.config_values())
            self.footer.set('Configuración guardada.')
            return True
        except Exception as e:
            self.error(e)
            return False

    def generate_certs(self):
        if self.server:
            return self.error(ValueError('Detenga el servidor antes de crear certificados.'))
        try:
            config = self.config_values()
            host = urlsplit(config['url']).hostname
        except Exception as e:
            return self.error(e)
        self.footer.set('Generando certificados para ' + host + '...')
        def job():
            from certificados import generate
            return generate(self.stock.directory / 'certificados', host)
        def done(result):
            for key, value in result.items():
                self.fields[key].set(value)
            self.save_config()
            self.footer.set('Certificados creados. Prepare los USB para distribuir la nueva CA pública.')
        self.background(job, done)

    def start_server(self):
        if self.server or not self.save_config():
            return
        try:
            config = self.stock.config()
            self.server = LicenseServer(self.stock, config['host'], config['port'], config['cert'], config['key'])
            self.server_thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True)
            self.server_thread.start()
            self.state_label.config(text='● Servidor activo', foreground='#18734b')
            self.start_button.config(state='disabled')
            self.stop_button.config(state='normal')
            self.footer.set('Escuchando en ' + config['url'] + '. Mantenga esta ventana abierta.')
        except Exception as e:
            self.server = None
            self.error(e)

    def stop_server(self):
        if not self.server:
            return
        self.stop_button.config(state='disabled')
        self.footer.set('Deteniendo el servidor...')
        server = self.server
        def job():
            server.shutdown()
            server.server_close()
        def done(_):
            self.server = None
            self.state_label.config(text='● Servidor detenido', foreground='#a34725')
            self.start_button.config(state='normal')
            self.footer.set('Servidor detenido. Las asignaciones se conservan.')
        self.background(job, done)

    def background(self, function, callback):
        self.jobs += 1
        def run():
            try:
                self.queue.put(('job', callback, function(), None))
            except Exception as e:
                self.queue.put(('job', callback, None, e))
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, callback, result, error = self.queue.get_nowait()
                if kind == 'log':
                    self.console.config(state='normal')
                    self.console.insert('end', result)
                    self.console.see('end')
                    self.console.config(state='disabled')
                else:
                    self.jobs -= 1
                    if error:
                        self.compile_button.config(state='normal')
                        self.error(error)
                    else:
                        callback(result)
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(100, self.poll)

    def auto_refresh(self):
        if not self.closing:
            self.refresh()
            self.root.after(3000, self.auto_refresh)

    def refresh(self):
        try:
            self.user_rows = self.stock.technicians()
            self.inventory_rows = self.stock.inventory()
            self.assignment_rows = self.stock.assignments()
            self.event_rows = self.stock.history()
            counts = {state: sum(r['state'] == state for r in self.inventory_rows) for state in STATES}
            for name, value in [('Total', len(self.inventory_rows)), ('Disponibles', counts['disponible']), ('Pendientes', counts['pendiente']),
                                ('Usadas', counts['usada']), ('Revisión', counts['revision']), ('Retiradas', counts['retirada']), ('Sin identificar', counts['sin identificar'])]:
                self.counters[name].set(f'{name}: {value}')
            self.render()
        except Exception as e:
            self.footer.set('No se pudo actualizar: ' + str(e))

    @staticmethod
    def matches(row, query, state):
        return (state == 'todos' or row['state'] == state) and query.casefold() in json.dumps(row, ensure_ascii=False).casefold()

    @staticmethod
    def populate(tree, rows):
        selected = tree.selection()
        previous_x, previous_y = tree.xview(), tree.yview()
        tree.delete(*tree.get_children())
        for iid, values, state in rows:
            tree.insert('', 'end', iid=str(iid), values=values, tags=(state,))
        if selected and tree.exists(selected[0]):
            tree.selection_set(selected[0])
        if previous_x:
            tree.xview_moveto(previous_x[0])
        if previous_y:
            tree.yview_moveto(previous_y[0])

    def render(self):
        if not hasattr(self, 'install_search'):
            return
        stock_rows = []
        for r in self.inventory_rows:
            if self.matches(r, self.stock_search.get(), self.stock_state.get()) and self.stock_edition.get() in ('todas', r['edition']) and self.stock_channel.get() in ('todos', r['channel']):
                info = json.loads(r['info'] or '{}')
                stock_rows.append((r['id'], (r['id'], r['name'], r['suffix'], r['edition'], r['channel'], r['reference'], r['state'], info.get('Serial', ''), info.get('Modelo', ''), local_date(r['updated'] or r['created'])), r['state']))
        install_rows = []
        for r in self.assignment_rows:
            if self.matches(r, self.install_search.get(), self.install_state.get()):
                info = json.loads(r['info'])
                install_rows.append((r['id'], (r['id'], r['license_id'], info.get('Serial', ''), info.get('Modelo', ''), info.get('Tecnico', ''), r['edition'], r['channel'], info.get('Windows', ''), r['state'], local_date(r['created'])), r['state']))
        self.populate(self.users_tree, [(r['id'], (r['id'], r['name'], 'Activo' if r['active'] else 'Inactivo', r['installations'], local_date(r['created']), local_date(r['updated'])), 'usada' if r['active'] else 'baja') for r in self.user_rows])
        groups = {}
        for row in self.inventory_rows:
            group = groups.setdefault((row['edition'], row['channel']), {'total': 0})
            group['total'] += 1
            group[row['state']] = group.get(row['state'], 0) + 1
        self.populate(self.types_tree, [(str(i), (edition, channel, counts['total'], counts.get('disponible', 0), counts.get('pendiente', 0),
                      counts.get('usada', 0), counts.get('revision', 0), counts.get('retirada', 0), counts.get('sin identificar', 0)), '')
                      for i, ((edition, channel), counts) in enumerate(sorted(groups.items()))])
        self.populate(self.stock_tree, stock_rows)
        self.populate(self.install_tree, install_rows)
        self.populate(self.history_tree, [(r['id'], (local_date(r['date']), r['action'], r['assignment'], r['detail']), '') for r in self.event_rows])

    def selected(self, tree):
        rows = tree.selection()
        if not rows:
            raise ValueError('Seleccione una fila primero.')
        return rows[0]

    def import_xml(self):
        files = filedialog.askopenfilenames(parent=self.root, title='Seleccionar XML o ZIP de licencias sin consumir', filetypes=[('Licencias XML / ZIP', '*.xml *.XML *.zip *.ZIP'), ('Todos los archivos', '*.*')])
        if files:
            self.do_import(files)

    def import_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title='Carpeta de licencias XML sin consumir')
        if folder:
            self.do_import([folder])

    def do_import(self, files):
        def done(results):
            self.refresh()
            self.footer.set(f"Importados: {sum(r[1] == 'importado' for r in results)} · Duplicados: {sum(r[1] == 'duplicado' for r in results)} · Errores: {sum(r[1].startswith('error:') for r in results)}")
            self.show_text('Resultado de importación', '\n'.join(f'{name}: {result}' for name, result in results) or 'No se encontraron XML.')
        self.background(lambda: self.stock.import_files(files), done)

    def classify_license(self):
        try:
            iid = int(self.selected(self.stock_tree))
            row = self.stock.license_details(iid)
        except Exception as e:
            return self.error(e)
        window = tk.Toplevel(self.root)
        window.title('Datos y clasificación de licencia')
        window.geometry('650x440')
        window.transient(self.root)
        viewport = ScrollFrame(window, min_width=580)
        viewport.pack(fill='both', expand=True)
        frame = ttk.Frame(viewport.content, padding=20)
        frame.pack(fill='both', expand=True)
        text = f"Licencia #{iid} · {row['name']} · *****-{row['suffix']}\nReferencia: {row['reference'] or 'No indicada'}\nEstado XML: {row['xml_state'] or 'No indicado'}\nClasificación actual: {row['classification_source']}"
        ttk.Label(frame, text=text, wraplength=600).pack(anchor='w', pady=10)
        edition = tk.StringVar(value=row['edition'])
        channel = tk.StringVar(value=row['channel'])
        for label, var, values in [('Edición Windows', edition, EDITIONS), ('Tipo de licencia', channel, CHANNELS)]:
            ttk.Label(frame, text=label).pack(anchor='w', pady=(8, 3))
            ttk.Combobox(frame, textvariable=var, values=values, state='readonly', width=35).pack(anchor='w')
        apply_reference = tk.BooleanVar(value=bool(row['reference']))
        ttk.Checkbutton(frame, text='Aplicar a todas con esta referencia y recordar para futuras importaciones', variable=apply_reference,
                        state='normal' if row['reference'] else 'disabled').pack(anchor='w', pady=14)
        ttk.Label(frame, text='Use la clasificación de su proveedor. Un estado numérico o una clave por sí solos no indican Pro / Home / CMAR.', wraplength=600).pack(anchor='w')
        def save():
            try:
                count = self.stock.set_classification(iid, edition.get(), channel.get(), apply_reference.get())
                self.refresh()
                self.footer.set(f'Clasificación guardada. Licencias actualizadas: {count}.')
                window.destroy()
            except Exception as e:
                self.error(e)
        ttk.Button(frame, text='Guardar clasificación', command=save).pack(anchor='w', pady=15)

    def toggle_stock(self):
        try:
            iid = int(self.selected(self.stock_tree))
            row = next(r for r in self.inventory_rows if r['id'] == iid)
            if row['assignment']:
                raise ValueError('La licencia está asignada. Revise su instalación y dé de baja la asignación primero.')
            enabled = not row['enabled']
            self.stock.toggle(iid, enabled)
            self.refresh()
            self.footer.set('Licencia habilitada.' if enabled else 'Licencia retirada del stock disponible. Puede volver a habilitarla.')
        except Exception as e:
            self.error(e)

    def stock_install(self):
        try:
            iid = int(self.selected(self.stock_tree))
            row = next(r for r in self.inventory_rows if r['id'] == iid)
            if not row['assignment']:
                raise ValueError('La licencia no tiene una asignación activa. Consulte Instalaciones para ver asignaciones antiguas.')
            self.show_assignment(row['assignment'])
        except Exception as e:
            self.error(e)

    def install_details(self):
        try:
            self.show_assignment(self.selected(self.install_tree))
        except Exception as e:
            self.error(e)

    def show_assignment(self, aid):
        row = next(r for r in self.stock.assignments() if r['id'] == aid)
        info = json.loads(row['info'])
        result = json.loads(row['result'])
        lines = [f"Asignación: {aid}", f"Licencia: #{row['license_id']} · {row['name']} · *****-{row['suffix']}",
                 f"Clasificación: {row['edition']} / {row['channel']} · Referencia: {row['reference']}", f"Estado: {row['state']}", f"Asignada: {local_date(row['created'])}", f"Actualizada: {local_date(row['updated'])}",
                 f"UUID: {row['machine']}", '', 'DATOS DEL EQUIPO']
        lines += [f'{k}: {v}' for k, v in info.items()]
        lines += ['', 'RESULTADO DE INSTALACIÓN'] + [f'{k}: {v}' for k, v in result.items()]
        lines += [f"Detalle: {row['detail']}", '', 'HISTORIAL']
        lines += [f"{local_date(e['date'])} · {e['action']} · {e['detail']}" for e in self.stock.history(aid)]
        self.show_text('Detalle de instalación', '\n'.join(lines))

    def release(self):
        try:
            aid = self.selected(self.install_tree)
            row = next(r for r in self.assignment_rows if r['id'] == aid)
            if row['state'] == 'baja':
                raise ValueError('Esta asignación ya está de baja.')
            reason = simpledialog.askstring('Dar de baja', 'Motivo de la baja (obligatorio):', parent=self.root)
            if reason is None:
                return
            if not reason.strip():
                raise ValueError('Debe indicar un motivo.')
            if not messagebox.askyesno('Devolver licencia al stock', 'La licencia volverá a estar disponible para otro PC.\nEsta operación no desinstala la clave del equipo anterior.\n\n¿Ha verificado que procede devolverla al stock?', parent=self.root):
                return
            self.stock.release(aid, reason)
            self.refresh()
            self.footer.set('Baja registrada. Historial conservado; licencia disponible si está habilitada.')
        except Exception as e:
            self.error(e)

    def backup(self):
        path = filedialog.asksaveasfilename(parent=self.root, title='Copia de seguridad de la base', defaultextension='.db',
                                          initialfile='licencias_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.db')
        if path:
            self.background(lambda: self.stock.backup(path), lambda _: self.footer.set('Copia creada. Guarde aparte la configuración y los certificados.'))

    def export_stock(self):
        rows = [self.stock_tree.item(iid)['values'] for iid in self.stock_tree.get_children()]
        self.export_csv(['ID', 'XML', 'Ultimos5', 'Edicion', 'Tipo', 'Referencia', 'Estado', 'Serie', 'Modelo', 'Actualizado'], rows)

    def export_installs(self):
        rows = []
        for r in self.assignment_rows:
            if self.matches(r, self.install_search.get(), self.install_state.get()):
                i = json.loads(r['info'])
                result = json.loads(r['result'])
                rows.append([r['id'], r['license_id'], r['name'], r['suffix'], r['edition'], r['channel'], r['reference'], r['machine'], i.get('Serial'), i.get('Fabricante'),
                             i.get('Modelo'), i.get('Windows'), i.get('Version'), i.get('Build'), i.get('Tecnico'), i.get('IP'), r['state'],
                             local_date(r['created']), local_date(r['updated']), result.get('before_partial'), result.get('after_partial'),
                             result.get('license_status'), result.get('code'), result.get('error'), r['detail']])
        self.export_csv(['Asignacion', 'Licencia', 'XML', 'Ultimos5', 'Edicion', 'Tipo', 'Referencia', 'UUID', 'Serie', 'Fabricante', 'Modelo', 'Windows', 'Version', 'Build',
                         'Tecnico', 'IP', 'Estado', 'Asignada', 'Actualizada', 'ClaveAnteriorUltimos5', 'ClaveInstaladaUltimos5',
                         'EstadoWindows', 'Codigo', 'Error', 'Detalle'], rows)

    def export_csv(self, headers, rows):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(headers)
                writer.writerows([[safe_cell(cell) for cell in row] for row in rows])
            self.footer.set('CSV exportado con los filtros actuales, sin claves completas.')
        except Exception as e:
            self.error(e)

    def compile_client(self):
        if os.name != 'nt':
            return self.error(ValueError('Compile el EXE en Windows. Use app_usb/COMPILAR.bat.'))
        self.compile_button.config(state='disabled')
        self.footer.set('Compilando el cliente; puede tardar varios minutos...')
        def job():
            process = subprocess.Popen([sys.executable, str(APP_USB / 'compilar.py')], cwd=APP_USB,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW,
                                       env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'})
            for line in process.stdout:
                self.queue.put(('log', None, line, None))
            if process.wait() != 0:
                raise RuntimeError('Falló la compilación. Consulte el registro de esta pestaña.')
        def done(_):
            self.compile_button.config(state='normal')
            self.footer.set('EXE generado en app_usb/salida. Ya puede preparar el pendrive.')
        self.background(job, done)

    def prepare_usb(self):
        try:
            if not self.server and not self.save_config():
                return
            config = self.stock.config()
            exe = APP_USB / 'salida' / 'PULSIA_Cliente_Licencias.exe'
            if not exe.exists():
                raise ValueError('Compile primero el EXE del cliente.')
            ca = Path(config.get('ca', ''))
            if not ca.is_file():
                raise ValueError('Seleccione el certificado CA público antes de preparar el USB.')
            # Validar que es un certificado PEM, nunca una clave privada.
            ca_bytes = ca.read_bytes()
            if b'PRIVATE KEY' in ca_bytes or b'BEGIN CERTIFICATE' not in ca_bytes:
                raise ValueError('El archivo CA debe contener solo certificados PEM públicos.')
            folder = filedialog.askdirectory(parent=self.root, title='Seleccione el pendrive o carpeta destino')
            if not folder:
                return
            destination = Path(folder)
            files = [destination / 'PULSIA_Cliente_Licencias.exe', destination / 'config.json', destination / 'ca.pem']
            if any(p.exists() for p in files) and not messagebox.askyesno('Actualizar cliente USB', 'Se reemplazarán el EXE, config.json y ca.pem existentes en la carpeta elegida. ¿Continuar?', parent=self.root):
                return
            if exe.resolve() != files[0].resolve():
                shutil.copy2(exe, files[0])
            files[1].write_text(json.dumps({'servidor': config['url'], 'token': config['client_token']}, indent=2), encoding='utf-8')
            files[2].write_bytes(ca_bytes)
            self.footer.set('Pendrive preparado: EXE, configuración y certificado CA público.')
        except Exception as e:
            self.error(e)

    def open_usb_folder(self):
        try:
            if os.name == 'nt':
                os.startfile(APP_USB)
            else:
                subprocess.Popen(['xdg-open', str(APP_USB)])
        except Exception as e:
            self.error(e)

    def show_text(self, title, text):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.geometry('850x580')
        body = ttk.Frame(window, padding=14)
        body.pack(fill='both', expand=True)
        view_frame, view = scrolled_text(body, font=('Consolas', 10))
        view_frame.pack(fill='both', expand=True)
        view.insert('1.0', text)
        view.config(state='disabled')

    def error(self, error):
        self.footer.set('Error: ' + str(error))
        messagebox.showerror('PULSIA Licencias', str(error), parent=self.root)

    def close(self):
        if self.jobs:
            return messagebox.showinfo('Operación en curso', 'Espere a que terminen las tareas antes de cerrar.', parent=self.root)
        if self.server:
            self.stop_server()
            return messagebox.showinfo('Deteniendo servidor', 'El servidor se está deteniendo. Cierre la ventana cuando termine.', parent=self.root)
        self.closing = True
        self.root.destroy()


def main():
    root = tk.Tk()
    ServerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
