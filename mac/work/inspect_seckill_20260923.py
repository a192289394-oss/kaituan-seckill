# Read-only PC inspection inside the project headless browser; no publish action.
import json
import time
from urllib.parse import urlparse

tab = new_tab('https://www.life-partner.cn/vmok/op-merchant/merchant-list')
# Only this headless browser: virtualized rows need a visible document.
activate_tab(tab)
wait_for_load()
time.sleep(8)
js("document.querySelectorAll('[id^=venus_]').forEach(x=>x.remove())")
rect = json.loads(js('''JSON.stringify((()=>{
 const e=document.querySelector('input[placeholder*="商家ID"]');
 if(!e)return null;
 const r=e.getBoundingClientRect();
 return {x:r.x+r.width/2,y:r.y+r.height/2};
})())'''))
if not rect:
    raise RuntimeError('search_missing')
click_at_xy(rect['x'], rect['y'])
type_text('深圳浪骑瞻云度假酒店')
press_key('Enter')
time.sleep(6)
button = json.loads(js('''JSON.stringify((()=>{
 const rows=[...document.querySelectorAll('tr,[role=row]')].filter(x=>x.innerText.includes('深圳浪骑瞻云度假酒店'));
 if(rows.length!==1)return null;
 const buttons=[...rows[0].querySelectorAll('a,button')].filter(x=>x.innerText.trim()==='附身来客后台');
 if(buttons.length!==1)return null;
 buttons[0].scrollIntoView({block:'center',inline:'center'});
 const r=buttons[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
})())'''))
if not button:
    raise RuntimeError('possession_button_not_unique')
click_at_xy(button['x'], button['y'])
expected_group = '1813245080589312'
expected_root = '7427049746126194727'
from urllib.parse import parse_qs
for _ in range(25):
    candidates = []
    for t in list_tabs():
        u = urlparse(t.get('url', ''))
        q = parse_qs(u.query)
        if u.hostname == 'life.douyin.com' and q.get('groupid') == [expected_group] and q.get('root_life_account_id') == [expected_root]:
            candidates.append(t)
    if len(candidates) == 1:
        break
    time.sleep(1)
else:
    print('ROUTES='+json.dumps([{'host':urlparse(t.get('url','')).hostname,'path':urlparse(t.get('url','')).path,'group':parse_qs(urlparse(t.get('url','')).query).get('groupid'),'root':parse_qs(urlparse(t.get('url','')).query).get('root_life_account_id')} for t in list_tabs()]))
    raise RuntimeError('possession_identity_not_verified')
switch_tab(candidates[0])
activate_tab(candidates[0])
wait_for_load()
goto_url('https://life.douyin.com/p/merchant-marketing-tools/live-seckill/list?groupid='+expected_group+'&root_life_account_id='+expected_root+'&life_biz_view_id=22')
wait_for_load()
time.sleep(12)
print('SECKILL=' + js('''JSON.stringify({path:location.pathname,activityCount:(document.body.innerText.match(/活动数量：\\d+/)||[])[0]})'''))
edit_button = json.loads(js('''JSON.stringify((()=>{
 const rows=[...document.querySelectorAll('tr,[role=row]')].filter(x=>x.innerText.includes('7661926099886917684'));
 if(rows.length!==1)return null;
 const buttons=[...rows[0].querySelectorAll('a,button')].filter(x=>x.innerText.trim()==='编辑');
 if(buttons.length!==1)return null;
 buttons[0].scrollIntoView({block:'center',inline:'center'});
 const r=buttons[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
})())'''))
if not edit_button:
    raise RuntimeError('activity_edit_entry_not_unique')
click_at_xy(edit_button['x'], edit_button['y'])
time.sleep(8)
print('EDIT_FORM=' + js('''JSON.stringify({path:location.pathname,capacity:(document.body.innerText.match(/已授权：36\\/39/)||[])[0]})'''))
batch = json.loads(js('''JSON.stringify((()=>{
 const buttons=[...document.querySelectorAll('button')].filter(b=>{
  if(b.innerText.trim()!=='批量录入主播抖音号')return false;
  for(let p=b.parentElement;p&&p!==document.body;p=p.parentElement){
   if(p.innerText.includes('选择主播 (36/39)'))return !p.innerText.includes('选择主播 (1/4)');
  }
  return false;
 });
 if(buttons.length!==1)return null;
 buttons[0].scrollIntoView({block:'center',inline:'center'});
 const r=buttons[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
})())'''))
if not batch:
    raise RuntimeError('creator_batch_entry_not_unique')
click_at_xy(batch['x'], batch['y'])
time.sleep(2)
print('BATCH_FORM=' + js('''JSON.stringify({text:document.body.innerText.slice(-1600),textareas:[...document.querySelectorAll('textarea')].map(x=>({placeholder:x.placeholder,visible:!!(x.offsetWidth||x.offsetHeight)}))})'''))
