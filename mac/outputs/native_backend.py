"""Queue adapter for coordinate-free BlueStacks account and business APIs."""
import json
import uuid
import android_runtime
import web_catalog as merchant_catalog
from native_account import NativeAccount
from native_http_api import NativeHttpApi
from native_runtime import NativeRuntime
from native_plan_executor import run as run_plan,detail
from native_plan import inspect_plan
from native_activity_executor import run as run_activity
from plan_owner import select_target,ResolutionUnavailable


def enabled(cfg):
    return android_runtime.emulator(cfg) and (cfg.get('android_device') or {}).get('execution_backend')=='native_api'


def products(api,plan_id):
    rows=[];seen=set()
    for page in range(1,11):
        _,d=api.read('/life/alliance/v1/merchant/task/product/search/',
            params={'task_id':plan_id,'page':page,'page_size':100})
        batch=d.get('product_list')
        if not isinstance(batch,list):raise ResolutionUnavailable('计划商品格式不完整，尚未提交')
        ids=[p.get('product_id') for p in batch]
        if any(not isinstance(i,str) or not i.isdigit() for i in ids) or len(set(ids))!=len(ids) or seen.intersection(ids):
            raise ResolutionUnavailable('计划商品分页重复或 ID 不完整，尚未提交')
        seen.update(ids);rows.extend(batch)
        if d.get('has_more') is False:return rows
        if d.get('has_more') is not True or not batch:break
    raise ResolutionUnavailable('计划商品分页尚未完整返回，尚未提交')


def display_hotel(target,items):
    # A verified POI can be operated under a company legal account. Keep that
    # exact execution identity, but report the actual storefront from the plan.
    names={p['shop_name'].strip() for p in items if isinstance(p.get('shop_name'),str) and p['shop_name'].strip()}
    return next(iter(names)) if len(names)==1 else target['name']


def inspect_link(plan_id,cfg,store,adb):
    """Native migration/preflight read: no task/journal/notification mutations."""
    if not enabled(cfg):raise ValueError('Native backend must be explicitly selected')
    with NativeAccount(adb,android_runtime.endpoint(cfg),autostart=False) as account:
        active=account.identity()['active']
        with NativeHttpApi(account,active['root'],active['account_id']) as api:
            items=products(api,plan_id)
        with store.connect() as db:
            directory=[json.loads(r[0]) for r in db.execute('SELECT data FROM merchant_catalog')]
        target=select_target(items,directory)
        root=str(target.get('root_id') or target['merchant_id']);life=str(target.get('merchant_id') or root)
        active=account.switch(root,life)['active']
        with NativeHttpApi(account,root,active['account_id']) as api:
            items=products(api,plan_id)
            observation=inspect_plan(plan_id,target,items,detail(api,{'task_id':plan_id}))
        return {'target':target,'hotel':display_hotel(target,items),'products':items,
            'observation':observation,'evidence':observation['evidence']}


def plan(task,cfg,store,adb,review_only=False):
    with NativeAccount(adb,android_runtime.endpoint(cfg),autostart=bool((cfg.get('android_device') or {}).get('autostart'))) as account:
        if review_only:
            with store.connect() as db:
                row=db.execute('SELECT data FROM task_targets WHERE task_id=? AND generation=?',
                    (task['task_id'],task['created'])).fetchone()
            if not row:return {'status':'needs_review','text':'原提交商家绑定缺失，不猜测身份或重新同意。'}
            target=json.loads(row[0])
        else:
            active=account.identity()['active']
            with NativeHttpApi(account,active['root'],active['account_id']) as api:
                items=products(api,task['task_id'])
            with store.connect() as db:
                directory=[json.loads(r[0]) for r in db.execute('SELECT data FROM merchant_catalog')]
            target=select_target(items,directory)
        root=str(target.get('root_id') or target['merchant_id']);life=str(target.get('merchant_id') or root)
        active=account.switch(root,life)['active']
        with NativeHttpApi(account,root,active['account_id']) as api:
            # Fresh full products under the selected merchant, not a cache/hint.
            items=products(api,task['task_id'])
            evidence=inspect_plan(task['task_id'],target,items,detail(api,task))['evidence']
            hotel=display_hotel(target,items)
            if not review_only:
                aliases=list(dict.fromkeys(target.get('aliases',[])+[p['shop_name'] for p in items if p.get('shop_name')]))
                target=dict(target,aliases=aliases)
                merchant_catalog.bind_target(store,task,target)
                store.bind_discovered_hotel(task,hotel)
            task['resolved_hotel']=hotel
            store.record_active_identity(task,target,active['name'])
            store.meta('plan_owner:'+task['task_id'],json.dumps(dict(evidence,generation=task['created']),ensure_ascii=False))
            result=run_plan(task,cfg,store,target,items,api,bool(cfg.get('auto_submit')) and not review_only)
            if result.get('reviews'):
                run_id=str(uuid.uuid4())
                for i,o in enumerate(result['reviews'],1):
                    store.record_review(run_id,i,task,hotel,{'state':'succeeded',
                        'reason':'原生详情独立读取：同一商家、计划、草稿、商品及 CPS 直播状态生效；'+o['fingerprint']})
            return result


def activity(job,cfg,store,adb):
    target=json.loads(job['target']);root=str(target.get('root_id') or target.get('root_life_account_id') or target['merchant_id'])
    life=str(target.get('merchant_id') or root);settings=cfg.get('pc_activity') or {}
    with NativeRuntime(adb,android_runtime.endpoint(cfg),root,life,autostart=bool((cfg.get('android_device') or {}).get('autostart'))) as runtime:
        return run_activity({'job':job,'database':store.path,'max_age':
            cfg.get('execution_max_age_seconds',cfg['max_task_age_seconds']),
            'allow_copy':bool(settings.get('allow_authorization_copy')),
            'allow_write':bool(settings.get('allow_authorization_write')) and job['kind']!='authorization_audit'},runtime.api)
