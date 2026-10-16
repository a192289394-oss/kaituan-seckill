# Executed after pc_browser_flow.possession_script inside the headless browser.
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode

os.umask(0o077)
ACCOUNT = 'qian314888'
OUT = Path('/Users/zhongjiawei/Documents/Codex/2026-09-18/uiautomator2/work/pc-acceptance/qian314888') / PC_TARGET['root']
OUT.mkdir(parents=True, exist_ok=True)
query = urlencode({'groupid': PC_TARGET['group'], 'root_life_account_id': PC_TARGET['root'], 'life_biz_view_id': '22'})
goto_url('https://life.douyin.com/p/merchant-marketing-tools/live-seckill/list?' + query)
activate_tab(current_tab())
wait_for_load()
time.sleep(6)


def read_json(path, params, body=None):
    url = 'https://life.douyin.com' + path + '?' + urlencode(params)
    options = {'credentials': 'include'}
    if body is not None:
        options.update(method='POST', headers={'Content-Type': 'application/json'}, body=json.dumps(body))
    # Returning raw text preserves 19-digit identifiers for Python JSON decoding.
    raw = js('(async()=>{const r=await fetch(' + json.dumps(url) + ',' + json.dumps(options) + ');if(!r.ok)throw Error("read_http_"+r.status);return await r.text()})()')
    data = json.loads(raw)
    if int(data.get('status_code', -1)) != 0:
        raise RuntimeError('read_api_failed_' + str(data.get('status_code')))
    return data


active = []
seen = set()
complete = False
now = time.time()
for page in range(1, 31):
    data = read_json('/life/marketing/v1/minus_activity/list', {'root_life_account_id': PC_TARGET['root']},
                     {'discount_type': 'merchant_live_flash_promotion', 'selected_account_id': '',
                      'pagination': {'current_page': page, 'page_size': 100}})
    for activity in data.get('activities', []):
        aid = str(activity['activity_id'])
        if aid in seen:
            raise RuntimeError('repeated_activity_page')
        seen.add(aid)
        if int(activity['activity_status']) == 2 and int(activity['start_time']) <= now < int(activity['end_time']):
            active.append(activity)
    if not data.get('pagination', {}).get('has_more'):
        complete = True
        break
if not complete:
    raise RuntimeError('activity_list_incomplete')
details = []
for activity in active:
    aid = str(activity['activity_id'])
    data = read_json('/life/marketing/v1/minus_activity/info',
                     {'activity_id': aid, 'selected_account_id': '', 'discount_type': 'merchant_live_flash_promotion',
                      'root_life_account_id': PC_TARGET['root']})
    detail = data['activity']
    if str(detail['activity_id']) != aid:
        raise RuntimeError('activity_identity_mismatch')
    details.append(detail)

lookup = None
matches = [x for a in details for x in a.get('anchor_info_list', []) if str(x.get('douyin_id')) == ACCOUNT]
if matches:
    if len({str(x['uid']) for x in matches}) != 1:
        raise RuntimeError('creator_identity_conflict')
    lookup = matches[0]

payload = {'target': PC_TARGET, 'account': ACCOUNT, 'total_read': len(seen), 'complete': complete,
           'active': details, 'lookup': lookup, 'observed_at': time.time()}
(OUT / 'read.json').write_text(json.dumps(payload, ensure_ascii=False))
(OUT / 'read.json').chmod(0o600)
print('AUTHORIZATION_SCAN=' + json.dumps({'hotel': PC_TARGET['name'], 'complete': complete, 'total': len(seen),
    'account_resolved': lookup is not None, 'nickname': lookup.get('nick_name') if lookup else None,
    'active': [{'id': str(a['activity_id']), 'name': a['activity_name'], 'end': str(a['end_time']),
                'products': len(a.get('sku_list', [])), 'anchors': len(a.get('anchor_info_list', [])),
                'account_present': any(str(x.get('douyin_id')) == ACCOUNT for x in a.get('anchor_info_list', []))}
               for a in details]}, ensure_ascii=False))
