# Multilogin profile batch importer

Creates up to 50 Windows / Mimic / cloud profiles per invocation using Multilogin X's documented API. Preserves each CSV email/proxy pair and writes other columns to notes. Existing profiles are never deleted, moved, or overwritten. Repeated proxies are permitted intentionally.

## Current status

The folder `ML Import 2026-09-18` was created through the Multilogin web UI. The account displayed 423/500 profiles used. No profile creation or cookie warming has been verified. The web UI requires a connected desktop agent for the requested configuration. This importer has local tests and a dry-run path; live API execution requires an automation token and remains unverified.

## Run on Windows (Python 3.10+)

Keep the original `ML list.csv` outside this public repository. Open a terminal in the downloaded code folder:

```powershell
py factory.py "C:\path\ML list.csv"
py factory.py "C:\path\ML list.csv" --apply
```

The second command prompts for an existing Multilogin automation token, without displaying or saving it. Alternatively supply `MLX_TOKEN` in the process environment. Do not paste tokens into chat or commit them. The CSV columns must include Email, Password, Proxy, CODE, PhoneNumber. Proxy syntax: host:port:username:password. Passwords containing colons are preserved.

Default: first 50 data rows, folder `ML Import 2026-09-18`. Later batches use `--offset 50 --count 50 --folder "ML Import batch 2"`. Capacity is rechecked before each creation. A full account stops the batch without cleanup or deletion.

The local SQLite journal prevents retries from silently duplicating successful or uncertain writes. Keep it between runs. Unexpected results and pre-existing names stop the run for reconciliation. Do not delete state to force a retry. API write timeouts are never automatically retried. This is deliberately conservative because creation can succeed before a response is lost.

## Profile settings

Restore startup, Windows, Mimic, cloud storage, custom HTTP proxy, traffic saver off. WebRTC/timezone/geolocation data/languages/navigator/port protection masked; geolocation permission prompt. Screen/fonts/media/WebGL metadata/WebGL graphics/canvas/audio real. No fixed IP, timezone, language, user-agent or hardware values copied from screenshots. Notes are limited to the API's documented 400 characters and never silently truncated.

## Cookie warming

`warm.py` implements ordinary visits to google.com, youtube.com, facebook.com, instagram.com, twitter.com, amazon.com, reddit.com, bbc.co.uk, linkedin.com, wikipedia.org. It runs three profiles concurrently, defaulting to six minutes of dwell time per profile plus navigation/launcher overhead. It validates each proxy through the launcher first, uses only journal-owned profiles, stops on access denials/challenges, closes profiles in cleanup, and records outcomes without cookie values. Existing login-required pages are simply visited; the worker does not log in, bypass challenges, or promise cookies on every domain. No claim of account trust, human activity, or detection avoidance is made.

On the Windows Multilogin computer, after provisioning:

```powershell
py -m pip install playwright
py warm.py "C:\path\ML list.csv"
```

No Playwright browser download is needed: the worker attaches to Multilogin's Mimic browser. Keep the launcher running and the computer awake. Warming is implemented but has not been tested against a live Windows launcher. Completed runs are skipped; interrupted runs are marked for review rather than silently repeated. Duration is not evidence that a profile is trusted by any website.

## Verify locally

```powershell
py -m unittest -v
```

API reference: https://documenter.getpostman.com/view/28533318/2s946h9Cv9 (vendor-linked documentation checked 2026-09-18). Creation uses `/profile/create`; capacity `/workspace/statistics`; folder discovery `/workspace/folders`; reconciliation `/profile/search`.
