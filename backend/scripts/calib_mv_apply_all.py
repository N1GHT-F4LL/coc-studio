"""Apply ALL enabled villages sequentially — one real SCID switch each.

For each enabled village (in list order): POST /api/multi_village/apply/{idx}
with the default farming config -> the backend drives the full switch flow
(mapping derive -> SCID page -> locate the account by name -> tap -> wait
home -> identity check -> snapshot home_v{idx}.png) and marks it confirmed.

Run:  ../.venv/Scripts/python.exe -X utf8 scripts/calib_mv_apply_all.py
Prereq: backend running, game on home, NO active run.
"""
import json
import sys
import time
import urllib.request

BASE = 'http://127.0.0.1:8000'


def api(path, method='GET', body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def main():
    st, state = api('/api/multi_village')
    if st != 200:
        sys.exit(f'backend not reachable ({st})')
    villages = [v for v in state['config']['villages'] if v.get('enabled')]
    print(f'{len(villages)} enabled village(s) to Apply:')
    for v in villages:
        print(f"  v{v['idx']}: {v['name']}")
    print()

    default_cfg = {'scenario': 'dragon_balloon',
                   'farm': {'min_gold': 100000, 'min_elixir': 100000,
                            'min_dark_elixir': 500}}
    results = []
    for v in villages:
        idx = v['idx']
        name = v['name']
        print(f'=== Apply village {idx} ({name}) — switch + snapshot + confirm ===',
              flush=True)
        st, resp = api(f'/api/multi_village/apply/{idx}', 'POST',
                       {'config': default_cfg})
        ok = st == 200 and resp.get('ok')
        results.append((idx, name, ok, resp.get('detail', '')))
        print(f'  -> {"CONFIRMED" if ok else "FAILED: " + str(resp.get("detail", ""))}',
              flush=True)
        time.sleep(2.0)

    print('\n===== RESULT =====')
    for idx, name, ok, detail in results:
        print(f'  v{idx} {name}: {"OK" if ok else "FAIL " + detail}')
    ok_n = sum(1 for r in results if r[2])
    print(f'{ok_n}/{len(results)} applied')
    print('=====')


if __name__ == '__main__':
    main()
