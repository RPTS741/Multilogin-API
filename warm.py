"""Ordinary page visits on the user's Windows Multilogin launcher.
Stops on challenges; does not log in, click ads, interact socially or bypass blocks.
"""
import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from factory import FactoryError, load_rows, signature, proxy, Client

SITES = ['google.com','youtube.com','facebook.com','instagram.com','twitter.com',
         'amazon.com','reddit.com','bbc.co.uk','linkedin.com','wikipedia.org']
LAUNCHER = 'https://launcher.mlx.yt:45001'

def local_call(token, path, body=None):
    req = urllib.request.Request(LAUNCHER+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r: result=json.load(r)
    except (OSError, ValueError):
        raise FactoryError('Launcher request failed; ensure Multilogin is running. No automatic retry.') from None
    if result.get('status',{}).get('error_code') or result.get('status',{}).get('http_code',200)>=400:
        raise FactoryError('Launcher rejected request.')
    return result['data']

async def visit_profile(pw, token, folder, profile_id, proxy_value, seconds):
    # Validate before starting; no direct-network fallback.
    await asyncio.to_thread(local_call, token, '/api/v1/proxy/validate', proxy(proxy_value))
    attempted = False
    results=[]
    try:
        attempted=True
        info=await asyncio.to_thread(local_call,token,
            f'/api/v2/profile/f/{folder}/p/{profile_id}/start?automation_type=playwright&headless_mode=false')
        port=str(info.get('port',''))
        if not port.isdigit() or not 1<=int(port)<=65535:
            raise FactoryError('Launcher returned an invalid automation port.')
        browser=await pw.chromium.connect_over_cdp('http://127.0.0.1:'+port,timeout=30000)
        if not browser.contexts:
            raise FactoryError('No persistent profile context returned.')
        context=browser.contexts[0]
        page=await context.new_page()
        page.set_default_timeout(15000)
        try:
            for site in SITES:
                response=await page.goto('https://'+site,wait_until='domcontentloaded',timeout=45000)
                text=(await page.locator('body').inner_text())[:30000].lower()
                if (response and response.status in (403,429)) or re.search(
                    r'verify (?:that )?you are human|unusual traffic|checking your browser|automated queries|complete the captcha',text):
                    results.append({'site':site,'status':'blocked'})
                    break
                if response and response.status >= 400:
                    results.append({'site':site,'status':'http_error'})
                    break
                await asyncio.sleep(seconds/len(SITES))
                # Counts only; cookie/session values are never exported.
                count=len(await context.cookies(['https://'+site]))
                results.append({'site':site,'status':'visited','cookie_count':count})
        finally:
            await page.close()
        return results
    finally:
        if attempted:
            # This worker only starts journal-owned profiles. Stop even if start response was lost.
            await asyncio.to_thread(local_call,token,f'/api/v1/profile/stop/p/{profile_id}')

async def execute(args, rows, token, db):
    from playwright.async_api import async_playwright
    await asyncio.to_thread(local_call,token,'/api/v1/version')
    client=Client(token)
    folders=client.call('/workspace/folders')['folders']
    matches=[f for f in folders if f['name']==args.folder]
    if len(matches)!=1: raise FactoryError('Expected one batch folder.')
    folder=matches[0]['folder_id']
    remote={p['id']:p for p in client.profiles()}
    jobs=[]
    for row in rows:
        job=db.execute('SELECT signature,profile_id,status FROM jobs WHERE folder=? AND email=?',
                       (folder,row['Email'].lower())).fetchone()
        if not job or job[2]!='created' or job[0]!=signature(row,folder):
            raise FactoryError('Batch is not fully provisioned with these inputs; run the importer first.')
        p=remote.get(job[1],{})
        if p.get('folder_id')!=folder or p.get('name','').lower()!=row['Email'].lower() or p.get('in_use_by'):
            raise FactoryError('Profile moved, changed, missing or in use; stop before warming.')
        old=db.execute('SELECT status FROM warming WHERE profile_id=?',(job[1],)).fetchone()
        if old:
            if old[0]=='completed': continue
            raise FactoryError('Prior incomplete warming attempt needs review before retry.')
        jobs.append((row,job[1]))
    gate=asyncio.Semaphore(3)
    async with async_playwright() as pw:
        async def worker(row,pid):
            async with gate:
                db.execute('INSERT INTO warming VALUES (?,?,?)',(pid,'running','[]')); db.commit()
                try:
                    result=await visit_profile(pw,token,folder,pid,row['Proxy'],args.seconds)
                    status='completed' if len(result)==len(SITES) and all(x['status']=='visited' for x in result) else 'needs_review'
                except Exception:
                    # Browser errors may embed URLs or credentials. Do not print them.
                    status='needs_review'; result=[{'status':'worker_or_launcher_error'}]
                db.execute('UPDATE warming SET status=?,report=? WHERE profile_id=?',(status,json.dumps(result),pid)); db.commit()
                print(f'Profile {pid}: {status}',flush=True)
        await asyncio.gather(*(worker(row,pid) for row,pid in jobs))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('csv'); ap.add_argument('--count',type=int,default=50)
    ap.add_argument('--offset',type=int,default=0)
    ap.add_argument('--folder',default='ML Import 2026-09-18')
    ap.add_argument('--state',default='state')
    ap.add_argument('--seconds',type=int,default=360)
    args=ap.parse_args()
    if not 300<=args.seconds<=480: raise FactoryError('Duration must be 300–480 seconds.')
    if sys.platform!='win32': raise FactoryError('Run warming on the intended Windows Multilogin machine.')
    rows=load_rows(args.csv,args.offset,args.count)
    state=Path(args.state)
    if not (state/'jobs.sqlite').exists(): raise FactoryError('Provisioning journal missing.')
    token=os.environ.get('MLX_TOKEN') or getpass.getpass('Multilogin automation token (hidden): ')
    lock=state/'run.lock'
    try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError: raise FactoryError('A run is active or has an unresolved lock.')
    try:
        os.close(fd)
        with sqlite3.connect(state/'jobs.sqlite') as db:
            db.execute('CREATE TABLE IF NOT EXISTS warming (profile_id TEXT PRIMARY KEY,status TEXT,report TEXT)')
            asyncio.run(execute(args,rows,token.strip(),db))
    finally: lock.unlink()

if __name__=='__main__':
    try: main()
    except FactoryError as e: print(str(e),file=sys.stderr); sys.exit(1)
