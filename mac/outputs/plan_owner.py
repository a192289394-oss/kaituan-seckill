"""Read-only plan ownership resolution. No hotel-text or historical-plan fallback."""
import fcntl
import json
import re


class ResolutionUnavailable(RuntimeError):
    pass


def select_target(products, rows):
    if not products:
        raise ResolutionUnavailable('计划未返回商品，暂时无法反查商家')
    if any(p.get('shop_num') != 1 or not str(p.get('shop_poi_id') or '').isdigit()
           or str(p.get('shop_poi_id')) == '0' for p in products):
        raise ResolutionUnavailable('计划商品包含多门店或缺少门店 ID，无法唯一确认商家')
    pois = {str(p['shop_poi_id']) for p in products}
    if len(pois) != 1:
        raise ResolutionUnavailable('计划商品涉及多个门店，无法唯一确认商家')
    poi = next(iter(pois))
    matched = [r for r in rows if str(r.get('poi_id')) == poi or
               any(str(s.get('poi_id')) == poi for s in r.get('related_store_ids', []))]
    roots = {str(r.get('root_id') or r.get('merchant_id') or '') for r in matched}
    if len(roots) != 1 or '' in roots:
        raise ResolutionUnavailable('反查门店尚未在商家目录中唯一定位，需核对目录和授权')
    root = next(iter(roots))
    parents = [r for r in rows if str(r.get('merchant_id')) == root
               and str(r.get('root_id') or root) == root]
    candidates = parents or matched
    # Multiple regional identities must not be collapsed merely because roots agree.
    if len(candidates) != 1:
        raise ResolutionUnavailable('反查门店存在多个商家入口，需核对账号关系')
    return candidates[0]


def verify_detail(plan_id, data, target, products):
    d = data.get('task_detail') or {}
    m = d.get('merchant_detail') or {}
    expected = str(target.get('root_id') or target.get('merchant_id'))
    if (data.get('status_code') != 0 or d.get('task_id') != plan_id
            or str(m.get('merchant_account_id') or '') != expected):
        raise ResolutionUnavailable('反查后的计划 ID 或商家详情未核验通过，未操作手机')
    ids = {p.get('product_id') for p in products}
    detail_ids = {p.get('product_id') for p in (d.get('data') or {}).get('product_list', [])}
    if not ids or None in ids or ids != detail_ids:
        raise ResolutionUnavailable('反查商品与计划详情不一致，等待重新读取')
    return {'task_id': plan_id, 'merchant_account_id': expected,
            'poi_id': str(products[0]['shop_poi_id']), 'product_count': len(ids),
            'source': 'plan_product_api'}


def browser_script(plan_id, detail=False):
    if not isinstance(plan_id, str) or not re.fullmatch(r'\d{10,25}', plan_id):
        raise ValueError('Invalid exact plan ID')
    return '\nPLAN=' + repr(plan_id) + '\nDETAIL=' + repr(detail) + r'''
from urllib.parse import urlencode
time.sleep(6)
def owner_read(path, params):
    q={'groupid':PC_TARGET['group'],'root_life_account_id':PC_TARGET['root'],'life_biz_view_id':22}
    q.update(params)
    ep=path+'?'+urlencode(q)
    raw=js('(async()=>{const c=new AbortController();const t=setTimeout(()=>c.abort(),15000);try{const r=await fetch('+json.dumps(ep)+',{credentials:"include",cache:"no-store",signal:c.signal});return await r.text()}finally{clearTimeout(t)}})()')
    return json.loads(raw)
if DETAIL:
    raw=owner_read('/life/alliance/v1/merchant/task/detail/get/',{'task_id':PLAN,'with_task_draft':'true','with_all_product_info':'true'})
    d=raw.get('task_detail') or {};m=d.get('merchant_detail') or {}
    result={'status_code':raw.get('status_code'),'task_detail':{'task_id':d.get('task_id'),
      'merchant_detail':{'merchant_account_id':m.get('merchant_account_id')},
      'data':{'product_list':[{'product_id':p.get('product_id')} for p in (d.get('data') or {}).get('product_list',[])]}}}
else:
    products=[];seen=set();complete=False
    for page in range(1,11):
        raw=owner_read('/life/alliance/v1/merchant/task/product/search/',{'task_id':PLAN,'page':page,'page_size':100})
        if raw.get('status_code')!=0:break
        batch=raw.get('product_list') or []
        ids=[p.get('product_id') for p in batch]
        if any(not isinstance(i,str) or not i.isdigit() for i in ids) or len(set(ids))!=len(ids) or seen.intersection(ids):break
        seen.update(ids)
        products.extend({k:p.get(k) for k in ('product_id','shop_name','shop_poi_id','shop_num')} for p in batch)
        if raw.get('has_more') is False:complete=True;break
        if not batch:break
    result={'status_code':raw.get('status_code'),'complete':complete,'products':products}
print('PLAN_OWNER_RESULT='+json.dumps(result,ensure_ascii=False))
'''


def resolve(task, cfg, store, runner, possession, urls):
    """Lock shared PC access; fresh products and exact owner verification each run."""
    with store.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM merchant_catalog ORDER BY name')]
    seeds = [r for r in rows if r.get('group_id') and r.get('root_id')
             and str(r.get('merchant_id')) == str(r.get('root_id'))]
    if not seeds:
        raise ResolutionUnavailable('缺少可用的电脑端商家目录，无法反查计划')
    def query(target, detail=False):
        try:
            result = runner(possession(target, urls(target)) + browser_script(task['task_id'], detail),
                profile_dir=(cfg.get('pc_activity') or {}).get('profile_dir'), timeout=180)
            lines = [s.split('=',1)[1] for s in result.stdout.splitlines() if s.startswith('PLAN_OWNER_RESULT=')]
            if result.returncode or len(lines) != 1:
                raise ResolutionUnavailable('电脑端反查暂不可用，请检查项目浏览器登录态或网络')
            return json.loads(lines[0])
        except ResolutionUnavailable:
            raise
        except Exception as exc:
            raise ResolutionUnavailable('电脑端反查连接暂不可用，等待恢复') from exc
    with open(str(store.path)+'.pc.lock', 'a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ResolutionUnavailable('电脑端正在处理其他任务，稍后自动反查') from exc
        data = query(seeds[0])
        if data.get('status_code') != 0 or data.get('complete') is not True:
            raise ResolutionUnavailable('计划商品反查未完整返回，等待恢复后重查')
        products = data.get('products') or []
        target = select_target(products, rows)
        evidence = verify_detail(task['task_id'], query(target, True), target, products)
        # A legal account name may differ from its hotel storefront name. These
        # aliases come only from the verified plan products, never message text.
        target = dict(target, aliases=list(dict.fromkeys(target.get('aliases', []) +
            [p['shop_name'] for p in products if isinstance(p.get('shop_name'), str) and p['shop_name']])))
    return target, evidence
