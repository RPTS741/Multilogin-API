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
from factory import FactoryError, load_rows, signature, proxy, notes, FLAGS, Client

SITES = ['google.com','youtube.com','facebook.com','instagram.com','twitter.com',
         'amazon.com','reddit.com','bbc.co.uk','linkedin.com','wikipedia.org']
LAUNCHER = 'https://launcher.mlx.yt:45001'

class WarmStageError(Exception):
    """Sanitized failure that is safe to show (never contains URLs or credentials)."""
    def __init__(self, stage, detail='failed'):
        self.stage = stage
        self.detail = detail
        super().__init__(f'{stage}: {detail}')

def validation_proxy(value):
    checked = proxy(value).copy()
    checked.pop('save_traffic', None)
    return checked

def repair_profile_proxy(token, row, profile_id):
    """Rewrite the exact CSV proxy using both supported profile API shapes."""
    settings = proxy(row['Proxy'])
    body = {
        'profile_id': profile_id,
        'name': row['Email'],
        'notes': notes(row),
        'proxy': settings.copy(),
        'parameters': {
            'flags': FLAGS.copy(),
            'storage': {'is_local': False},
            'fingerprint': {},
            'proxy': settings.copy(),
        },
    }
    try:
        Client(token).call('/profile/update', body)
    except FactoryError:
        raise WarmStageError('profile_proxy_update', 'API rejected proxy repair') from None

def safe_browser_error(exc):
    """Return a credential/URL-free browser failure category."""
    message = str(exc)
    match = re.search(r'net::(ERR_[A-Z0-9_]+)', message)
    if match:
        return match.group(1)
    if re.search(r'timeout', message, re.I):
        return 'TIMEOUT'
    if re.search(r'(page|context|browser).{0,30}closed', message, re.I):
        return 'BROWSER_CLOSED'
    return 'NAVIGATION_ERROR'

def local_call(token, path, body=None, stage='launcher'):
    req = urllib.request.Request(LAUNCHER+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
                 'Accept':'application/json','User-Agent':'Multilogin-API-Client/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r: result=json.load(r)
    except urllib.error.HTTPError as exc:
        code = None
        try:
            reply = json.loads(exc.read(16384))
            candidate = reply.get('status', {}).get('error_code')
            if isinstance(candidate, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', candidate):
                code = candidate
        except (ValueError, AttributeError):
            pass
        detail = f'HTTP {exc.code}' + (f' ({code})' if code else '')
        raise WarmStageError(stage, detail) from None
    except (OSError, ValueError):
        raise WarmStageError(stage, 'launcher unavailable or invalid response') from None
    status = result.get('status', {})
    error_code = status.get('error_code')
    if error_code or status.get('http_code',200)>=400:
        safe = error_code if isinstance(error_code, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', error_code) else 'rejected'
        raise WarmStageError(stage, safe)
    if 'data' not in result:
        raise WarmStageError(stage, 'missing response data')
    return result['data']

async def visit_profile(pw, token, folder, profile_id, proxy_value, seconds):
    # Profiles created by older importer releases may have persisted only one
    # of Multilogin's accepted proxy shapes. Rewrite both before validation.
    # The caller supplies the full row separately through proxy_value below.
    # Validate before starting; no direct-network fallback.
    # The launcher validation endpoint accepts only connection fields. The
    # create-profile endpoint additionally accepts save_traffic.
    await asyncio.to_thread(local_call, token, '/api/v1/proxy/validate',
                            validation_proxy(proxy_value), 'proxy_validation')
    attempted = False
    results=[]
    try:
        attempted=True
        info=await asyncio.to_thread(local_call,token,
            f'/api/v2/profile/f/{folder}/p/{profile_id}/start?automation_type=playwright&headless_mode=false',
            None, 'profile_start')
        port=str(info.get('port',''))
        if not port.isdigit() or not 1<=int(port)<=65535:
            raise WarmStageError('profile_start', 'invalid automation port')
        try:
            browser=await pw.chromium.connect_over_cdp('http://127.0.0.1:'+port,timeout=30000)
        except Exception:
            raise WarmStageError('browser_attach', 'could not attach to profile') from None
        if not browser.contexts:
            raise WarmStageError('browser_attach', 'no persistent context')
        context=browser.contexts[0]
        page=await context.new_page()
        page.set_default_timeout(15000)
        try:
            for site in SITES:
                try:
                    response=await page.goto('https://'+site,wait_until='domcontentloaded',timeout=45000)
                except Exception as exc:
                    raise WarmStageError('site_visit', f'{site}: {safe_browser_error(exc)}') from None
                try:
                    text=(await page.locator('body').inner_text())[:30000].lower()
                except Exception:
                    raise WarmStageError('site_visit', f'{site}: BODY_UNAVAILABLE') from None
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
            try:
                await asyncio.to_thread(local_call,token,f'/api/v1/profile/stop/p/{profile_id}',None,'profile_stop')
            except WarmStageError:
                # Preserve the primary error. The next remote-state check will
                # refuse to proceed if the profile remains in use.
                pass

async def execute(args, rows, token, db):
    from playwright.async_api import async_playwright
    await asyncio.to_thread(local_call,token,'/api/v1/version',None,'launcher_version')
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
            if not args.retry_needs_review:
                raise FactoryError('Prior incomplete warming attempt needs review before retry.')
            db.execute('DELETE FROM warming WHERE profile_id=?',(job[1],))
        jobs.append((row,job[1]))
    db.commit()
    gate=asyncio.Semaphore(3)
    async with async_playwright() as pw:
        async def worker(row,pid):
            async with gate:
                db.execute('INSERT INTO warming VALUES (?,?,?)',(pid,'running','[]')); db.commit()
                try:
                    await asyncio.to_thread(repair_profile_proxy, token, row, pid)
                    result=await visit_profile(pw,token,folder,pid,row['Proxy'],args.seconds)
                    status='completed' if len(result)==len(SITES) and all(x['status']=='visited' for x in result) else 'needs_review'
                except WarmStageError as exc:
                    status='needs_review'; result=[{'status':'stage_error','stage':exc.stage,'detail':exc.detail}]
                except Exception:
                    # Browser errors may embed URLs or credentials. Do not print them.
                    status='needs_review'; result=[{'status':'unexpected_error'}]
                db.execute('UPDATE warming SET status=?,report=? WHERE profile_id=?',(status,json.dumps(result),pid)); db.commit()
                suffix = ''
                if status != 'completed' and result and result[-1].get('stage'):
                    suffix = f" ({result[-1]['stage']}: {result[-1]['detail']})"
                print(f'Profile {pid}: {status}{suffix}',flush=True)
                return status
        if not jobs:
            print('All requested profiles are already warmed.')
            return
        # A dead or expired proxy belongs to one profile and must not block the
        # rest of the batch. Each worker still stops its own profile safely and
        # records a sanitized failure for review.
        print(f'Warming {len(jobs)} profiles (3 at a time). Failed proxies will be isolated.',flush=True)
        statuses = await asyncio.gather(*(worker(row,pid) for row,pid in jobs))
        completed = sum(status == 'completed' for status in statuses)
        needs_review = len(statuses) - completed
        print(f'Warming chunk finished: {completed} completed; {needs_review} need proxy review.',flush=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('csv'); ap.add_argument('--count',type=int,default=50)
    ap.add_argument('--offset',type=int,default=0)
    ap.add_argument('--folder',default='ML Import 2026-09-18')
    ap.add_argument('--state',default='state')
    ap.add_argument('--seconds',type=int,default=360)
    ap.add_argument('--retry-needs-review',action='store_true')
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
