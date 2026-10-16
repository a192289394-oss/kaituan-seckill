PC_TARGET = {'name': '依力酒店(广州番禺市桥地铁站店)', 'group': '1859348750932873', 'root': '7615891641152636938'}

import json, time
from urllib.parse import urlparse, parse_qs
linke_tab = new_tab('https://www.life-partner.cn/vmok/op-merchant/merchant-list')
# Only the project headless Chrome: virtualized merchant rows need visibility.
activate_tab(linke_tab)
wait_for_load()
for _ in range(20):
    host = js('location.hostname')
    if host == 'sso.oceanengine.com' or '/login' in js('location.pathname'):
        raise RuntimeError('PC 登录已失效，请更新项目专用浏览器登录态。')
    rect = json.loads(js("""JSON.stringify((()=>{
      const e=document.querySelector('input[placeholder*="商家ID"]');
      if(!e)return null;
      const r=e.getBoundingClientRect();
      return {x:r.x+r.width/2,y:r.y+r.height/2};
    })())"""))
    if rect:
        break
    time.sleep(1)
else:
    raise RuntimeError('林客商家搜索入口未加载。')
js("document.querySelectorAll('[id^=venus_]').forEach(x=>x.remove())")
click_at_xy(rect['x'], rect['y'])
js("const e=document.querySelector('input[placeholder*=\"商家ID\"]');e.focus();e.select();")
type_text(PC_TARGET['name'])
if js("document.querySelector('input[placeholder*=\"商家ID\"]').value") != PC_TARGET['name']:
    raise RuntimeError('商家搜索词未正确写入，请重试。')
press_key('Enter')
for _ in range(20):
    finder = """JSON.stringify((()=>{
      const name=__NAME__;
      document.querySelectorAll('[id^=venus_]').forEach(x=>x.remove());
      const rows=[...document.querySelectorAll('tr,[role=row]')].filter(x=>x.innerText.includes(name));
      if(rows.length!==1)return null;
      const buttons=[...rows[0].querySelectorAll('a,button')].filter(x=>x.innerText.trim()==='附身来客后台');
      if(buttons.length!==1)return null;
      buttons[0].scrollIntoView({block:'center',inline:'center'});
      const r=buttons[0].getBoundingClientRect();
      const x=r.x+r.width/2,y=r.y+r.height/2;
      if(!buttons[0].contains(document.elementFromPoint(x,y)))return null;
      return {x,y};
    })())""".replace('__NAME__', json.dumps(PC_TARGET['name']))
    button = json.loads(js(finder))
    if button:
        break
    time.sleep(1)
else:
    raise RuntimeError('未找到唯一商家及来客附身入口，请核对酒店名称或权限。')
before_ids = {t['targetId'] for t in list_tabs()}
click_at_xy(button['x'], button['y'])
for _ in range(30):
    candidates = []
    for tab in list_tabs():
        if tab['targetId'] in before_ids:
            continue
        page = urlparse(tab.get('url', ''))
        query = parse_qs(page.query)
        if (page.hostname == 'life.douyin.com'
                and query.get('groupid') == [PC_TARGET['group']]
                and query.get('root_life_account_id') == [PC_TARGET['root']]):
            candidates.append(tab)
    if len(candidates) == 1:
        switch_tab(candidates[0])
        activate_tab(candidates[0])
        wait_for_load()
        break
    time.sleep(1)
else:
    raise RuntimeError('附身未返回与目标商家一致的新来客页面。')

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
