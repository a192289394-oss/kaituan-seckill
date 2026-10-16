"""API-only counterpart of the existing durable PC authorization controller."""
from copy import deepcopy
import hashlib
import json
import time
import pc_jobs
from pc_authorization import parse_activity_response,verify_existing_authorizations
from pc_executor import (NeedsReview,choose_plan,source_signature,preserves_existing,summary,template_spec,filter_activities_for_target)
from native_activity import (exact_id,lookup_body,resolve_creators,authorization_payload,
    verify_precheck,LOOKUP_PATH,PRECHECK_PATH)
from native_commit import ActivityPermit
from native_webview_api import SubmissionUncertain


CONFIRM_FIELDS={'action','confirmed','activity_id','fingerprint'}
VOLATILE={'create_time','update_time','creator_account_name','sku_count','anchor_count',
    'activity_discount_unit_list','intelligent_creation_display_plan_list',
    'left_quantity','left_quantity_realtime','left_stock','sold_count','sold_quantity',
    'coupon_order_cnt','coupon_sell_cnt','coupon_order_amount','stock_insufficient_status',
    # Product-level live inventory counters (change with every sale).
    'avail_qty','sku_avail_qty'}


def _stable(value):
    """Canonicalise a readback without turning changing counters into consent."""
    if isinstance(value,dict):
        return {key:_stable(item) for key,item in value.items() if key not in VOLATILE}
    if isinstance(value,list):
        rows=[_stable(item) for item in value]
        if rows and all(isinstance(item,dict) for item in rows):
            rows.sort(key=lambda item:json.dumps(item,sort_keys=True,ensure_ascii=False,allow_nan=False))
        return rows
    return value


def authorization_fingerprint(source,requested,missing):
    """Bind consent to the stable activity snapshot and exact account delta."""
    snapshot=deepcopy(source)
    # These are signed display URLs. Their identifiers and all business fields
    # remain covered, while a CDN signature refresh does not invalidate consent.
    for anchor in snapshot.get('anchor_info_list',[]):
        avatar=anchor.get('avatar')
        if isinstance(avatar,dict):avatar.pop('url_list',None)
    for sku in snapshot.get('sku_list',[]):
        info=sku.get('product_info')
        if isinstance(info,dict):info.pop('image_list',None)
    frozen={'source':_stable(snapshot),'requested_accounts':list(requested),
        'missing_accounts':list(missing)}
    return hashlib.sha256(json.dumps(frozen,sort_keys=True,ensure_ascii=False,
        allow_nan=False,separators=(',',':')).encode()).hexdigest()


def authorization_preview(plan,accounts,allow_copy):
    source=plan['source'];missing=list(plan['missing']);products=[]
    for sku in source['sku_list']:
        product_id=exact_id(sku['product_id']);spec=plan['products'][product_id]
        info=sku.get('product_info') or {}
        products.append({'id':product_id,'sku_id':exact_id(sku['sku_id']),
            'name':info.get('product_name') or sku.get('product_name') or '商品 '+product_id,
            'price_cents':int(spec['price']),'stock_per_creator':int(spec['stock'])})
    copy_required=len(source.get('anchor_info_list') or [])+len(missing)>60
    activity_name=source.get('activity_name') if isinstance(source.get('activity_name'),str) else ''
    result={'mode':'authorize_existing','activity_id':exact_id(source['activity_id']),
        'activity_name':activity_name,'name':activity_name,
        'fingerprint':authorization_fingerprint(source,accounts,missing),
        # ``accounts`` is retained for the shared preview component; the two
        # explicit fields make requested scope and actual delta unambiguous.
        'accounts':list(accounts),'requested_accounts':list(accounts),
        'missing_accounts':missing,'products':products,
        'end_time':int(source['end_time']),'timezone':'Asia/Shanghai',
        'copy_required':copy_required}
    if copy_required:
        result.update(blocked=True,
            reason=('当前活动达人名额不足。网页确认仅允许补充当前活动，不会把本次确认转换成'
                '新建独立活动；未提交。'))
    return result




def min_stock(reviews, source=None):
    """Min remaining across products; fall back to stock_per_creator; else None."""
    remainings=[]
    if reviews:
        coverage=(reviews[-1] or {}).get('coverage') or {}
        for grants in coverage.values():
            for grant in (grants or {}).values():
                if isinstance(grant.get('remaining'), int):
                    remainings.append(grant['remaining'])
    if remainings:
        return min(remainings)
    stocks=[]
    for sku in (source or {}).get('sku_list') or []:
        for grant in sku.get('anchor_list') or []:
            if int(grant.get('identity_type', 0))==1 and isinstance(grant.get('total_quantity'), int):
                stocks.append(int(grant['total_quantity']))
                break
        else:
            if isinstance(sku.get('total_quantity'), int):
                stocks.append(int(sku['total_quantity']))
    return min(stocks) if stocks else None


def seckill_card(source, accounts, reviews):
    activity_name=source.get('activity_name') if isinstance(source.get('activity_name'),str) else ''
    end_time=int(source['end_time']) if source and source.get('end_time') is not None else None
    return {'kind':'seckill',
        'activity_id':exact_id(source['activity_id']) if source else '',
        'activity_name':activity_name,'name':activity_name,
        'accounts':list(accounts),
        'end_time':end_time,
        'min_stock':min_stock(reviews, source)}


def with_seckill_card(result, source, accounts, reviews):
    details=dict(result.get('details') or {})
    details['card']=seckill_card(source, accounts, reviews)
    out=dict(result); out['details']=details; out['reviews']=reviews
    return out

def select_activity_result(sources, activities, accounts, allow_copy, now, hotel_name=None):
    """Multi live templates with different terms: ship candidates, no default pick."""
    n = len(sources)
    hotel_bit = f'「{hotel_name}」' if hotel_name else '本店'
    reason = (f'{hotel_bit}有 {n} 个生效秒杀、商品/价格/库存/截止时间不同，请选择要加号的活动；'
              '未默认选第一个，也未把其他门店活动当作候选。')
    candidates = []
    for source in sources:
        try:
            products = template_spec(source)
        except NeedsReview:
            continue
        coverage = verify_existing_authorizations(source, activities, accounts, now)
        missing = [a for a in accounts if coverage['missing'][a]]
        plan = {'source': source, 'missing': missing, 'products': products, 'coverage': coverage}
        candidates.append(authorization_preview(plan, accounts, allow_copy))
    return {'status': 'needs_input', 'text': reason,
            'details': {'reason': reason, 'candidates': candidates, 'parameters_applied': False,
                        'candidate_kind': 'live_activity', 'match': 'multi',
                        'hotel': hotel_name}}

def preview_result(preview,text=None):
    text=text or ('当前生效秒杀缺少完整授权。商品、价格、每达人库存、截止时间和待补账号已冻结；'
        '请审阅后在同一任务二次确认。')
    if preview.get('blocked'):text=preview['reason']
    details={'preview':preview}
    if preview.get('blocked'):details.update(blocked=True,reason=preview['reason'])
    return {'status':'needs_input','text':text,'details':details}


def comparable_payload(preview):
    """Signed avatar CDN URLs rotate on every read; they are display-only and
    must not make two otherwise identical authorization payloads differ."""
    from copy import deepcopy
    p=deepcopy(preview)
    for a in ((p.get('body') or {}).get('activity') or {}).get('anchor_info_list') or []:
        if isinstance(a,dict):a.pop('avatar',None)
    for sku in ((p.get('body') or {}).get('activity') or {}).get('sku_list') or []:
        # Display/product readback and live sold counters, not authorization terms.
        if isinstance(sku,dict):sku.pop('product_info',None);sku.pop('total_left_stock',None)
    return p


def valid_confirmation(parameters):
    return (isinstance(parameters,dict) and set(parameters)==CONFIRM_FIELDS
        and parameters.get('action')=='authorize_existing'
        and parameters.get('confirmed') is True
        and isinstance(parameters.get('activity_id'),str)
        and isinstance(parameters.get('fingerprint'),str)
        and len(parameters['fingerprint'])==64
        and all(c in '0123456789abcdef' for c in parameters['fingerprint']))


class Activities:
    def __init__(self,api):self.api=api

    def read(self):
        seen=set();active=[];now=time.time()
        for page in range(1,101):
            _,data=self.api.read('/life/marketing/v1/minus_activity/list',body={
                'discount_type':'merchant_live_flash_promotion','selected_account_id':'',
                'pagination':{'current_page':page,'page_size':100}})
            p=data.get('pagination')or{};rows=data.get('activities')
            if not isinstance(rows,list) or not isinstance(p.get('has_more'),bool):
                raise NeedsReview('活动目录分页不完整，尚未提交')
            for a in rows:
                aid=str(a['activity_id'])
                if aid in seen:raise NeedsReview('活动目录分页重复，尚未提交')
                seen.add(aid)
                if int(a['activity_status'])==2 and int(a['start_time'])<=now<int(a['end_time']):
                    raw,_=self.api.read('/life/marketing/v1/minus_activity/info',params={
                        'activity_id':aid,'selected_account_id':'','discount_type':'merchant_live_flash_promotion'})
                    active.append(parse_activity_response(raw,aid))
            if p['has_more'] is False:return active
        raise NeedsReview('活动目录超过分页上限，尚未提交')

    def verify_twice(self,source,accounts,preserve=False):
        results=[]
        for _ in range(2):
            current=self.read()
            if preserve:
                originals=[a for a in current if str(a['activity_id'])==str(source['activity_id'])]
                if len(originals)!=1 or not preserves_existing(source,originals[0]):return None
            c=verify_existing_authorizations(source,current,accounts,time.time())
            if c['status']!='already_authorized':return None
            results.append(c)
        return results


def run(context,api,parameters=None):
    job=context['job'];accounts=json.loads(job['accounts']);reader=Activities(api)
    journal=pc_jobs.load_journal(context['database'],job)
    review_only=job['stage'] in pc_jobs.POST_COMMIT or (journal and journal['commit_at'] is not None)
    if review_only:
        if not journal:return {'status':'needs_review','text':'提交后缺少持久化预览，只允许人工核对，不重放。'}
        reviews=reader.verify_twice(json.loads(journal['data'])['source'],accounts,preserve=True)
        if not reviews:return {'status':'waiting_review','text':'提交结果尚未确认，继续只读复核，不会重复提交。'}
        source=json.loads(journal['data'])['source']
        return with_seckill_card({'status':'succeeded','text':summary(accounts,reviews,changed=True)},source,accounts,reviews)
    prefer=None
    if isinstance(parameters,dict) and isinstance(parameters.get('activity_id'),str):
        prefer=parameters['activity_id']
        if set(parameters)=={'activity_id'}:parameters=None  # selection only, not consent
    target=job.get('target')
    if isinstance(target,str):
        target=json.loads(target)
    if not isinstance(target,dict):
        target={}
    hotel_name=target.get('name') if isinstance(target.get('name'),str) else None
    activities=reader.read()
    scoped,scope_mode=filter_activities_for_target(activities,target)
    if scope_mode=='filtered':
        activities=scoped
        if prefer is not None and not any(str(a.get('activity_id'))==str(prefer) for a in activities):
            return {'status':'needs_input',
                'text':f'所选活动不属于当前酒店{"「"+hotel_name+"」" if hotel_name else ""}；未提交，请重新选择本店活动。',
                'details':{'reason':'activity_not_for_hotel','match':'none','candidates':[],
                    'candidate_kind':'live_activity','hotel':hotel_name,'parameters_applied':False}}
        if not activities:
            return {'status':'needs_input',
                'text':(f'当前本店「{hotel_name}」' if hotel_name else '当前账号下')
                    + '没有生效中的秒杀活动；请先到抖音来客自行创建秒杀活动后再来加号。本工具只往已有活动里加号，不会参考旧活动新建。未提交。',
                'details':{'reason':'no_live_activity_refuse_create','match':'none','candidates':[],
                    'candidate_kind':'none','blocked':True,'hotel':hotel_name,'parameters_applied':False}}
    plan=choose_plan(activities,accounts,time.time(),prefer)
    if plan.get('action')=='select_activity':
        return select_activity_result(plan['sources'],activities,accounts,
            bool(context.get('allow_copy')),time.time(),hotel_name=hotel_name)
    if plan['action']=='already_authorized':
        reviews=reader.verify_twice(plan['source'],accounts)
        if not reviews:return {'status':'queued','text':'已有授权两轮结果暂不一致，重新只读核对；未提交。'}
        return with_seckill_card({'status':'succeeded','text':summary(accounts,reviews)},plan['source'],accounts,reviews)
    frozen=authorization_preview(plan,accounts,bool(context.get('allow_copy')))
    # Discovery is always read-only, even when the process is configured for
    # writes. A later same-task confirmation must bind to this exact snapshot.
    if parameters is None:
        # Existing live activity + task-level allow_write: no separate operator
        # confirmation. Bind to the frozen snapshot read just now; every later
        # gate (precheck, fresh re-read, once-only journal, double review) stays.
        if context.get('allow_write') and not frozen.get('blocked') and frozen.get('activity_id') and frozen.get('fingerprint'):
            parameters={'action':'authorize_existing','confirmed':True,
                'activity_id':frozen['activity_id'],'fingerprint':frozen['fingerprint']}
        else:return preview_result(frozen)
    if not valid_confirmation(parameters):
        return preview_result(frozen,'确认参数不完整或不是当前活动授权确认；未提交，请重新审阅。')
    if (parameters['activity_id']!=frozen['activity_id']
            or parameters['fingerprint']!=frozen['fingerprint']):
        return preview_result(frozen,'当前活动、已有授权或待补账号已变化；旧确认已作废，未提交。')
    if frozen.get('blocked'):return preview_result(frozen)
    if not context.get('allow_write'):
        return {'status':'needs_review','text':'同任务确认已读取，但本机写入闸门未开启；未提交。',
            'details':{'preview':frozen}}
    copy=len(plan['source']['anchor_info_list'])+len(plan['missing'])>60
    if copy and not context.get('allow_copy'):
        return preview_result(frozen)
    _,resolved=api.read(LOOKUP_PATH,body=lookup_body(plan['source'],plan['missing'],copy=copy))
    if resolved.get('duplicate_anchor_sku_infos'):
        return {'status':'queued','text':'平台提示并发已有授权，重新跨活动核对；未提交。'}
    creators=resolve_creators(resolved,plan['missing'])
    preview=authorization_payload(plan['source'],plan['missing'],creators,api.expected_root)
    _,precheck=api.read(PRECHECK_PATH,body=preview['body'])
    verify_precheck(precheck)
    fresh_activities=reader.read()
    if scope_mode=='filtered':
        fresh_activities,_=filter_activities_for_target(fresh_activities,target)
    fresh=choose_plan(fresh_activities,accounts,time.time(),prefer)
    if fresh.get('action')=='select_activity':
        return {'status':'queued','text':'平台预检查期间出现多个不同生效模板，重新读取；未提交。'}
    if (fresh['action']!='authorize' or fresh['missing']!=plan['missing']
            or fresh['products']!=plan['products'] or source_signature(fresh['source'])!=source_signature(plan['source'])):
        return {'status':'queued','text':'平台预检查期间模板或授权变化，重新读取；未提交。'}
    fresh_frozen=authorization_preview(fresh,accounts,bool(context.get('allow_copy')))
    if fresh_frozen!=frozen:
        return {'status':'queued','text':'平台预检查后冻结预览已变化，旧确认失效；重新读取，未提交。'}
    fresh_preview=authorization_payload(fresh['source'],fresh['missing'],creators,api.expected_root)
    if comparable_payload(fresh_preview)!=comparable_payload(preview):
        return {'status':'queued','text':'预检查后完整授权参数已变化，重新读取；未提交。'}
    expected={'root':api.expected_root,'accounts':accounts,'source':plan['source'],
        'authorization_preview':frozen,'preview':preview}
    pc_jobs.prepare(context['database'],job,expected)
    pc_jobs.submission_gate(context['database'],job,context['max_age'],expected)
    try:api.submit_activity_once(preview['body'],ActivityPermit(context['database'],job,expected,context['max_age']))
    except SubmissionUncertain:
        return {'status':'waiting_review','text':'提交响应尚未确认，继续只读复核，不会重复提交。'}
    return {'status':'waiting_review','text':'已发送一次原生接口提交，进入独立结果复核；不会重复发送。'}
