"""Interactive Windows entry point; token stays in process memory."""
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

CLIENT_HEADERS={'Content-Type':'application/json','Accept':'application/json',
                'User-Agent':'Multilogin-API-Client/1.0'}

def login_token():
    print('Sign in locally to obtain a 24-hour automation token. Credentials are not saved.')
    email=input('Multilogin account email: ').strip()
    password=getpass.getpass('Multilogin account password (hidden): ')
    if not email or not password:
        raise SystemExit('Email and password required. Nothing created.')
    payload=json.dumps({'email':email,'password':hashlib.md5(password.encode()).hexdigest()}).encode()
    del password
    def request(path, data=None, bearer=None):
        stage='Sign-in' if path=='/user/signin' else 'Automation token creation'
        headers=CLIENT_HEADERS.copy()
        if bearer: headers['Authorization']='Bearer '+bearer
        req=urllib.request.Request('https://api.multilogin.com'+path,data=data,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=45) as response:
                result=json.load(response)
            token=result.get('data',{}).get('token')
            if not isinstance(token,str) or not token:
                raise SystemExit('Authentication did not return a token. Nothing created; send this message, not your credentials.')
            return token
        except urllib.error.HTTPError as exc:
            detail='No structured error code returned'
            try:
                body=json.loads(exc.read(16384))
                code=body.get('status',{}).get('error_code')
                if isinstance(code,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',code):
                    detail='API error code: '+code
            except (ValueError,AttributeError):
                pass
            raise SystemExit('%s failed (HTTP %s). %s. Nothing created.' % (stage,exc.code,detail)) from None
        except (urllib.error.URLError,TimeoutError,ValueError):
            raise SystemExit('Could not complete Multilogin authentication. Nothing created.') from None
    bearer=request('/user/signin',payload)
    return request('/workspace/automation_token?expiration_period=24h',bearer=bearer)

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
    print('Press Enter to sign in, or paste an existing automation token.')
    token=getpass.getpass('Automation token (optional, hidden): ').strip()
    if not token: token=login_token()
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
