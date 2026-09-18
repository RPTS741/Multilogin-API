"""Interactive Windows entry point; token stays in process memory."""
import getpass
import os
from pathlib import Path
import subprocess
import sys

def main():
    if sys.platform != 'win32':
        raise SystemExit('Run this starter on your Windows Multilogin computer.')
    import tkinter as tk
    from tkinter.filedialog import askopenfilename
    root=tk.Tk(); root.withdraw()
    source=askopenfilename(title='Select the email/proxy CSV',filetypes=[('CSV files','*.csv')])
    root.destroy()
    if not source: return
    os.chdir(Path(__file__).resolve().parent)
    subprocess.run([sys.executable,'factory.py',source],check=True)
    token=getpass.getpass('Paste your Multilogin automation token (hidden): ').strip()
    if not token: raise SystemExit('No token entered. Nothing created.')
    env=os.environ.copy(); env['MLX_TOKEN']=token
    try:
        subprocess.run([sys.executable,'-m','pip','install','playwright'],check=True)
        subprocess.run([sys.executable,'factory.py',source,'--apply'],env=env,check=True)
        subprocess.run([sys.executable,'warm.py',source],env=env,check=True)
    finally:
        env.pop('MLX_TOKEN',None)

if __name__=='__main__':
    try: main()
    except subprocess.CalledProcessError:
        print('A stage stopped. Review the message above; do not delete the state folder.')
        sys.exit(1)
