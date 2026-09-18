"""Multilogin X batch provisioning. No credentials are written to the journal."""
import argparse
import csv
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import urllib.error
import urllib.request

API = 'https://api.multilogin.com'
FLAGS = dict(audio_masking='natural', fonts_masking='natural',
    geolocation_masking='mask', geolocation_popup='prompt',
    graphics_masking='natural', graphics_noise='natural',
    localization_masking='mask', media_devices_masking='natural',
    navigator_masking='mask', ports_masking='mask', proxy_masking='custom',
    screen_masking='natural', timezone_masking='mask', webrtc_masking='mask',
    canvas_noise='natural', startup_behavior='recover')

class FactoryError(Exception):
    pass

def load_rows(path, offset=0, count=50):
    if offset < 0 or not 1 <= count <= 50:
        raise FactoryError('Offset must be nonnegative; batch size must be 1–50.')
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not {'Email', 'Password', 'Proxy', 'CODE', 'PhoneNumber'} <= set(reader.fieldnames or []):
            raise FactoryError('CSV needs Email, Password, Proxy, CODE, PhoneNumber columns.')
        rows = list(reader)[offset:offset+count]
    if not rows:
        raise FactoryError('No rows in requested range.')
    seen = set()
    for number, row in enumerate(rows, offset+2):
        if None in row or any(v is None for v in row.values()):
            raise FactoryError(f'CSV row {number}: inconsistent columns.')
        row['Email'] = row['Email'].strip()
        email = row['Email'].lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or email in seen:
            raise FactoryError(f'CSV row {number}: invalid or duplicate email.')
        seen.add(email)
        proxy(row['Proxy'])
        if len(notes(row)) > 400:
            raise FactoryError(f'CSV row {number}: notes exceed documented API limit (400).')
    return rows

def proxy(value):
    fields = value.strip().split(':', 3)
    if len(fields) != 4 or not all(fields) or not fields[1].isdigit() or not 1 <= int(fields[1]) <= 65535:
        raise FactoryError('Invalid proxy format; expected host:port:username:password.')
    return dict(host=fields[0], port=int(fields[1]), username=fields[2],
                password=fields[3], type='http', save_traffic=False)

def notes(row):
    return '\n'.join(f'{k}: {v}' for k, v in row.items() if k not in ('Email', 'Proxy'))

def payload(row, folder):
    return dict(name=row['Email'], browser_type='mimic', os_type='windows',
        folder_id=folder, times=1, notes=notes(row), parameters=dict(
            flags=FLAGS.copy(), storage={'is_local': False}, fingerprint={},
            proxy=proxy(row['Proxy'])))

def signature(row, folder):
    return hashlib.sha256(json.dumps(payload(row, folder), sort_keys=True).encode()).hexdigest()

class Client:
    def __init__(self, token):
        self.token = token

    def call(self, path, body=None):
        request = urllib.request.Request(API + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Bearer '+self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as e:
            # Never expose response bodies, which may contain submitted credentials.
            raise FactoryError(f'API HTTP {e.code} at {path}; stopped, no automatic write retry.') from None
        except (OSError, ValueError):
            raise FactoryError(f'API result unavailable at {path}; a write may have succeeded. Reconcile before retry.') from None
        status = result.get('status', {})
        if status.get('error_code') or status.get('http_code', 200) >= 400:
            raise FactoryError(f'API rejected {path}; stopped without retry.')
        return result['data']

    def profiles(self):
        out = []
        for offset in range(0, 10001, 100):
            data = self.call('/profile/search', dict(is_removed=False, limit=100,
                offset=offset, search_text='', storage_type='all', order_by='created_at', sort='asc'))
            page = data['profiles']
            out.extend(page)
            if len(out) >= data['total_count']:
                return out
            if not page:
                break
        raise FactoryError('Could not exhaust profile list; stopped to prevent duplicates.')

def run(rows, folder_name, client, db):
    folders = client.call('/workspace/folders')['folders']
    matches = [f for f in folders if f['name'] == folder_name]
    if len(matches) > 1:
        raise FactoryError('Multiple folders match; resolve the folder name first.')
    existing = client.profiles()
    # Avoid creating a folder if this batch contains names in other folders.
    folder_id = matches[0]['folder_id'] if matches else None
    by_name = {}
    for p in existing:
        by_name.setdefault(p['name'].lower(), []).append(p)
    for row in rows:
        found = by_name.get(row['Email'].lower(), [])
        if found and (len(found) != 1 or found[0]['folder_id'] != folder_id):
            raise FactoryError('A requested email already exists outside this batch, or has duplicate profiles. No writes made.')
    if folder_id is None:
        folder_id = client.call('/workspace/folder_create',
            {'name': folder_name, 'comment': 'CSV profile batch; exact email/proxy pairing.'})['id']
    completed = 0
    for row in rows:
        key = row['Email'].lower()
        sig = signature(row, folder_id)
        saved = db.execute('SELECT signature, profile_id, status FROM jobs WHERE folder=? AND email=?',
                           (folder_id, key)).fetchone()
        found = by_name.get(key, [])
        if saved and saved[0] != sig:
            raise FactoryError('Input changed for a journaled row; refusing to overwrite or duplicate.')
        if found:
            if saved and saved[1] == found[0]['id'] and saved[2] == 'created':
                completed += 1
                continue
            raise FactoryError('Existing batch profile needs reconciliation; refusing to guess proxy/settings.')
        if saved:
            raise FactoryError('Journal contains a prior attempt missing from current results. Reconcile before retry.')
        stats = client.call('/workspace/statistics')
        available = stats['profiles_cloud_limit'] - stats['profiles_cloud_count']
        if available <= 0:
            print(f'Capacity reached. {completed}/{len(rows)} completed; remaining rows untouched.')
            return
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)', (folder_id, key, sig, None, 'creating'))
        db.commit()
        result = client.call('/profile/create', payload(row, folder_id))
        ids = result.get('ids', [])
        if len(ids) != 1:
            raise FactoryError('Unexpected create result; journal retained for reconciliation.')
        db.execute('UPDATE jobs SET profile_id=?, status=? WHERE folder=? AND email=?',
                   (ids[0], 'created', folder_id, key))
        db.commit()
        completed += 1
        print(f'Created {completed}/{len(rows)}')
    verified = {p['id'] for p in client.profiles() if p['folder_id'] == folder_id}
    expected = {r[0] for r in db.execute('SELECT profile_id FROM jobs WHERE folder=? AND status=?', (folder_id, 'created'))}
    if not expected <= verified:
        raise FactoryError('Final profile listing did not confirm all created IDs.')
    print(f'Confirmed {completed}/{len(rows)} profiles in {folder_name}. Cookie warming has not run.')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--count', type=int, default=50)
    ap.add_argument('--offset', type=int, default=0, help='Number of data rows to skip')
    ap.add_argument('--folder', default='ML Import 2026-09-18')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--state', default='state')
    args = ap.parse_args()
    rows = load_rows(args.csv, args.offset, args.count)
    print(f'Validated {len(rows)} rows; {len(set(r["Proxy"].strip() for r in rows))} unique proxy credentials.')
    print('Exact pairings retained. Extra columns mapped to notes. No secrets displayed.')
    if not args.apply:
        print('Dry run complete. Use --apply to create the batch.')
        return
    token = os.environ.get('MLX_TOKEN') or getpass.getpass('Multilogin automation token (hidden): ')
    if not token.strip():
        raise FactoryError('Token required.')
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    lock = state/'run.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise FactoryError('Another run or a stale run.lock exists. Check the previous process before removing the lock.')
    try:
        os.close(fd)
        with sqlite3.connect(state/'jobs.sqlite') as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (folder TEXT, email TEXT, signature TEXT, profile_id TEXT, status TEXT, PRIMARY KEY(folder,email))')
            run(rows, args.folder, Client(token.strip()), db)
    finally:
        lock.unlink()

if __name__ == '__main__':
    try:
        main()
    except (FactoryError, KeyError) as e:
        print(str(e) if isinstance(e, FactoryError) else 'Unexpected API schema; stopped safely.', file=sys.stderr)
        sys.exit(1)
