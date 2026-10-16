"""Web-only renewal of an expired live-seckill template, with explicit dates.

Official tools_merchant_new_pc sources (work/official-assets-20261014):
marketing-chunk-2987 activity-ID DSL writes IDs only for isEdit; the SKU
apiToForm transform retains coupon IDs only for isEdit. The live-flash request
transform rebuilds per-creator price/stock. marketing-62e7e448 defines save,
pre_check, batch_input; NotStart=1 and Valid=2 are distinct saved states.
No notification or UI operation is performed here.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import time
from zoneinfo import ZoneInfo

import android_runtime
import native_backend
import native_activity_executor
import pc_jobs
from native_activity import (DISCOUNT_TYPE, LOOKUP_PATH, PRECHECK_PATH, exact_id,
    lookup_body, resolve_creators, verify_precheck)
from native_commit import ActivityPermit,NativeDispatchDenied
from native_webview_api import SubmissionUncertain
from pc_authorization import parse_activity_response
from pc_executor import NeedsReview, template_spec

BEIJING=ZoneInfo('Asia/Shanghai')
VOLATILE={'create_time','update_time','creator_account_name','sku_count','anchor_count',
    'activity_discount_unit_list','intelligent_creation_display_plan_list',
    'left_quantity','left_quantity_realtime','left_stock','sold_count','sold_quantity',
    'coupon_order_cnt','coupon_sell_cnt','coupon_order_amount','stock_insufficient_status'}
RECORD_IDS={'activity_id','merchant_act_id','activity_detail_id','coupon_id'}
PARAMETERS={'template_id','fingerprint','start_time','end_time','confirmed'}
CURRENT_PRODUCT_PATH='/life/marketing/v1/marketing/account/product/list'


class CreateBlocked(NeedsReview):
    """Source settings lack evidence for a creator-only copy contract."""


class CreationPermit(ActivityPermit):
    def consume(self,root,body):
        activity=body.get('activity') or {};start=activity.get('start_time');end=activity.get('end_time')
        if (isinstance(start,bool) or not isinstance(start,(int,float)) or not math.isfinite(start)
                or isinstance(end,bool) or not isinstance(end,(int,float)) or not math.isfinite(end)
                or not time.time()<start<end):
            raise NativeDispatchDenied('新档期开始时间已到或发生变化；尚未发送，不重放。')
        super().consume(root,body)


def stable(value,remove_ids=False):
    """Remove observed readback statistics; retain all other source settings."""
    if isinstance(value,dict):
        return {k:stable(v,remove_ids) for k,v in value.items()
            if k not in VOLATILE and (not remove_ids or k not in RECORD_IDS)}
    if isinstance(value,list):
        rows=[stable(v,remove_ids) for v in value]
        if rows and all(isinstance(v,dict) for v in rows):
            rows.sort(key=lambda v:json.dumps(v,sort_keys=True,ensure_ascii=False,allow_nan=False))
        return rows
    return value


def fingerprint(source):
    # Signed CDN URLs change on every read. These exact display-only paths are
    # absent from the creator-only create packet: old actors are replaced and
    # SKU product_info is removed. Keep every other field in the fingerprint.
    snapshot=deepcopy(source)
    for anchor in snapshot.get('anchor_info_list',[]):
        avatar=anchor.get('avatar')
        if isinstance(avatar,dict):avatar.pop('url_list',None)
    for sku in snapshot.get('sku_list',[]):
        info=sku.get('product_info')
        if isinstance(info,dict):info.pop('image_list',None)
    return hashlib.sha256(json.dumps(stable(snapshot),sort_keys=True,ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()


class AllActivities(native_activity_executor.Activities):
    """Read complete pages and exact raw details, including expired activities."""
    def read(self):
        result=[];seen=set()
        for page in range(1,101):
            _,data=self.api.read('/life/marketing/v1/minus_activity/list',body={
                'discount_type':DISCOUNT_TYPE,'selected_account_id':'',
                'pagination':{'current_page':page,'page_size':100}})
            pagination=data.get('pagination') or {};rows=data.get('activities')
            if not isinstance(rows,list) or not isinstance(pagination.get('has_more'),bool):
                raise NeedsReview('活动目录分页不完整；没有提交。')
            for row in rows:
                aid=exact_id(row.get('activity_id'))
                if aid in seen:raise NeedsReview('活动分页重复；没有提交。')
                seen.add(aid)
                raw,_=self.api.read('/life/marketing/v1/minus_activity/info',params={
                    'activity_id':aid,'selected_account_id':'','discount_type':DISCOUNT_TYPE})
                result.append(parse_activity_response(raw,aid))
            if pagination['has_more'] is False:return result
            if not rows:raise NeedsReview('活动分页未明确结束；没有提交。')
        raise NeedsReview('活动目录超过分页上限；没有提交。')


def integer(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value!=int(value):
        raise NeedsReview(label+'必须为精确整数。')
    return int(value)


def source_spec(source):
    if source.get('discount_type')!=DISCOUNT_TYPE or integer(source.get('coupon_type'),'活动类型')!=20:
        raise NeedsReview('旧模板不是已核验的直播秒杀。')
    spec=template_spec(source)
    for sku in source['sku_list']:
        exact_id(sku['product_id']);exact_id(sku['sku_id'])
        for grant in sku.get('anchor_list',[]):
            if grant.get('identity_type')==1:
                if integer(grant['fixed_price'],'价格')<=0 or integer(grant['total_quantity'],'每达人库存')<=0:
                    raise NeedsReview('旧模板价格或每达人库存不完整。')
    return spec


def preview(source,accounts,reason):
    spec=source_spec(source);products=[]
    for sku in source['sku_list']:
        pid=exact_id(sku['product_id']);info=sku.get('product_info') or {}
        products.append({'id':pid,'name':info.get('product_name') or sku.get('product_name') or '商品 '+pid,
            'price_cents':spec[pid]['price'],'stock_per_creator':spec[pid]['stock']})
    result={'template_id':exact_id(source['activity_id']),'fingerprint':fingerprint(source),
        'products':products,'accounts':list(accounts),'start_time_old':integer(source['start_time'],'旧开始时间'),
        'end_time_old':integer(source['end_time'],'旧结束时间'),'reason':reason,'timezone':'Asia/Shanghai',
        'current_product_check':{'status':'required','source':'old_activity_snapshot',
            'reason':'旧活动中的商品信息可能是快照；当前可售、销售和使用时段须按所确认新档期重新读取，未验证不允许新建。'}}
    try:creation_support(source)
    except CreateBlocked as exc:result.update(blocked=True,reason=str(exc))
    return result


def expired_templates(activities,now):
    result=[]
    for activity in activities:
        if activity.get('activity_status')==3 and integer(activity['end_time'],'旧结束时间')<=now:
            try:source_spec(activity)
            except (NeedsReview,ValueError,KeyError,TypeError):continue
            result.append(activity)
    return sorted(result,key=lambda a:(int(a['end_time']),exact_id(a['activity_id'])),reverse=True)


def blank_creation(source):
    """Official copy semantics: no existing rights, broker, or DSS allocation."""
    activity=stable(deepcopy(source),remove_ids=True)
    activity.pop('activity_status',None)
    for key in ('anchor_info_list','anchor_info_list_douyin','anchor_info_list_no_douyin',
            'alliance_task_relation_info'):
        activity.pop(key,None)
    activity['anchor_info_list']=[];activity['anchor_broker_info_list']=[]
    for sku in activity['sku_list']:
        sku.pop('product_info',None);sku.pop('anchor_list',None)
        sku['dss_stock_info_list']=[]
    return activity


def candidate_signature(source):
    config=blank_creation(source)
    for key in ('activity_name','start_time','end_time'):config.pop(key,None)
    spec=source_spec(source)
    for sku in config['sku_list']:
        pid=str(sku['product_id']);sku['total_quantity']=spec[pid]['stock']
    return json.dumps(config,sort_keys=True,ensure_ascii=False,allow_nan=False)


def need_input(activities,accounts,now,reason=None):
    candidates=expired_templates(activities,now)
    reason=reason or '没有可沿用的生效达人秒杀。旧活动仅作候选；请确认商品、每达人价格/库存和新开始、结束日期。'
    if not candidates:return {'status':'needs_input','text':reason,'details':{'reason':reason,'candidates':[]}}
    views=[preview(a,accounts,reason) for a in candidates]
    details={'reason':reason,'candidates':views}
    if len({candidate_signature(a) for a in candidates})==1:details['preview']=views[0]
    else:
        details['reason']='旧模板商品、价格、库存或其它条款不同；请明确选择模板，再填写新档期。'
    if details.get('preview',{}).get('blocked'):
        details['blocked']=True;details['reason']=details['preview']['reason']
    return {'status':'needs_input','text':details['reason'],'details':details}


def validate_parameters(parameters,source,now):
    if not isinstance(parameters,dict) or set(parameters)!=PARAMETERS or parameters.get('confirmed') is not True:
        raise NeedsReview('请明确确认模板指纹及新开始、结束时间；不接受改价、改库存或默认日期。')
    if parameters['template_id']!=exact_id(source['activity_id']) or parameters['fingerprint']!=fingerprint(source):
        raise NeedsReview('旧模板与网页预览不一致；请重新审阅。')
    start=integer(parameters['start_time'],'新开始时间');end=integer(parameters['end_time'],'新结束时间')
    if not now<start<end or end>253402214400:
        raise NeedsReview('新开始时间必须在当前时间之后，结束时间必须晚于开始时间（北京时间）。')
    if source.get('activity_status')!=3 or integer(source['end_time'],'旧结束时间')>now:
        raise NeedsReview('所选活动不再是已结束模板；请重新审阅。')
    return start,end


def current_product_check(api,source,start,end):
    """Official product picker contract, never stale activity product_info.

    marketing-chunk-3572 modules 193274/728441 use the account/product/list
    GET, cursor=current_page-1, product_list/total, is_deny/deny_reason and
    sold_start_time/sold_end_time. Fixed use_date is verified when supplied;
    missing or calendar-dependent policy remains unknown, never zero/valid.
    """
    wanted={exact_id(s['product_id']):exact_id(s['sku_id']) for s in source['sku_list']}
    found={};seen=set();all_rows=[];complete=False
    for cursor in range(100):
        _,data=api.read(CURRENT_PRODUCT_PATH,params={'selected_account_id':api.expected_root,
            # The official picker itself reads the whole candidate list. Avoid
            # guessing an array serializer for product_id_list; match exact IDs
            # only after complete pages under this merchant and activity window.
            'coupon_type':20,'mkt_activity_type':2,
            'size':100,'cursor':cursor,'activity_start_time':start,'activity_end_time':end})
        rows=data.get('product_list');total=data.get('total')
        if isinstance(total,str) and total.isdigit():total=int(total)
        if not isinstance(rows,list) or isinstance(total,bool) or not isinstance(total,int) or total<0:
            raise NeedsReview('当前商品列表/总数未完整读取；没有新建。')
        for product in rows:
            pid=exact_id(product.get('product_id'))
            if pid in seen:raise NeedsReview('当前商品分页重复；没有新建。')
            seen.add(pid)
            all_rows.append(product)
            if pid in wanted:found[pid]=product
        if len(seen)>=total:complete=True;break
        if not rows:raise NeedsReview('当前商品分页未完整结束；没有新建。')
    if not complete:raise NeedsReview('当前商品列表超过分页上限；没有新建。')
    checks=[]
    for pid,sku_id in wanted.items():
        row=found.get(pid);check={'id':pid,'sku_id':sku_id,'status':'unknown','source':'current_product_api','reasons':[]}
        if row is None:
            check['reasons'].append('当前商品接口未返回精确商品；无法证明当前可售。');checks.append(check);continue
        # Record only the fields needed for business review; do not copy URLs,
        # user metadata, auth, or the full product response into public details.
        check.update(name=row.get('product_name'),sold_start_time=row.get('sold_start_time'),
            sold_end_time=row.get('sold_end_time'),available_quantity=row.get('avail_qty'),
            platform_is_deny=row.get('is_deny'),platform_deny_reason=row.get('deny_reason') or None,
            candidate_returned=True)
        blocked=False;unknown=False
        if row.get('is_deny') is True or row.get('deny_reason'):
            blocked=True;check['reasons'].append(row.get('deny_reason') or '平台明确禁选。')
        elif row.get('is_deny') is not None and row.get('is_deny') is not False:
            unknown=True;check['reasons'].append('平台未明确返回商品禁选状态。')
        # The official picker disables a row on truthy is_deny; a missing
        # optional flag is accepted by that UI. Keep its value as None here,
        # rather than inventing an explicit false or a zero inventory.
        skus=row.get('sku_list')
        matches=[s for s in skus if str(s.get('id'))==sku_id] if isinstance(skus,list) else []
        if len(matches)!=1:
            unknown=True;check['reasons'].append('当前商品没有唯一匹配模板规格。')
        elif matches[0].get('is_deny') is True or matches[0].get('deny_reason'):
            blocked=True;check['reasons'].append(matches[0].get('deny_reason') or '平台明确禁选该规格。')
        elif matches[0].get('is_deny') is not None and matches[0].get('is_deny') is not False:
            unknown=True;check['reasons'].append('当前规格禁选标记不是已核验的布尔合同。')
        try:
            sale_start=integer(row.get('sold_start_time'),'当前商品销售开始');sale_end=integer(row.get('sold_end_time'),'当前商品销售结束')
            available=integer(row.get('avail_qty'),'当前商品可售库存')
            if not 0<sale_start<=start<end<=sale_end:
                blocked=True;check['reasons'].append('当前商品销售时段未覆盖新活动完整档期。')
            if available<=0:blocked=True;check['reasons'].append('当前商品明确无可售库存。')
        except NeedsReview:
            unknown=True;check['reasons'].append('当前销售时段或商品可售库存未完整核验。')
        use=row.get('use_date')
        if isinstance(use,dict):
            check['use_date']={k:use.get(k) for k in ('use_date_type','use_start_date','use_end_date','days_of_week')}
        if not isinstance(use,dict) or use.get('use_date_type')!=1:
            unknown=True;check['reasons'].append('当前使用时段缺失或需日历规则核验；不沿用旧快照。')
        else:
            try:
                use_start=datetime.strptime(use['use_start_date'],'%Y-%m-%d').replace(tzinfo=BEIJING).timestamp()
                use_end=datetime.strptime(use['use_end_date'],'%Y-%m-%d').replace(tzinfo=BEIJING).timestamp()+86400-1
                if not use_start<=use_end or use_end<end:
                    blocked=True;check['reasons'].append('当前商品使用有效期未覆盖活动结束；不擅自延期商品。')
            except (KeyError,TypeError,ValueError):
                unknown=True;check['reasons'].append('当前商品使用日期格式尚未核验。')
        check['status']='blocked' if blocked else 'unknown' if unknown else 'verified'
        checks.append(check)
    status='blocked' if any(p['status']=='blocked' for p in checks) else 'unknown' if any(p['status']=='unknown' for p in checks) else 'verified'
    candidates=[]
    for row in all_rows:
        for sku in row.get('sku_list',[]):
            candidates.append({'id':str(row.get('product_id')),'sku_id':str(sku.get('id')),
                'name':row.get('product_name'),'price_cents':sku.get('sku_amount'),
                'suggested_price_cents':sku.get('suggest_activity_amount'),
                'is_deny':row.get('is_deny'),'deny_reason':row.get('deny_reason'),
                'sold_start_time':row.get('sold_start_time'),'sold_end_time':row.get('sold_end_time'),
                'use_date':row.get('use_date')})
    return {'status':status,'source':'current_product_api','start_time':start,'end_time':end,'products':checks,
        'legal_candidate_ids':[p['id'] for p in checks if p['status']=='verified'],'current_candidates':candidates}


def creation_support(source):
    # These automatic modes can authorise unrelated actors. Their manual
    # equivalents have not been validated for this renewal path: fail closed.
    extra=source.get('extra_map') or {}
    if (extra.get('auto_assign_user_limit') or extra.get('auto_live_flash_config') or source.get('auto_assign_config')
            or any(a.get('auto_type') not in (None,0,1) for a in source.get('anchor_info_list',[]))):
        raise CreateBlocked('旧模板含自动分配达人配置；当前不能证明新建只授指定账号，请人工审阅。')
    def inspect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.startswith('coupon_') and key not in {'coupon_type','coupon_id'}|VOLATILE and item:
                    raise CreateBlocked('旧模板含尚未验证复制语义的券配置；保留预览，请人工审阅。')
                inspect(item)
        elif isinstance(value,list):
            for item in value:inspect(item)
    inspect(source)


def creation_payload(source,accounts,creators,root,start,end):
    spec=source_spec(source);root=exact_id(root)
    if not accounts or len(accounts)>60 or len(set(accounts))!=len(accounts) or set(creators)!=set(accounts):
        raise NeedsReview('请求账号不完整、重复或超过单活动容量。')
    creation_support(source)
    activity=blank_creation(source)
    activity['start_time']=start;activity['end_time']=end
    new=[];uids=set()
    for account in accounts:
        creator=creators[account];uid=exact_id(creator['uid'])
        if creator.get('douyin_id')!=account or creator.get('identity_type')!=1 or uid in uids:
            raise NeedsReview('请求账号与平台精确达人身份不一致。')
        uids.add(uid);new.append({'uid':uid,'identity_type':1,'douyin_id':account})
    activity['anchor_info_list']=new
    for sku in activity['sku_list']:
        pid=exact_id(sku['product_id']);sku['product_id']=pid;sku['sku_id']=exact_id(sku['sku_id'])
        sku['fixed_price']=spec[pid]['price'];sku['total_quantity']=spec[pid]['stock']
        sku['anchor_list']=[{'uid':a['uid'],'identity_type':1,'fixed_price':spec[pid]['price'],
            'total_quantity':spec[pid]['stock']} for a in new]
    return {'selected_account_id':root,'activity':activity}


def overlap_conflicts(activities,body):
    wanted=body['activity'];uids={a['uid'] for a in wanted['anchor_info_list']}
    skus={s['sku_id'] for s in wanted['sku_list']};conflicts=[]
    for activity in activities:
        if activity.get('activity_status') not in (1,2):continue
        if not int(activity['start_time'])<wanted['end_time'] or not wanted['start_time']<int(activity['end_time']):continue
        for sku in activity.get('sku_list',[]):
            if str(sku.get('sku_id')) in skus and any(str(g.get('uid')) in uids for g in sku.get('anchor_list',[])):
                conflicts.append(exact_id(activity['activity_id']));break
    return sorted(set(conflicts))


def matches_saved(activity,body,now):
    """Saved future configuration is distinct from a currently effective grant."""
    expected=body['activity'];status=activity.get('activity_status')
    if status!=(1 if now<expected['start_time'] else 2) or now>=expected['end_time']:return False
    actual=blank_creation(activity)
    wanted=blank_creation(expected)
    # Server-only response fields may be added; every requested setting must
    # still match. Original actor lists are checked separately below.
    for key,value in wanted.items():
        if key not in ('sku_list','anchor_info_list','anchor_broker_info_list') and stable(actual.get(key))!=stable(value):return False
    anchors=activity.get('anchor_info_list') or []
    requested={a['uid']:a['douyin_id'] for a in expected['anchor_info_list']}
    if (len(anchors)!=len(requested) or {str(a.get('uid')) for a in anchors}!=set(requested)
            or any(a.get('identity_type')!=1 or a.get('douyin_id') not in (None,'',requested.get(str(a.get('uid')))) for a in anchors)
            or activity.get('anchor_broker_info_list') or activity.get('alliance_task_relation_info')):return False
    rows={str(s.get('sku_id')):s for s in activity.get('sku_list',[])}
    if len(rows)!=len(expected['sku_list']) or len(rows)!=len(activity.get('sku_list',[])):return False
    for sku in expected['sku_list']:
        found=rows.get(sku['sku_id'])
        if not found or str(found.get('product_id'))!=sku['product_id'] or found.get('dss_stock_info_list'):return False
        for key,value in sku.items():
            if key not in ('anchor_list','dss_stock_info_list','total_quantity','product_id','sku_id') and stable(found.get(key))!=stable(value):return False
        grants=found.get('anchor_list') or []
        if len(grants)!=len(requested) or {str(g.get('uid')) for g in grants}!=set(requested):return False
        for grant in grants:
            try:
                price=integer(grant.get('fixed_price'),'结果价格');stock=integer(grant.get('total_quantity'),'结果每达人库存')
            except NeedsReview:return False
            if grant.get('identity_type')!=1 or price!=sku['fixed_price'] or stock!=sku['total_quantity']:return False
            if status==2 and (not isinstance(grant.get('left_quantity'),(int,float)) or grant['left_quantity']<=0):return False
    return True


def review_new(reader,expected):
    reviews=[]
    for _ in range(2):
        current=reader.read();original=[a for a in current if exact_id(a['activity_id'])==expected['template_id']]
        if len(original)!=1 or fingerprint(original[0])!=expected['template_fingerprint']:return None
        matching=[a for a in current if exact_id(a['activity_id']) not in expected['pre_existing_ids']
            and matches_saved(a,expected['preview']['body'],time.time())]
        if len(matching)!=1:return None
        found=matching[0]
        reviews.append({'activity_id':exact_id(found['activity_id']),'state':'pending' if found['activity_status']==1 else 'active',
            'at':time.time(),'start_time':found['start_time'],'end_time':found['end_time'],
            'products':expected['products'],'accounts':expected['accounts']})
    if reviews[0]['activity_id']!=reviews[1]['activity_id'] or reviews[0]['state']!=reviews[1]['state']:return None
    return reviews


def review_existing_window(reader,body,template_id,template_fingerprint):
    reviews=[]
    for _ in range(2):
        current=reader.read();original=[a for a in current if exact_id(a['activity_id'])==template_id]
        if len(original)!=1 or fingerprint(original[0])!=template_fingerprint:return None
        matching=[a for a in current if matches_saved(a,body,time.time())]
        if len(matching)!=1:return None
        found=matching[0]
        reviews.append({'activity_id':exact_id(found['activity_id']),
            'state':'pending' if found['activity_status']==1 else 'active','at':time.time()})
    if reviews[0]['activity_id']!=reviews[1]['activity_id'] or reviews[0]['state']!=reviews[1]['state']:return None
    return reviews


def run_api(job,cfg,store,api,parameters=None):
    """Transport-independent core. The worker supplies a fenced runtime API."""
    accounts=json.loads(job['accounts']);reader=AllActivities(api)
    journal=pc_jobs.load_journal(store.path,job)
    context={'job':job,'database':store.path,'max_age':cfg.get('execution_max_age_seconds',cfg['max_task_age_seconds']),
        'allow_copy':bool((cfg.get('pc_activity') or {}).get('allow_authorization_copy')),
        'allow_write':bool((cfg.get('pc_activity') or {}).get('allow_authorization_write')) and job['kind']!='authorization_audit'}
    if job['stage'] in pc_jobs.POST_COMMIT or journal and journal['commit_at'] is not None:
        if not journal:return {'status':'waiting_review','text':'提交边界缺少本机预览日志；只允许复核，不会再次提交。'}
        expected=json.loads(journal['data'])
        if not expected.get('web_renewal'):return native_activity_executor.run(context,api)
        reviews=review_new(reader,expected)
        if not reviews:
            details={'submission_result':'unconfirmed'}
            try:
                window=expected['preview']['body']['activity']
                details['current_product_check']=current_product_check(api,expected['source'],window['start_time'],window['end_time'])
            except Exception:
                details['current_product_check']={'status':'unavailable','source':'current_product_api'}
            return {'status':'waiting_review','text':'新活动仍未确认；继续只读复核，不重复提交。当前商品与旧模板的差异见下方。','details':details}
        start=datetime.fromtimestamp(expected['preview']['body']['activity']['start_time'],BEIJING).strftime('%Y-%m-%d %H:%M:%S')
        end=datetime.fromtimestamp(expected['preview']['body']['activity']['end_time'],BEIJING).strftime('%Y-%m-%d %H:%M:%S')
        state='已保存，待生效' if reviews[-1]['state']=='pending' else '已生效'
        return {'status':'succeeded','text':f'新档期授权配置{state}，两轮独立复核一致；旧活动未修改。档期：{start} 至 {end}（北京时间）。',
            'details':{'state':reviews[-1]['state'],'activity_id':reviews[-1]['activity_id'],
                'products':expected['products'],'accounts':accounts},'reviews':reviews}
    all_activities=reader.read();now=time.time();current_check=None
    live=[a for a in all_activities if a.get('activity_status')==2 and int(a['start_time'])<=now<int(a['end_time'])]
    if parameters is None:
        if live:
            try:return native_activity_executor.run(context,api)
            except NeedsReview as exc:return need_input(all_activities,accounts,now,str(exc))
        return need_input(all_activities,accounts,now)
    if isinstance(parameters,dict) and parameters.get('action')=='authorize_existing':
        try:return native_activity_executor.run(context,api,parameters)
        except NeedsReview as exc:return need_input(all_activities,accounts,time.time(),str(exc))
    try:
        if not isinstance(parameters,dict) or not isinstance(parameters.get('template_id'),str):raise NeedsReview('需选择精确模板。')
        sources=[a for a in all_activities if exact_id(a['activity_id'])==parameters['template_id']]
        if len(sources)!=1:raise NeedsReview('所选旧模板未唯一读取；请重新审阅。')
        source=sources[0];start,end=validate_parameters(parameters,source,now)
        current_check=current_product_check(api,source,start,end)
        if current_check['status']!='verified':
            raise NeedsReview('当前商品可售或使用时段未全部通过核验；保留原商品和价格/库存，仅列出合法候选供选择，没有新建。')
        if not context['allow_write']:raise NeedsReview('当前为只读预览；新增写入未获许可。')
        creation_support(source)
        lookup_source=dict(source,start_time=start,end_time=end)
        _,resolved=api.read(LOOKUP_PATH,body=lookup_body(lookup_source,accounts,copy=True))
        if resolved.get('duplicate_anchor_sku_infos'):raise NeedsReview('平台提示新档期已有重叠授权；不重复创建。')
        creators=resolve_creators(resolved,accounts)
        body=creation_payload(source,accounts,creators,api.expected_root,start,end)
        conflicts=overlap_conflicts(all_activities,body)
        if conflicts:
            reviews=review_existing_window(reader,body,parameters['template_id'],parameters['fingerprint'])
            if reviews:
                state='待生效' if reviews[-1]['state']=='pending' else '已生效'
                return {'status':'succeeded','text':f'已有完全一致的新档期授权配置（{state}），已独立复核两次；未重复创建。',
                    'details':{'state':reviews[-1]['state'],'activity_id':reviews[-1]['activity_id'],
                        'mode':'already_configured','products':preview(source,accounts,'已有同档期配置')['products'],
                        'accounts':accounts},'reviews':reviews}
            raise NeedsReview('新档期已有相同账号/商品的重叠活动；需要人工取舍，不重复创建。')
        _,checked=api.read(PRECHECK_PATH,body=body);verify_precheck(checked)
        fresh_all=reader.read();fresh=[a for a in fresh_all if exact_id(a['activity_id'])==parameters['template_id']]
        if len(fresh)!=1:raise NeedsReview('预检查后旧模板未唯一读取。')
        validate_parameters(parameters,fresh[0],time.time())
        fresh_body=creation_payload(fresh[0],accounts,creators,api.expected_root,start,end)
        if fresh_body!=body or overlap_conflicts(fresh_all,body):raise NeedsReview('预检查后模板或授权发生变化；请重新审阅。')
        current_check=current_product_check(api,fresh[0],start,end)
        if current_check['status']!='verified':
            raise NeedsReview('最终闸门前当前商品供给/使用时段发生变化或未核验；没有新建。')
        # Re-run the platform check at the final boundary, not only the preview.
        _,checked=api.read(PRECHECK_PATH,body=body);verify_precheck(checked)
        validate_parameters(parameters,fresh[0],time.time())
        product_preview=preview(source,accounts,'用户明确确认的新档期')['products']
        expected={'root':api.expected_root,'accounts':accounts,'source':source,'web_renewal':True,
            'template_id':parameters['template_id'],'template_fingerprint':parameters['fingerprint'],
            'current_product_check':current_check,
            'products':product_preview,'pre_existing_ids':sorted(exact_id(a['activity_id']) for a in fresh_all),
            'preview':{'mode':'create','accounts':accounts,'body':body}}
        pc_jobs.prepare(store.path,job,expected)
        pc_jobs.submission_gate(store.path,job,context['max_age'],expected)
        try:api.submit_activity_once(body,CreationPermit(store.path,job,expected,context['max_age']))
        except SubmissionUncertain:
            return {'status':'waiting_review','text':'已进入一次提交边界，接口结果尚未确认；将只读复核，不重复提交。'}
        return {'status':'waiting_review','text':'新档期请求已发送一次；进入两轮独立结果复核。'}
    except NeedsReview as exc:
        result=need_input(all_activities,accounts,time.time(),str(exc))
        if current_check is not None:
            result['details']['current_product_check']=current_check
            if current_check['status']!='verified':result['details']['blocked']=True
            if isinstance(result['details'].get('preview'),dict):
                result['details']['preview']['current_product_check']=current_check
        return result


def run(job,cfg,store,adb,parameters=None):
    target=json.loads(job['target']);root=exact_id(target.get('root_id') or target.get('root_life_account_id') or target['merchant_id'])
    life=exact_id(target.get('merchant_id') or root)
    # Resolve dynamically so the worker's process-local gateway fence wraps
    # every submission, including this new create path.
    with native_backend.NativeRuntime(adb,android_runtime.endpoint(cfg),root,life,
            autostart=bool((cfg.get('android_device') or {}).get('autostart'))) as runtime:
        return run_api(job,cfg,store,runtime.api,parameters)
