"""Exact plan ownership/state and the officially observed approval packet.

merchant_h5 enums: Oriented=30, media Live=2, WaitAccept=2,
InProgress=3, task_draft_status WaitConfirm=1/Approved=2, Approve=5.
Packets are frozen by the durable native plan journal before dispatch.
"""
from copy import deepcopy
import hashlib
import json
from native_activity import exact_id
from pc_executor import NeedsReview
from plan_owner import verify_detail

CONFIRM_PATH='/life/alliance/v1/merchant/broker/operation/confirm/'


def draft_business_terms(task):
    """Freeze draft terms independently; the main task can legitimately differ."""
    data=task.get('data') or {}
    terms={'product_terms':sorted(({k:p.get(k) for k in ('product_id','actual_price','origin_price',
        'commission_rate','product_type','product_sub_type','sold_start_time','sold_end_time')}
        for p in data.get('product_list',[])),key=lambda p:p['product_id']),
        'requirement':data.get('requirement'),'settlement':data.get('settlement'),
        'tiered_commission':data.get('tiered_commission'),'activity':data.get('activity')}
    return deepcopy(terms)


def inspect_plan(plan_id,target,products,response):
    evidence=verify_detail(plan_id,response,target,products)
    task=response['task_detail'];data=task.get('data')or{};draft=response.get('task_draft_detail')or{}
    if task.get('task_type')!=30 or (data.get('requirement')or{}).get('media_type')!=2:
        raise NeedsReview('计划并非已核验的定向 CPS 直播计划，尚未提交')
    draft_id=exact_id(data.get('task_draft_id'))
    if exact_id(draft.get('task_draft_id'))!=draft_id:
        raise NeedsReview('计划与草稿身份不一致，尚未提交')
    draft_task=draft.get('task')or{}
    if draft_task.get('task_id')!=plan_id:
        raise NeedsReview('确认草稿不属于当前计划，尚未提交')
    verify_detail(plan_id,{'status_code':0,'task_detail':draft_task},target,products)
    if (draft_task.get('data')or{}).get('requirement',{}).get('media_type')!=2:
        raise NeedsReview('草稿直播类型与当前计划不一致，尚未提交')
    status=task.get('status');draft_status=draft.get('task_draft_status')
    if status==3 and draft_status==2:state='already_active'
    elif status==2 and draft_status==1:state='pending'
    elif status in (4,5) or draft_status in (3,4,5):state='closed'
    else:raise NeedsReview('计划或草稿状态未确认，尚未提交')
    snapshot={'task_id':plan_id,'draft_id':draft_id,'root':evidence['merchant_account_id'],
        'poi':evidence['poi_id'],'products':sorted(p['product_id'] for p in products),
        'product_terms':sorted(({k:p.get(k) for k in ('product_id','actual_price','origin_price',
            'commission_rate','product_type','product_sub_type','sold_start_time','sold_end_time')}
            for p in data.get('product_list',[])),key=lambda p:p['product_id']),
        'requirement':data.get('requirement'),'settlement':data.get('settlement'),
        'tiered_commission':data.get('tiered_commission'),'activity':data.get('activity'),
        'confirm_deadline':data.get('task_confirm_end_time'),'draft_update_time':draft.get('update_time'),
        'draft_terms':draft_business_terms(draft_task)}
    fingerprint=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    # Labels stay outside the fingerprint freeze so older journals still verify.
    product_labels=[{'product_id':exact_id(p.get('product_id')),
        'name':p.get('product_name'),'commission_rate':p.get('commission_rate')}
        for p in data.get('product_list',[])]
    return {'state':state,'snapshot':snapshot,'fingerprint':fingerprint,'evidence':evidence,
        'product_labels':product_labels}


def approval_packet(observation,response,permission,marketing,now):
    if observation['state']!='pending':raise NeedsReview('只有待确认计划可发送同意，已有结果只复核')
    s=observation['snapshot']
    products=[{'product_id':pid,'shop_num':1,'shop_poi_id':s['poi']} for pid in s['products']]
    fresh=inspect_plan(s['task_id'],{'root_id':s['root']},products,response)
    if fresh['fingerprint']!=observation['fingerprint'] or fresh['state']!='pending':
        raise NeedsReview('准备期间计划已变化，尚未提交')
    if permission.get('status_code')!=0 or permission.get('has_perm') is not True:
        raise NeedsReview('当前商家未返回计划操作权限，尚未提交')
    deadline=s['confirm_deadline']
    if isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or now>=deadline:
        raise NeedsReview('计划确认时限未核验或已过期，尚未提交')
    draft=response.get('task_draft_detail')or{};extra=draft.get('extra')or{}
    if extra.get('OperationType')!=1:
        raise NeedsReview('该草稿不是新开团创建，不自动同意修改或终止')
    activity=s.get('activity')or{};info=activity.get('marketing_activity_info')or{}
    need=info.get('NeedMarketingActivity') is True
    if marketing.get('status_code')!=0:raise NeedsReview('配套营销活动未读取完成，尚未提交')
    rows=marketing.get('ActivityInfoList')
    if not isinstance(rows,list):raise NeedsReview('配套营销活动结果不完整，尚未提交')
    if need and not rows:raise NeedsReview('计划要求配套营销活动，但尚未配置；不擅自新增商品价格或库存')
    if rows and not need:raise NeedsReview('营销活动与计划要求不一致，尚未提交')
    for row in rows:
        exact_id(row.get('MarketingActivityID'))
        if row.get('MarketingActivityType') is None or not str(row['MarketingActivityType']).strip():
            raise NeedsReview('配套营销活动类型未核验，尚未提交')
    body={'operation_type':5,'task_id':s['task_id'],'task_draft_id':s['draft_id']}
    if rows:body['confirm_update_info']={'marketing_activity_list':deepcopy(rows)}
    return body
