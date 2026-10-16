"""Build the field-verified, headless-only Linke -> Laike navigation flow.

No save, publish, price or inventory mutations. Tokens remain in the browser.
"""
def possession_script(target, urls):
    name = target.get('name')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('PC 附身需要明确商家名称。')
    config = {'name': name, 'group': urls['groupid'], 'root': urls['root_life_account_id']}
    return 'PC_TARGET = ' + repr(config) + '\n' + r'''
import json, time
from urllib.parse import urlparse, parse_qs
def navigation_js(code):
    # Only inspect/focus navigation code uses this retry, never business writes.
    for attempt in range(8):
        try:
            return js(code)
        except Exception as exc:
            if 'Inspected target navigated or closed' not in str(exc) or attempt == 7:
                raise
            time.sleep(.5)
linke_tab = new_tab('https://www.life-partner.cn/vmok/op-merchant/merchant-list')
# Only the project headless Chrome: virtualized merchant rows need visibility.
activate_tab(linke_tab)
wait_for_load()
for _ in range(20):
    host = navigation_js('location.hostname')
    if host == 'sso.oceanengine.com' or '/login' in navigation_js('location.pathname'):
        raise RuntimeError('PC 登录已失效，请更新项目专用浏览器登录态。')
    rect = json.loads(navigation_js("""JSON.stringify((()=>{
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
navigation_js("document.querySelectorAll('[id^=venus_]').forEach(x=>x.remove())")
click_at_xy(rect['x'], rect['y'])
navigation_js("const e=document.querySelector('input[placeholder*=\"商家ID\"]');e.focus();e.select();")
type_text(PC_TARGET['name'])
if navigation_js("document.querySelector('input[placeholder*=\"商家ID\"]').value") != PC_TARGET['name']:
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
    button = json.loads(navigation_js(finder))
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
'''
