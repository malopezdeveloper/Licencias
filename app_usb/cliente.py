"""Cliente USB PULSIA. Se compila en Windows con COMPILAR.bat."""
import ctypes
import json
import os
from pathlib import Path
import queue
import re
import ssl
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from urllib.parse import urlsplit
import ipaddress
import tempfile

try:
    from .widgets import ScrollFrame, scrolled_text
except ImportError:
    from widgets import ScrollFrame, scrolled_text
import urllib.request
import urllib.error
import uuid
import xml.etree.ElementTree as ET

BASE=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
APP_ID='55c92734-d682-4d71-983e-d6ec3f16059f' # Windows licensing application.
PS=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'

def powershell(script):
    result=subprocess.run([str(PS),'-NoLogo','-NoProfile','-NonInteractive','-Command','-'],input=script,
                          text=True,encoding='utf-8',errors='replace',capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW,timeout=120)
    if result.returncode: raise RuntimeError('Windows no pudo completar la consulta o instalacion de licencia.')
    try: return json.loads(result.stdout.strip().lstrip('\ufeff'))
    except ValueError: raise RuntimeError('Windows devolvio una respuesta no reconocida.') from None

def info():
    return powershell(r"""$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$b=Get-CimInstance Win32_BIOS
$c=Get-CimInstance Win32_ComputerSystem
$o=Get-CimInstance Win32_OperatingSystem
$u=Get-CimInstance Win32_ComputerSystemProduct
$edition=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').EditionID
@{machine="$($u.UUID)";edition="$edition";info=@{Serial="$($b.SerialNumber)";Fabricante="$($c.Manufacturer)";Modelo="$($c.Model)";Windows="$($o.Caption)";Version="$($o.Version)";Build="$($o.BuildNumber)"}} | ConvertTo-Json -Compress
""")

def install(key):
    if not re.fullmatch(r'[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}',key): raise RuntimeError('Clave XML no valida.')
    # Clave por stdin: no se muestra como argumento de un proceso ni en el registro.
    script="""$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$result=@{ok=$false;before_partial='';after_partial='';license_status='';code='';error=''}
try {
 $before=@(Get-CimInstance SoftwareLicensingProduct -Filter "ApplicationID='APP_VALUE'" | Where-Object {$_.PartialProductKey} | Sort-Object LicenseStatus -Descending)
 if ($before.Count -gt 0) { $result.before_partial="$($before[0].PartialProductKey)" }
 $s=Get-CimInstance SoftwareLicensingService
 $r=Invoke-CimMethod -InputObject $s -MethodName InstallProductKey -Arguments @{ProductKey='KEY_VALUE'}
 $result.code="$($r.ReturnValue)"
 if ($r.ReturnValue -ne 0) { throw 'InstallProductKey failed' }
 $p=@(Get-CimInstance SoftwareLicensingProduct -Filter "ApplicationID='APP_VALUE'" | Where-Object {$_.PartialProductKey -eq 'SUFFIX_VALUE'})
 $result.ok=($p.Count -gt 0)
 if ($p.Count -gt 0) {
   $result.after_partial="$($p[0].PartialProductKey)"
   $result.license_status="$($p[0].LicenseStatus)"
 }
 if (-not $result.ok) { $result.error='No se encontro el sufijo esperado tras instalar.' }
} catch {
 $result.error='Windows no pudo instalar o verificar la clave.'
 if (-not $result.code) { $result.code="$($_.Exception.HResult)" }
}
$result | ConvertTo-Json -Compress
"""
    return powershell(script.replace('KEY_VALUE',key).replace('APP_VALUE',APP_ID).replace('SUFFIX_VALUE',key[-5:]))

def detected_edition(value):
    # EditionID proviene del registro de Windows; no se deduce del tipo de clave.
    return {'professional':'Pro', 'core':'Home', 'professionaln':'Pro N', 'coren':'Home N',
            'coresinglelanguage':'Home Single Language', 'enterprise':'Enterprise', 'enterprisen':'Enterprise N',
            'education':'Education', 'educationn':'Education N', 'professionaleducation':'Pro Education',
            'professionalworkstation':'Pro for Workstations'}.get(str(value).casefold(), '')

def normalize_server(value, default_port=8443):
    value = str(value).strip()
    if not value:
        raise ValueError('Indique la IP o el nombre del servidor.')
    # Una IP sin esquema utiliza HTTPS y el puerto habitual del servidor.
    if '://' not in value:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            address = None
        if address and address.version == 6:
            value = '[' + str(address) + ']'
        value = 'https://' + value
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
    except ValueError:
        raise ValueError('Dirección o puerto no válidos.') from None
    if parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('Use una IP o dirección HTTPS sin rutas ni credenciales.')
    try:
        address = ipaddress.ip_address(host)
        host = str(address)
        if address.version == 6:
            host = '[' + host + ']'
    except ValueError:
        host = host.encode('idna').decode('ascii').lower()
        if len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
            raise ValueError('Nombre del servidor no válido.')
        if re.fullmatch(r'[0-9.]+', host):
            raise ValueError('IP no válida.')
    if port is None:
        port = default_port
    if not 1 <= port <= 65535:
        raise ValueError('Puerto fuera de rango.')
    return f'https://{host}:{port}'


def load_config():
    path = BASE / 'config.json'
    if not path.exists():
        return {}
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(config, dict):
        raise ValueError('config.json debe contener un objeto JSON.')
    return config


def save_server(value):
    config = load_config()
    url = normalize_server(value)
    config['servidor'] = url
    config['servidor_confirmado'] = True
    # Mantener token y demás ajustes. Reemplazo atómico, sin truncar la memoria anterior.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=BASE, prefix='config_', suffix='.tmp', delete=False) as f:
            temp_path = Path(f.name)
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(BASE / 'config.json')
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
    return url


def create_api(config):
    url=config['servidor'].rstrip('/'); token=config.get('token','')
    from urllib.parse import urlsplit
    parts=urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise RuntimeError('Configure una dirección HTTPS válida en config.json.')
    if not token or token.startswith('COPIAR_'): raise RuntimeError('Configure el token del servidor en config.json.')
    context=ssl.create_default_context()
    if (BASE/'ca.pem').exists(): context.load_verify_locations(cafile=str(BASE/'ca.pem'))
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs): return None
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=context))
    def api(route,payload):
        req=urllib.request.Request(url+route,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
        try:
            with opener.open(req,timeout=30) as response: return json.load(response)
        except urllib.error.HTTPError as e:
            messages={401:'Token rechazado por el servidor.',409:'No hay licencias disponibles para la edición y el tipo solicitados.',400:'Solicitud rechazada. Revise la edición y clasifique el stock en el servidor.',422:'El técnico no está disponible. Actualice la lista y seleccione un usuario activo.'}
            raise RuntimeError(messages.get(e.code,'El servidor devolvió un error HTTP.')) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise RuntimeError('No se pudo conectar por HTTPS. Revise red, servidor y certificado.') from None
    return api


class Client:
    def __init__(self,root):
        self.root=root; self.q=queue.Queue(); self.running=False; self.loading_users=False; self.technicians={}
        root.title('PULSIA · Cliente de licencias'); root.geometry('900x700'); root.minsize(540,380)
        self.viewport=ScrollFrame(root,min_width=720)
        self.viewport.pack(fill='both',expand=True)
        frame=ttk.Frame(self.viewport.content,padding=20); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='PULSIA · Instalación de licencia',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Licencia asignada desde el servidor de la red local.').pack(anchor='w',pady=(4,16))
        server_row=ttk.Frame(frame); server_row.pack(fill='x',pady=6)
        server_row.columnconfigure(1,weight=1)
        ttk.Label(server_row,text='Servidor:').grid(row=0,column=0,sticky='w')
        self.server_address=tk.StringVar(value='Sin configurar')
        self.server_entry=ttk.Entry(server_row,textvariable=self.server_address,state='readonly')
        self.server_entry.grid(row=0,column=1,sticky='ew',padx=8)
        self.server_button=ttk.Button(server_row,text='Cambiar IP / servidor',command=self.change_server)
        self.server_button.grid(row=0,column=2,sticky='e')
        self.technician=tk.StringVar()
        tech_row=ttk.Frame(frame); tech_row.pack(fill='x',pady=6)
        ttk.Label(tech_row,text='Técnico:').pack(side='left')
        self.tech_entry=ttk.Combobox(tech_row,textvariable=self.technician,width=35,state='readonly'); self.tech_entry.pack(side='left',padx=8)
        self.tech_entry.bind('<<ComboboxSelected>>',lambda _:self.idle_controls())
        self.refresh_users_button=ttk.Button(tech_row,text='Conectar / actualizar técnicos',command=self.refresh_technicians)
        self.refresh_users_button.pack(side='left',padx=6)
        type_row=ttk.Frame(frame); type_row.pack(fill='x',pady=6)
        self.edition=tk.StringVar(value='Automática (Windows)')
        self.channel=tk.StringVar(value='Cualquiera')
        ttk.Label(type_row,text='Edición:').pack(side='left')
        self.edition_box=ttk.Combobox(type_row,textvariable=self.edition,values=('Automática (Windows)','Pro','Home','Pro N','Home N','Home Single Language','Enterprise','Enterprise N','Education','Education N','Pro Education','Pro for Workstations'),state='readonly',width=24)
        self.edition_box.pack(side='left',padx=6)
        ttk.Label(type_row,text='Tipo:').pack(side='left')
        self.channel_box=ttk.Combobox(type_row,textvariable=self.channel,values=('Cualquiera','CMAR','OEM','Retail','Volumen MAK','Volumen KMS','Volumen'),state='readonly',width=16)
        self.channel_box.pack(side='left',padx=6)
        self.status=tk.StringVar(value='Preparado. Configure el servidor para empezar.')
        self.status_label=ttk.Label(frame,textvariable=self.status,wraplength=650)
        self.status_label.pack(fill='x',pady=8)
        self.button=ttk.Button(frame,text='Solicitar e instalar licencia',command=self.start,state='disabled'); self.button.pack(anchor='w',pady=8)
        self.progress=ttk.Progressbar(frame,mode='indeterminate'); self.progress.pack(fill='x',pady=8)
        log_frame,self.log=scrolled_text(frame,height=12,state='disabled')
        log_frame.pack(fill='both',expand=True)
        self.note_label=ttk.Label(frame,text='Instala la clave y verifica su sufijo. No ejecuta la activación de Windows.',wraplength=650)
        self.note_label.pack(fill='x',pady=(10,0))
        frame.bind('<Configure>',lambda e:[label.configure(wraplength=max(300,e.width-40)) for label in (self.status_label,self.note_label)])
        root.protocol('WM_DELETE_WINDOW',self.close); root.after(100,self.poll)
        root.after_idle(self.first_server)
    def first_server(self):
        try:
            config=load_config()
            current=config.get('servidor','')
            if current:
                self.server_address.set(normalize_server(current))
            if not current or not config.get('servidor_confirmado',False):
                self.change_server(first=True)
            else:
                self.status.set('Servidor guardado en el pendrive.')
            if load_config().get('servidor_confirmado',False): self.refresh_technicians()
        except (ValueError,OSError) as e:
            self.status.set('No se pudo leer la configuración. Revise config.json o pulse Cambiar IP / servidor.')
            messagebox.showerror('Configuración',str(e),parent=self.root)

    def change_server(self,first=False):
        if self.running or self.loading_users:
            return
        initial=self.server_address.get()
        if initial=='Sin configurar': initial=''
        value=simpledialog.askstring('Servidor de licencias',
            'Introduzca la IP del servidor (ej. 192.168.1.139).\nTambién admite nombre o IP:puerto. Se guardará en este pendrive.',
            initialvalue=initial,parent=self.root)
        if value is None:
            if first:self.status.set('Configuración pendiente. Pulse Cambiar IP / servidor antes de instalar.')
            return
        try:
            url=save_server(value)
            self.server_address.set(url)
            self.technicians.clear()
            self.technician.set('')
            self.tech_entry.configure(values=())
            self.status.set('Servidor guardado. Conectando para obtener los técnicos...')
            self.refresh_technicians()
        except (ValueError,OSError) as e:
            messagebox.showerror('No se pudo guardar el servidor',str(e),parent=self.root)
            self.status.set('No se guardó el cambio. Compruebe la dirección y que el pendrive permita escritura.')

    def idle_controls(self):
        busy=self.running or self.loading_users
        self.button.config(state='normal' if not busy and self.technician.get() in self.technicians else 'disabled')
        self.tech_entry.config(state='disabled' if busy else 'readonly')
        self.server_button.config(state='disabled' if busy else 'normal')
        self.refresh_users_button.config(state='disabled' if busy else 'normal')
        self.edition_box.config(state='disabled' if self.running else 'readonly')
        self.channel_box.config(state='disabled' if self.running else 'readonly')

    def refresh_technicians(self):
        if self.running or self.loading_users:
            return
        try:
            config=load_config()
            if not config.get('servidor_confirmado',False):
                self.status.set('Configure primero la IP del servidor.')
                return
            self.loading_users=True
            self.idle_controls()
            self.status.set('Conectando al servidor para obtener los técnicos...')
            threading.Thread(target=self.users_worker,args=(dict(config),),daemon=True).start()
        except (ValueError,OSError) as e:
            self.loading_users=False
            self.idle_controls()
            self.status.set('No se pudo leer la configuración: '+str(e))

    def users_worker(self,config):
        try:
            result=create_api(config)('/technicians',{})
            rows=result.get('technicians')
            if not isinstance(rows,list) or any(not isinstance(r,dict) or type(r.get('id')) is not int or not isinstance(r.get('name'),str) or not r['name'].strip() for r in rows):
                raise RuntimeError('Lista de técnicos no válida recibida del servidor.')
            self.q.put(('users',{'technicians':rows}))
        except Exception as e:
            message=str(e) if isinstance(e,RuntimeError) else 'No se pudo obtener la lista de técnicos. Revise la configuración y el servidor.'
            self.q.put(('users',{'technicians':[],'error':message}))

    def apply_technicians(self,result):
        previous=self.technicians.get(self.technician.get())
        self.technicians={r['name']:r['id'] for r in result['technicians']}
        self.tech_entry.config(values=tuple(self.technicians))
        self.technician.set(next((name for name,iid in self.technicians.items() if iid==previous),''))
        self.loading_users=False
        self.idle_controls()
        self.status.set(result.get('error') or ('Seleccione un técnico de la lista del servidor.' if self.technicians else 'No hay técnicos activos. Añádalos en Usuarios / técnicos del servidor y actualice la lista.'))

    def close(self):
        if self.running:
            messagebox.showinfo('Operación en curso','Espere a que termine la operación antes de cerrar.'); return
        self.root.destroy()
    def emit(self,text): self.q.put(('message',text))
    def poll(self):
        try:
            while True:
                kind,text=self.q.get_nowait()
                if kind=='users':
                    self.apply_technicians(text)
                    continue
                self.status.set(text)
                self.log.config(state='normal'); self.log.insert('end',text+'\n'); self.log.see('end'); self.log.config(state='disabled')
                if kind=='done':
                    self.running=False; self.idle_controls(); self.progress.stop()
        except queue.Empty: pass
        self.root.after(100,self.poll)
    def start(self):
        if self.running or self.loading_users: return
        selected_id=self.technicians.get(self.technician.get())
        if selected_id is None:
            self.status.set('Conecte al servidor y seleccione un técnico de su lista.')
            return
        try:
            config=load_config()
            if not config.get('servidor_confirmado',False):
                self.change_server(first=True)
                config=load_config()
                if not config.get('servidor_confirmado',False): return
            self.connection_config=dict(config)
        except (ValueError,OSError) as e:
            messagebox.showerror('Configuración',str(e),parent=self.root)
            return
        self.server_button.config(state='disabled')
        self.running=True; self.button.config(state='disabled'); self.tech_entry.config(state='disabled'); self.progress.start()
        self.technician_id=selected_id
        self.idle_controls()
        self.requested_edition=self.edition.get()
        self.requested_channel=self.channel.get()
        self.edition_box.config(state='disabled'); self.channel_box.config(state='disabled')
        threading.Thread(target=self.work,daemon=True).start()
    def work(self):
        assignment=None; installed=False
        try:
            if os.name!='nt' or not ctypes.windll.shell32.IsUserAnAdmin(): raise RuntimeError('Ejecute la aplicación como administrador.')
            config=getattr(self,'connection_config',None) or load_config()
            api=create_api(config)
            self.emit('Leyendo los datos del equipo...')
            data=info(); machine=str(uuid.UUID(data['machine'])).upper()
            if machine in ('00000000-0000-0000-0000-000000000000','FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF'): raise RuntimeError('UUID de firmware no válido.')
            data['machine']=machine
            selected_edition=getattr(self,'requested_edition','Automática (Windows)')
            selected_channel=getattr(self,'requested_channel','Cualquiera')
            if selected_edition == 'Automática (Windows)':
                selected_edition=detected_edition(data.get('edition',''))
            if not selected_edition:
                raise RuntimeError('No se reconoce la edición instalada. Seleccione una edición compatible antes de solicitar licencia.')
            data['edition']=selected_edition
            if selected_channel != 'Cualquiera': data['channel']=selected_channel
            data['technician_id']=self.technician_id
            self.emit('Equipo: '+data['info']['Modelo']+' · Serie: '+data['info']['Serial'])
            self.emit('Solicitando una licencia exclusiva al servidor...')
            assignment=api('/reserve',data)
            self.emit('Asignación: '+assignment['id'])
            self.emit('Licencia: '+assignment.get('edition',selected_edition)+' / '+assignment.get('channel','Tipo no indicado'))
            raw=assignment['xml']
            if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper(): raise RuntimeError('XML no admitido.')
            xml=ET.fromstring(raw)
            keys=[(e.text or '').strip().upper() for e in xml.iter() if e.tag.split('}')[-1]=='ProductKey']
            if len(keys)!=1: raise RuntimeError('El XML no contiene una única ProductKey.')
            self.emit('Instalando y comprobando la clave...')
            result=install(keys[0])
            installed=bool(result['ok'])
            api('/report',{'id':assignment['id'],'machine':machine,'technician_id':self.technician_id,'state':'usada' if installed else 'revision','detail':'Instalacion verificada por sufijo.' if installed else 'Windows no verifico la instalacion.', 'result':{k:v for k,v in result.items() if k != 'ok'}})
            if not installed: raise RuntimeError('Instalación no verificada. Licencia bloqueada para revisión.')
            self.q.put(('done','CORRECTO: clave instalada y registrada como usada. Últimos cinco: '+keys[0][-5:]))
        except Exception as e:
            # No mostrar respuestas crudas de Windows/XML, que podrían contener claves.
            known=isinstance(e,RuntimeError)
            text=str(e) if known else 'Error al leer la configuración, el equipo o la respuesta. Revise la configuración y reintente.'
            if assignment:
                text+=' La licencia permanece bloqueada. Reintente en este mismo PC.'
                if installed: text+=' Windows ya tiene la clave instalada; falta confirmar al servidor.'
            self.q.put(('done','ERROR: '+text))

if __name__=='__main__':
    root=tk.Tk(); Client(root); root.mainloop()
