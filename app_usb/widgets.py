"""Contenedores con desplazamiento, compartidos por servidor y cliente portable."""
import tkinter as tk
from tkinter import ttk


class ScrollFrame(ttk.Frame):
    """La vista crece con la ventana y conserva acceso al contenido al reducirla."""
    def __init__(self, parent, min_width=600, min_height=0):
        super().__init__(parent)
        self.min_width = min_width
        self.min_height = min_height
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background='#eef2f6')
        self.vertical = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vertical.set, xscrollcommand=self.horizontal.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.vertical.grid(row=0, column=1, sticky='ns')
        self.horizontal.grid(row=1, column=0, sticky='ew')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.canvas.bind('<Configure>', self.resize)
        self.content.bind('<Configure>', self.resize)
        top = self.winfo_toplevel()
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            top.bind(sequence, self.wheel, add='+')

    def resize(self, event=None):
        if not self.winfo_exists():
            return
        width = max(self.min_width, self.canvas.winfo_width())
        height = max(self.min_height, self.content.winfo_reqheight(), self.canvas.winfo_height())
        self.canvas.itemconfigure(self.window, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def wheel(self, event):
        if not self.winfo_exists():
            return
        widget = event.widget
        # Textos, tablas y listas conservan su propio desplazamiento con la rueda.
        if isinstance(widget, (tk.Text, ttk.Treeview, ttk.Combobox, tk.Listbox)):
            return
        current = widget
        while current is not None and current is not self:
            current = getattr(current, 'master', None)
        if current is not self:
            return
        direction = -1 if getattr(event, 'num', None) == 4 or getattr(event, 'delta', 0) > 0 else 1
        if event.state & 1:
            self.canvas.xview_scroll(direction * 3, 'units')
        else:
            self.canvas.yview_scroll(direction * 3, 'units')
        return 'break'


def scrolled_text(parent, **options):
    """Devuelve contenedor y Text; ambos ejes disponibles para registros largos."""
    wrapper = ttk.Frame(parent)
    text = tk.Text(wrapper, wrap='none', **options)
    vertical = ttk.Scrollbar(wrapper, orient='vertical', command=text.yview)
    horizontal = ttk.Scrollbar(wrapper, orient='horizontal', command=text.xview)
    text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    text.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    wrapper.rowconfigure(0, weight=1)
    wrapper.columnconfigure(0, weight=1)
    return wrapper, text
