"""Prepara un entorno local para arrancar el servidor gráfico en Windows."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    python = ROOT / '.venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.exists():
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], check=True)
    check = subprocess.run([str(python), '-c', 'import tkinter, cryptography'], capture_output=True)
    if check.returncode:
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    return subprocess.call([str(python), str(ROOT / 'servidor_gui.py')], cwd=ROOT)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print('No se pudo iniciar el servidor:', e)
        sys.exit(1)
