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
from tkinter import ttk, messagebox
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
    return powershell("""$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$b=Get-CimInstance Win32_BIOS
$c=Get-CimInstance Win32_ComputerSystem
$o=Get-CimInstance Win32_OperatingSystem
$u=Get-CimInstance Win32_ComputerSystemProduct
@{machine="$($u.UUID)";info=@{Serial="$($b.SerialNumber)";Fabricante="$($c.Manufacturer)";Modelo="$($c.Model)";Windows="$($o.Caption)";Version="$($o.Version)";Build="$($o.BuildNumber)"}} | ConvertTo-Json -Compress
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

class Client:
    def __init__(self,root):
        self.root=root; self.q=queue.Queue(); self.running=False
        root.title('PULSIA · Cliente de licencias'); root.geometry('760x540'); root.minsize(620,420)
        frame=ttk.Frame(root,padding=20); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='PULSIA · Instalación CMAR',font=('Segoe UI',18,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Licencia asignada desde el servidor de la red local.').pack(anchor='w',pady=(4,16))
        self.technician=tk.StringVar()
        tech_row=ttk.Frame(frame); tech_row.pack(fill='x',pady=6)
        ttk.Label(tech_row,text='Técnico (opcional):').pack(side='left')
        self.tech_entry=ttk.Entry(tech_row,textvariable=self.technician,width=35); self.tech_entry.pack(side='left',padx=8)
        self.status=tk.StringVar(value='Preparado. Compruebe config.json antes de empezar.')
        ttk.Label(frame,textvariable=self.status,wraplength=650).pack(anchor='w',pady=8)
        self.button=ttk.Button(frame,text='Solicitar e instalar licencia',command=self.start); self.button.pack(anchor='w',pady=8)
        self.progress=ttk.Progressbar(frame,mode='indeterminate'); self.progress.pack(fill='x',pady=8)
        self.log=tk.Text(frame,height=12,state='disabled',wrap='word'); self.log.pack(fill='both',expand=True)
        ttk.Label(frame,text='Instala la clave y verifica su sufijo. No ejecuta la activación de Windows.').pack(anchor='w',pady=(10,0))
        root.protocol('WM_DELETE_WINDOW',self.close); root.after(100,self.poll)
    def close(self):
        if self.running:
            messagebox.showinfo('Operación en curso','Espere a que termine la operación antes de cerrar.'); return
        self.root.destroy()
    def emit(self,text): self.q.put(('message',text))
    def poll(self):
        try:
            while True:
                kind,text=self.q.get_nowait()
                self.status.set(text)
                self.log.config(state='normal'); self.log.insert('end',text+'\n'); self.log.see('end'); self.log.config(state='disabled')
                if kind=='done':
                    self.running=False; self.button.config(state='normal'); self.tech_entry.config(state='normal'); self.progress.stop()
        except queue.Empty: pass
        self.root.after(100,self.poll)
    def start(self):
        self.running=True; self.button.config(state='disabled'); self.tech_entry.config(state='disabled'); self.progress.start()
        self.technician_value=self.technician.get().strip()[:100]
        threading.Thread(target=self.work,daemon=True).start()
    def work(self):
        assignment=None; installed=False
        try:
            if os.name!='nt' or not ctypes.windll.shell32.IsUserAnAdmin(): raise RuntimeError('Ejecute la aplicación como administrador.')
            config=json.loads((BASE/'config.json').read_text(encoding='utf-8-sig'))
            url=config['servidor'].rstrip('/'); token=config['token']
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
                    messages={401:'Token rechazado por el servidor.',409:'No hay licencias disponibles.',400:'El servidor rechazó la solicitud.'}
                    raise RuntimeError(messages.get(e.code,'El servidor devolvió un error HTTP.')) from None
                except (urllib.error.URLError,TimeoutError,OSError):
                    raise RuntimeError('No se pudo conectar por HTTPS. Revise red, servidor y certificado.') from None
            self.emit('Leyendo los datos del equipo...')
            data=info(); machine=str(uuid.UUID(data['machine'])).upper()
            if machine in ('00000000-0000-0000-0000-000000000000','FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF'): raise RuntimeError('UUID de firmware no válido.')
            data['machine']=machine
            data['info']['Tecnico']=self.technician_value
            self.emit('Equipo: '+data['info']['Modelo']+' · Serie: '+data['info']['Serial'])
            self.emit('Solicitando una licencia exclusiva al servidor...')
            assignment=api('/reserve',data)
            self.emit('Asignación: '+assignment['id'])
            raw=assignment['xml']
            if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper(): raise RuntimeError('XML no admitido.')
            xml=ET.fromstring(raw)
            keys=[(e.text or '').strip().upper() for e in xml.iter() if e.tag.split('}')[-1]=='ProductKey']
            if len(keys)!=1: raise RuntimeError('El XML no contiene una única ProductKey.')
            self.emit('Instalando y comprobando la clave...')
            result=install(keys[0])
            installed=bool(result['ok'])
            api('/report',{'id':assignment['id'],'machine':machine,'state':'usada' if installed else 'revision','detail':'Instalacion verificada por sufijo.' if installed else 'Windows no verifico la instalacion.', 'result':{k:v for k,v in result.items() if k != 'ok'}})
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
