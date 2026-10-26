"""Compila el cliente Windows. No requiere ni incluye licencias reales."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    if os.name != 'nt':
        raise RuntimeError('El EXE debe compilarse en Windows.')
    os.chdir(ROOT)
    env_python = ROOT / 'build-env/Scripts/python.exe'
    if not env_python.exists():
        subprocess.run([sys.executable, '-m', 'venv', 'build-env'], check=True)
    python = str(env_python)
    subprocess.run([python, '-m', 'pip', 'install', '--upgrade', 'pyinstaller>=6,<7'], check=True)
    # Publicar solo una compilación terminada; ante fallos conservar el EXE anterior.
    with tempfile.TemporaryDirectory(prefix='dist_', dir=ROOT) as staging:
        subprocess.run([python, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                        '--windowed', '--uac-admin', '--name', 'PULSIA_Cliente_Licencias',
                        '--distpath', staging, str(ROOT / 'cliente.py')], check=True)
        output = ROOT / 'salida'
        output.mkdir(exist_ok=True)
        temp_exe = output / 'cliente_nuevo.tmp'
        shutil.copy2(Path(staging) / 'PULSIA_Cliente_Licencias.exe', temp_exe)
        temp_exe.replace(output / 'PULSIA_Cliente_Licencias.exe')
        if not (output / 'config.json').exists():
            shutil.copy2(ROOT / 'config.example.json', output / 'config.json')
    print('LISTO: EXE generado en app_usb/salida. Use Preparar pendrive en el servidor.')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('ERROR de compilacion:', e)
        sys.exit(1)
