# Independent second read in the existing headless session; no business writes.
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse, parse_qs, urlencode

ROOT = Path('/Users/zhongjiawei/Documents/Codex/2026-09-18/uiautomator2')
sys.path.insert(0, str(ROOT / 'outputs'))
from pc_authorization import parse_activity_response, verify_existing_authorizations

for root in ['7372762113233651738', '7615891641152636938']:
    directory = ROOT / 'work/pc-acceptance/qian314888' / root
    first = json.loads((directory / 'read.json').read_text())
    target = first['target']
    sources = [a for a in first['active'] if any(x.get('douyin_id') == 'qian314888' for x in a.get('anchor_info_list', []))]
    assert len(sources) == 1
    source = sources[0]
    tabs = [t for t in list_tabs() if parse_qs(urlparse(t.get('url', '')).query).get('root_life_account_id') == [root]]
    assert len(tabs) == 1
    switch_tab(tabs[0])
    activate_tab(tabs[0])
    goto_url('https://life.douyin.com/p/merchant-marketing-tools/live-seckill/list?' + urlencode({
        'groupid': target['group'], 'root_life_account_id': root, 'life_biz_view_id': '22'}))
    wait_for_load()
    time.sleep(3)
    route = parse_qs(urlparse(js('location.href')).query)
    assert route.get('root_life_account_id') == [root] and route.get('groupid') == [target['group']]
    aid = str(source['activity_id'])
    url = '/life/marketing/v1/minus_activity/info?' + urlencode({'activity_id': aid, 'selected_account_id': '',
        'discount_type': 'merchant_live_flash_promotion', 'root_life_account_id': root})
    raw = js('(async()=>{const r=await fetch(' + json.dumps(url) + ',{credentials:"include",cache:"no-store"});if(!r.ok)throw Error("detail_read_failed");return await r.text()})()')
    fresh = parse_activity_response(raw, aid)
    result = verify_existing_authorizations(source, [fresh], ['qian314888'], time.time())
    assert result['status'] == 'already_authorized'
    document = {'target': target, 'account': 'qian314888', 'activity': fresh, 'verification': result,
                'observed_at': time.time(), 'submitted': False}
    out = directory / 'verified-twice.json'
    out.write_text(json.dumps(document, ensure_ascii=False))
    out.chmod(0o600)
    print('INDEPENDENT_RECHECK=' + json.dumps({'hotel': target['name'], 'status': result['status'],
        'products': len(result['coverage']['qian314888']), 'submitted': False}, ensure_ascii=False))
