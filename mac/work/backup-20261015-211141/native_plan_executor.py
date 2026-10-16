"""Native plan approval controller; only fresh API ownership can prepare it."""
import json
import time
from native_plan import inspect_plan,approval_packet
from native_plan_journal import load,prepare,PlanPermit
from native_webview_api import SubmissionUncertain
from service_runtime import execution_age


def detail(api,task):
    return api.read('/life/alliance/v1/merchant/task/detail/get/',params={
        'task_id':task['task_id'],'with_task_draft':True,'with_all_product_info':True,'with_task_order':True})[1]


def verify_twice(api,task,target,products,committed=None):
    observations=[]
    for _ in range(2):
        o=inspect_plan(task['task_id'],target,products,detail(api,task))
        if o['state']!='already_active':return None
        if committed:
            s=o['snapshot']
            keys=('task_id','draft_id','root','poi','products','product_terms','requirement','settlement','tiered_commission','activity')
            # Historical journals did not store draft terms. Preserve their
            # existing review contract; every newly prepared packet freezes them.
            if 'draft_terms' in committed:keys+=('draft_terms',)
            for key in keys:
                if s.get(key)!=committed.get(key):return None
        observations.append(o)
    if observations[0]['fingerprint']!=observations[1]['fingerprint']:return None
    return observations


def run(task,cfg,store,target,products,api,allow_write):
    journal=load(store.path,task)
    if task['stage'] in ('submitting','confirming','verifying') or journal and journal['dispatched_at'] is not None:
        if not journal:return {'status':'needs_review','text':'提交后缺少原生计划预览，不重放确认请求。'}
        reviews=verify_twice(api,task,target,products,json.loads(journal['data'])['snapshot'])
        return ({'status':'succeeded','text':'计划已生效，已独立复核两次；未重复提交。','reviews':reviews} if reviews
            else {'status':'waiting_review','text':'提交结果尚未确认，继续只读复核，不会重新同意。'})
    response=detail(api,task);observation=inspect_plan(task['task_id'],target,products,response)
    if observation['state']=='already_active':
        reviews=verify_twice(api,task,target,products)
        return ({'status':'succeeded','text':'计划已经开通，已独立复核两次；没有重复同意。','reviews':reviews} if reviews
            else {'status':'queued','text':'已有计划状态暂不一致，重新只读核验；尚未提交。'})
    if observation['state']=='closed':return {'status':'failed','text':'计划已拒绝、过期、取消或结束，本次未提交。'}
    if not allow_write:return {'status':'needs_review','text':'待确认计划已识别，但原生确认写入尚未启用；未提交。'}
    _,permission=api.read('/life/alliance/v1/merchant/partner/permission/check/')
    _,marketing=api.read('/life/alliance/v1/merchant/task/marketing/activity/get/',body={'task_id':task['task_id']})
    body=approval_packet(observation,response,permission,marketing,time.time())
    expected={'root':api.expected_root,'snapshot':observation['snapshot'],'fingerprint':observation['fingerprint'],'body':body}
    store.submission_gate(task,cfg,'api_prepared')
    prepare(store.path,task,expected)
    fresh=detail(api,task)
    # Permissions and associated marketing activities may change independently
    # of the draft. Re-read both at the second boundary, not just plan detail.
    _,fresh_permission=api.read('/life/alliance/v1/merchant/partner/permission/check/')
    _,fresh_marketing=api.read('/life/alliance/v1/merchant/task/marketing/activity/get/',body={'task_id':task['task_id']})
    body_again=approval_packet(observation,fresh,fresh_permission,fresh_marketing,time.time())
    if body_again!=body:raise RuntimeError('计划确认参数已变化，尚未提交')
    store.submission_gate(task,cfg,'confirming')
    try:api.submit_plan_once(body,PlanPermit(store.path,task,expected,execution_age(cfg)))
    except SubmissionUncertain:
        return {'status':'waiting_review','text':'确认响应尚未读取完成，继续只读复核，不会再次发送。'}
    return {'status':'waiting_review','text':'已发送一次计划同意请求，进入独立结果复核。'}
