"""API-only counterpart of the existing durable PC authorization controller."""
from copy import deepcopy
import hashlib
import json
import time
import pc_jobs
from pc_authorization import parse_activity_response,verify_existing_authorizations
from pc_executor import (NeedsReview,choose_plan,source_signature,preserves_existing,summary)
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
    result={'mode':'authorize_existing','activity_id':exact_id(source['activity_id']),
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
        return {'status':'succeeded','text':summary(accounts,reviews,changed=True),'reviews':reviews}
    plan=choose_plan(reader.read(),accounts,time.time())
    if plan['action']=='already_authorized':
        reviews=reader.verify_twice(plan['source'],accounts)
        if not reviews:return {'status':'queued','text':'已有授权两轮结果暂不一致，重新只读核对；未提交。'}
        return {'status':'succeeded','text':summary(accounts,reviews),'reviews':reviews}
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
    fresh=choose_plan(reader.read(),accounts,time.time())
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
