"""Interactive Windows entry point; credentials and tokens stay in process memory."""
import getpass
import os
from pathlib import Path
import subprocess
import sys
import hashlib
import json
import urllib.request
import urllib.error
import re
import ctypes
import time

CLIENT_HEADERS={'Content-Type':'application/json','Accept':'application/json',
                'User-Agent':'Multilogin-API-Client/1.0'}

def sign_in(email, password):
    """Return a short-lived sign-in token without persisting credentials."""
    payload=json.dumps({'email':email,'password':hashlib.md5(password.encode()).hexdigest()}).encode()
    headers=CLIENT_HEADERS.copy()
    for attempt in range(8):
        req=urllib.request.Request('https://api.multilogin.com/user/signin',data=payload,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=45) as response:
                result=json.load(response)
            token=result.get('data',{}).get('token')
            if not isinstance(token,str) or not token:
                raise SystemExit('Authentication did not return a token. Nothing was changed.')
            return token
        except urllib.error.HTTPError as exc:
            if 500 <= exc.code < 600 and attempt < 7:
                print(f'Multilogin sign-in service returned HTTP {exc.code}; retrying automatically.',flush=True)
                time.sleep(min(30, 2 ** (attempt + 1)))
                continue
            detail='No structured error code returned'
            try:
                body=json.loads(exc.read(16384))
                code=body.get('status',{}).get('error_code')
                if isinstance(code,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',code):
                    detail='API error code: '+code
            except (ValueError,AttributeError):
                pass
            raise SystemExit('Sign-in failed (HTTP %s). %s. Nothing was changed.' % (exc.code,detail)) from None
        except (urllib.error.URLError,TimeoutError,ValueError):
            if attempt < 7:
                print('Multilogin sign-in service unavailable; retrying automatically.',flush=True)
                time.sleep(min(30, 2 ** (attempt + 1)))
                continue
            raise SystemExit('Could not complete Multilogin authentication. Nothing was changed.') from None

def login_credentials():
    print('Sign in locally. Credentials stay in memory only and are not saved.')
    email=input('Multilogin account email: ').strip()
    password=getpass.getpass('Multilogin account password (hidden): ')
    if not email or not password:
        raise SystemExit('Email and password required. Nothing created.')
    # Prove the credentials now, before any child process is launched, and
    # reuse this token for the quick provisioning reconciliation.
    return email,password,sign_in(email,password)

def main():
    if sys.platform != 'win32':
        raise SystemExit('Run this starter on your Windows Multilogin computer.')
    # Keep Windows awake only while this process is active; the setting resets on exit.
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    try:
        import tkinter as tk
        from tkinter.filedialog import askopenfilename
        root=tk.Tk(); root.withdraw()
        source=askopenfilename(title='Select the email/proxy CSV',filetypes=[('CSV files','*.csv')])
        root.destroy()
        if not source: return
        os.chdir(Path(__file__).resolve().parent)
        subprocess.run([sys.executable,'factory.py',source],check=True)
        print('Press Enter to sign in, or paste an existing automation token.')
        token=getpass.getpass('Automation token (optional, hidden): ').strip()
        email=password=None
        if not token:
            email,password,token=login_credentials()
        env=os.environ.copy(); env['MLX_TOKEN']=token
        try:
            subprocess.run([sys.executable,'-m','pip','install','playwright'],check=True)
            subprocess.run([sys.executable,'factory.py',source,'--apply'],env=env,check=True)
            if email is None:
                subprocess.run([sys.executable,'warm.py',source,'--retry-needs-review'],env=env,check=True)
            else:
                # Sign-in tokens last about 30 minutes. Refresh before every
                # six-profile chunk; each chunk takes about 12 minutes at
                # three concurrent profiles. No credentials are written.
                print('Using automatically refreshed sign-in tokens for the overnight run.')
                for offset in range(0,50,6):
                    count=min(6,50-offset)
                    env['MLX_TOKEN']=sign_in(email,password)
                    print(f'Starting warming chunk {offset+1}-{offset+count} of 50.',flush=True)
                    subprocess.run([sys.executable,'warm.py',source,'--offset',str(offset),
                                    '--count',str(count),'--retry-needs-review'],env=env,check=True)
        finally:
            env.pop('MLX_TOKEN',None)
            password=None
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

if __name__=='__main__':
    try: main()
    except subprocess.CalledProcessError:
        print('A stage stopped. Review the message above; do not delete the state folder.')
        sys.exit(1)
