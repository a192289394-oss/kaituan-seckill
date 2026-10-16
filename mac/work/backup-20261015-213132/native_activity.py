"""Official live-seckill API payloads, without form state or coordinate input.

Audited against tools_merchant_new_pc 1.0.0.9836: batch_input user_type=3,
minus_activity/pre_check then save, Discount-Type=20. Existing coupon IDs and
allocated quantities are retained on edit; copy creates only requested grants.
"""
from copy import deepcopy
import re
from pc_executor import NeedsReview,template_spec

SAVE_PATH='/life/marketing/v1/minus_activity/save'
PRECHECK_PATH='/life/marketing/v1/minus_activity/pre_check'
LOOKUP_PATH='/life/hermes/marketing_tool/live/douyin_id/batch_input'
DISCOUNT_TYPE='merchant_live_flash_promotion'


def exact_id(value):
    if isinstance(value,bool) or not re.fullmatch(r'[0-9]{1,25}',str(value)) or int(value)<=0:
        raise NeedsReview('接口身份编号未精确核验，尚未提交')
    return str(value)


def lookup_body(source,accounts,copy=False):
    if not accounts or len(set(accounts))!=len(accounts) or any(not isinstance(a,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{2,64}',a) for a in accounts):
        raise NeedsReview('抖音号列表不完整或重复')
    body={'douyin_ids':' '.join(accounts),'user_type':3,
          'sku_list':[{'sku_id':exact_id(s['sku_id']),'product_id':exact_id(s['product_id'])} for s in source['sku_list']],
          'start_time':int(source['start_time']),'end_time':int(source['end_time'])}
    if not copy:body['exist_activity_id']=exact_id(source['activity_id'])
    return body


def resolve_creators(data,accounts):
    if data.get('status_code')!=0 or data.get('fail_douyin_ids'):
        raise NeedsReview('平台未完整解析指定抖音号，尚未提交')
    rows=data.get('success_anchor_list')
    if not isinstance(rows,list):raise NeedsReview('平台未返回主播身份列表')
    resolved={};uids=set()
    for row in rows:
        account=row.get('douyin_id')
        if account not in accounts or account in resolved or row.get('user_type')!=3:
            raise NeedsReview('平台返回的抖音号或主播类型与请求不符')
        uid=exact_id(row.get('uid'))
        if uid in uids:raise NeedsReview('不同抖音号映射同一身份，需核对')
        uids.add(uid);resolved[account]={'uid':uid,'identity_type':1,'douyin_id':account}
    if set(resolved)!=set(accounts):raise NeedsReview('指定抖音号未全部解析成功')
    return resolved


def authorization_payload(source,accounts,creators,root,max_anchors=60):
    """Do not submit an unchanged activity or re-grant an existing creator."""
    root=exact_id(root);exact_id(source['activity_id'])
    if source.get('discount_type')!=DISCOUNT_TYPE or int(source.get('coupon_type',-1))!=20:
        raise NeedsReview('模板不是已核验的直播秒杀')
    if int(source.get('activity_status',-1))!=2:
        raise NeedsReview('模板当前不是生效活动')
    if not accounts or len(set(accounts))!=len(accounts) or set(creators)!=set(accounts):
        raise NeedsReview('指定账号与已解析账号不一致')
    if not isinstance(max_anchors,int) or max_anchors<1:raise ValueError('Invalid anchor limit')
    existing={exact_id(a['uid']) for a in source['anchor_info_list']}
    new=[];seen=set()
    for account in accounts:
        a=creators[account];uid=exact_id(a['uid'])
        if a.get('douyin_id')!=account or a.get('identity_type')!=1 or uid in existing or uid in seen:
            raise NeedsReview('账号已存在或身份冲突，需重新跨活动只读核对')
        seen.add(uid);new.append({'uid':uid,'identity_type':1,'douyin_id':account})
    spec=template_spec(source)
    copy=len(existing)+len(new)>max_anchors
    if len(new)>max_anchors:raise NeedsReview('单次指定主播超过平台活动容量')
    activity=deepcopy(source)
    # Readback-only metadata never becomes a request parameter. All unlisted
    # business settings remain identical to the verified source snapshot.
    for key in ('activity_status','create_time','update_time','creator_account_name','sku_count',
                'activity_discount_unit_list','intelligent_creation_display_plan_list'):
        activity.pop(key,None)
    activity['activity_id']=exact_id(source['activity_id'])
    if copy:
        activity.pop('activity_id',None);activity.pop('merchant_act_id',None)
        activity['anchor_info_list']=deepcopy(new)
        activity['anchor_broker_info_list']=[]
    else:
        activity['anchor_info_list']=deepcopy(source['anchor_info_list'])+deepcopy(new)
    for sku in activity['sku_list']:
        product=exact_id(sku['product_id']);sku['sku_id']=exact_id(sku['sku_id']);sku['product_id']=product
        if spec[product]['sku_id']!=sku['sku_id']:raise NeedsReview('模板商品与规格不一致')
        original=deepcopy(sku.get('anchor_list',[]))
        sku.pop('product_info',None);sku.pop('left_quantity',None)
        # GET returns aggregate quantity across all creators (e.g. 21*2000).
        # The official multi-SKU save form uses PER-creator quantity here.
        # Forwarding the aggregate would multiply inventory on the new grant.
        sku['total_quantity']=spec[product]['stock']
        sku['anchor_list']=[] if copy else original
        if copy:
            # A new creator-only activity must not allocate unrelated DSS or
            # merchant/broker channel inventory a second time.
            sku['dss_stock_info_list']=[]
        for grant in sku['anchor_list']:
            grant['uid']=exact_id(grant['uid'])
            if 'coupon_id' in grant:grant['coupon_id']=exact_id(grant['coupon_id'])
            grant.pop('left_quantity',None)
        for a in new:
            sku['anchor_list'].append({'uid':a['uid'],'identity_type':1,
                'fixed_price':spec[product]['price'],'total_quantity':spec[product]['stock']})
    return {'mode':'copy' if copy else 'edit','accounts':list(accounts),
            'body':{'selected_account_id':root,'activity':activity}}


def verify_precheck(response):
    if response.get('status_code')!=0 or not isinstance(response.get('pre_check_result'),dict):
        raise NeedsReview('平台预检查未完整返回，尚未提交')
    # Official frontend also stops for non-empty duplicate/blocked SKU maps;
    # HTTP/business status 0 alone does not mean the packet is ready to save.
    if any(response.get(k) for k in ('pre_check_result','sku_block_msg_map','product_validation_result','double_check_info')):
        raise NeedsReview('平台预检查提示商品、授权或价格条件需处理，尚未提交')
