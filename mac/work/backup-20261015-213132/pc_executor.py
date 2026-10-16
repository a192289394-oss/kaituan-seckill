"""Headless authorization controller. All business writes go through the UI and durable gate."""
import json
import time
from datetime import datetime
from urllib.parse import urlencode, urlparse, parse_qs

from pc_authorization import parse_activity_response, verify_existing_authorizations
import pc_jobs


class NeedsReview(RuntimeError):
    pass


class AuthorizationChanged(NeedsReview):
    pass


def creator_templates(activities):
    return [a for a in activities if any(int(x.get('identity_type', 0)) == 1 for x in a.get('anchor_info_list', []))]


def template_spec(source):
    products = {}
    for sku in source['sku_list']:
        grants = [g for g in sku.get('anchor_list', []) if int(g.get('identity_type', 0)) == 1]
        values = {(int(g['fixed_price']), int(g['total_quantity'])) for g in grants}
        if len(values) != 1:
            raise NeedsReview('现有达人价格/初始库存不统一，请明确沿用哪个模板；未修改。')
        price, stock = values.pop()
        if price <= 0 or stock <= 0 or price != int(sku['fixed_price']):
            raise NeedsReview('模板价格或库存不完整；未修改。')
        pid = str(sku['product_id'])
        if pid in products:
            raise NeedsReview('多规格商品需要单独核对；未修改。')
        products[pid] = {'sku_id': str(sku['sku_id']), 'price': price, 'stock': stock}
    if not products:
        raise NeedsReview('模板没有商品。')
    return products


def source_signature(source):
    return (str(source['activity_id']), int(source['start_time']), int(source['end_time']),
            source.get('sell_out_style'),
            sorted((str(a['uid']), str(a.get('douyin_id', '')), int(a.get('identity_type', 0))) for a in source['anchor_info_list']),
            sorted((str(s['sku_id']), str(s['product_id']), int(s['fixed_price']),
                    sorted((str(g['uid']), int(g['fixed_price']), int(g['total_quantity'])) for g in s['anchor_list'])) for s in source['sku_list']))


def choose_plan(activities, accounts, now):
    sources = creator_templates(activities)
    if not sources:
        raise NeedsReview('没有可沿用的生效达人秒杀模板，需要明确商品、价格、库存和时段。')
    universe = {str(s['sku_id']) for a in sources for s in a['sku_list']}
    complete = [a for a in sources if {str(s['sku_id']) for s in a['sku_list']} == universe]
    for source in complete:
        coverage = verify_existing_authorizations(source, activities, accounts, now)
        if coverage['status'] == 'already_authorized':
            return {'action': 'already_authorized', 'source': source, 'coverage': coverage}
    signatures = {}
    for source in sources:
        spec = template_spec(source)
        key = json.dumps([spec, int(source['end_time'])], sort_keys=True)
        signatures.setdefault(key, []).append(source)
    if len(signatures) != 1:
        raise NeedsReview('存在不同商品/价格/库存/截止时间的生效模板，请指定活动；未选择第一个或改价。')
    source = min(sources, key=lambda a: len(a.get('anchor_info_list', [])))
    coverage = verify_existing_authorizations(source, activities, accounts, now)
    if coverage['conflicts']:
        raise NeedsReview('已有授权存在价格、库存或时段冲突，需要确认，未自动补库存或重建。')
    missing = [a for a in accounts if coverage['missing'][a]]
    existing = {str(x.get('douyin_id')) for a in activities for x in a.get('anchor_info_list', [])}
    if any(a in existing for a in missing):
        raise NeedsReview('部分商品已有授权但覆盖不完整，需要确认，未创建重叠活动。')
    return {'action': 'authorize', 'source': source, 'missing': missing,
            'products': template_spec(source), 'coverage': coverage}


class Browser:
    def __init__(self, context, tools):
        self.context = context
        self.tools = tools
        self.root = context['urls']['root_life_account_id']
        self.group = context['urls']['groupid']
        self.js = tools['js']

    def route(self):
        url = urlparse(self.js('location.href'))
        q = parse_qs(url.query)
        root_ok = q.get('root_life_account_id') == [self.root]
        if 'root_life_account_id' not in q and getattr(self, 'bound_activity', None):
            root_ok = url.path == '/p/merchant-marketing-tools/live-seckill/edit' and q.get('id') == [self.bound_activity]
        if url.hostname != 'life.douyin.com' or q.get('groupid') != [self.group] or not root_ok:
            raise RuntimeError('PC 商家路由或登录身份尚未就绪，未修改。')

    def reopen(self):
        self.tools['goto_url'](self.context['urls']['seckill'])
        self.tools['wait_for_load']()
        time.sleep(3)
        self.route()

    def read(self, path, params, body=None):
        self.route()
        params = {**params, 'root_life_account_id': self.root}
        options = {'credentials': 'include', 'cache': 'no-store'}
        if body is not None:
            options.update(method='POST', headers={'Content-Type': 'application/json'}, body=json.dumps(body))
        raw = self.js('(async()=>{const r=await fetch(' + json.dumps(path + '?' + urlencode(params)) + ','
                      + json.dumps(options) + ');if(!r.ok)throw Error("PC_READ_HTTP");return await r.text()})()')
        result = json.loads(raw)
        if int(result.get('status_code', -1)) != 0:
            raise RuntimeError('PC 后台只读接口暂不可用，请检查登录和商家权限。')
        return raw, result

    def detail(self, aid):
        raw, _ = self.read('/life/marketing/v1/minus_activity/info', {
            'activity_id': str(aid), 'selected_account_id': '', 'discount_type': 'merchant_live_flash_promotion'})
        return parse_activity_response(raw, str(aid))

    def activities(self):
        seen, active = set(), []
        now = time.time()
        for page in range(1, 101):
            _, data = self.read('/life/marketing/v1/minus_activity/list', {}, {
                'discount_type': 'merchant_live_flash_promotion', 'selected_account_id': '',
                'pagination': {'current_page': page, 'page_size': 100}})
            pagination = data.get('pagination') or {}
            if 'has_more' not in pagination or not isinstance(data.get('activities'), list):
                raise NeedsReview('活动分页证据不完整，未修改。')
            for a in data['activities']:
                aid = str(a['activity_id'])
                if aid in seen:
                    raise NeedsReview('活动分页重复，未修改。')
                seen.add(aid)
                if int(a['activity_status']) == 2 and int(a['start_time']) <= now < int(a['end_time']):
                    active.append(self.detail(aid))
            if not pagination['has_more']:
                return active
        raise NeedsReview('活动分页超过本轮上限，未修改。')

    def verify_twice(self, source, accounts, initial=None, preserve_existing=False):
        reviews = []
        for index in range(2):
            if index == 0 and initial is not None:
                activities = initial
            else:
                self.reopen()
                activities = self.activities()
            if preserve_existing:
                fresh = [a for a in activities if str(a['activity_id']) == str(source['activity_id'])]
                if len(fresh) != 1 or not preserves_existing(source, fresh[0]):
                    return None
            result = verify_existing_authorizations(source, activities, accounts, time.time())
            if result['status'] != 'already_authorized':
                return None
            reviews.append({'at': time.time(), 'coverage': result['coverage']})
            if index == 0:
                time.sleep(2)
        return reviews


def preserves_existing(source, fresh):
    if any(int(source[k]) != int(fresh[k]) for k in ('start_time', 'end_time')):
        return False
    if not {str(a['uid']) for a in source['anchor_info_list']} <= {str(a['uid']) for a in fresh['anchor_info_list']}:
        return False
    rows = {str(s['sku_id']): s for s in fresh['sku_list']}
    for sku in source['sku_list']:
        current = rows.get(str(sku['sku_id']))
        if not current or str(current['product_id']) != str(sku['product_id']):
            return False
        old = {(str(g['uid']), int(g['fixed_price']), int(g['total_quantity'])) for g in sku['anchor_list']}
        new = {(str(g['uid']), int(g['fixed_price']), int(g['total_quantity'])) for g in current['anchor_list']}
        if not old <= new:
            return False
    return True


def summary(accounts, reviews, changed=False):
    lines = [('授权结果已生效并复核两次；未重复提交。' if changed else '已有有效授权，已复核两次；未重复添加或复制。')]
    for account in accounts:
        grants = list(reviews[-1]['coverage'][account].values())
        end = datetime.fromtimestamp(min(g['end_time'] for g in grants)).strftime('%Y-%m-%d %H:%M:%S')
        lines.append(f'{account}：{len(grants)}个商品，有效至{end}（北京时间），逐商品剩余库存最低{min(g["remaining"] for g in grants)}。')
    return '\n'.join(lines)


def run(context, tools):
    job = context['job']
    accounts = json.loads(job['accounts'])
    browser = Browser(context, tools)
    browser.reopen()
    journal = pc_jobs.load_journal(context['database'], job)
    review_only = job['stage'] == 'verifying' or (journal and journal['commit_at'] is not None)
    activities = browser.activities()
    if review_only:
        if not journal:
            return {'status': 'needs_review', 'text': '提交后缺少持久化预览，不能安全重放；需要人工核对。'}
        plan = json.loads(journal['data'])
        reviews = browser.verify_twice(plan['source'], accounts, activities, preserve_existing=True)
        if not reviews:
            return {'status': 'waiting_review', 'text': '提交结果尚未确认，将只读复核，不会再次提交。'}
        return {'status': 'succeeded', 'text': summary(accounts, reviews, changed=True), 'reviews': reviews}
    plan = choose_plan(activities, accounts, time.time())
    if plan['action'] == 'already_authorized':
        reviews = browser.verify_twice(plan['source'], accounts, activities)
        if not reviews:
            return {'status': 'queued', 'text': '两轮结果暂不一致，将重新只读核对；未提交。'}
        return {'status': 'succeeded', 'text': summary(accounts, reviews), 'reviews': reviews}
    if not context.get('allow_write'):
        return {'status': 'needs_review', 'text': '已确认缺少授权，但本机新增授权写入尚未启用；未提交。'}
    from pc_ui_authorization import prepare_authorization
    try:
        preview = prepare_authorization(browser, plan)
    except AuthorizationChanged:
        return {'status': 'queued', 'text': '平台提示已存在授权；丢弃未保存表单，重新跨活动只读核对。'}
    except NeedsReview:
        raise
    except Exception as exc:
        raise RuntimeError('未保存表单尚未就绪，未提交：' + type(exc).__name__ + '；稍后重新加载核验。') from exc
    # Recheck all activities and source after preparing the unsaved UI. No retry if committed.
    current = browser.activities()
    current_plan = choose_plan(current, accounts, time.time())
    if current_plan['action'] != 'authorize' or current_plan['missing'] != plan['missing']:
        return {'status': 'queued', 'text': '准备期间授权已变化，丢弃未保存表单，重新只读核对。'}
    if current_plan['products'] != plan['products'] or source_signature(current_plan['source']) != source_signature(plan['source']):
        return {'status': 'queued', 'text': '准备期间模板已变化，未提交；将重新读取当前模板。'}
    expected = {'root': browser.root, 'accounts': accounts, 'source': plan['source'], 'preview': preview}
    pc_jobs.prepare(context['database'], job, expected)
    pc_jobs.submission_gate(context['database'], job, context['max_age'], expected)
    # A timeout from this point is always review-only, even if the click never reached Chrome.
    from pc_ui_authorization import publish_once
    publish_once(browser, preview)
    return {'status': 'waiting_review', 'text': '已触发一次提交，进入独立结果复核；不会重试提交。'}
