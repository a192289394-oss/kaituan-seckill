"""Verified-form adapter: append or copy without changing the original grants.

Unsupported controls stop before the durable submit boundary; never guess settings.
"""
import json
import re
import time
from decimal import Decimal
from urllib.parse import urlencode, urlparse, parse_qs

from pc_executor import NeedsReview, AuthorizationChanged
import pc_jobs

# Shortest matching form block prevents hidden selection modals/other tables mixing in.
DOM = r'''
const visible=e=>{for(let p=e;p&&p.nodeType===1;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||s.opacity==='0')return false}return !!(e.offsetWidth||e.offsetHeight)};
const area=kind=>{
 const all=[...document.querySelectorAll('div')].filter(e=>visible(e)&&
   (kind==='products' ? e.innerText.includes('选择商品 (')&&e.innerText.includes('商品名称/ID') :
    e.innerText.trim().startsWith('授权达人')&&e.innerText.includes('批量录入主播抖音号')&&e.innerText.includes('选择主播 (')));
 all.sort((a,b)=>a.innerText.length-b.innerText.length);
 if(!all.length)throw Error('form_block_missing_'+kind);return all[0];
};
'''


def script(browser, body):
    return browser.js('(()=>{' + DOM + body + '})()')


def click_expression(browser, expression):
    rect = script(browser, 'const e=' + expression + ''';if(!e||!visible(e)||e.disabled)throw Error('control_missing');
        e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();const x=r.x+r.width/2,y=r.y+r.height/2;
        if(!e.contains(document.elementFromPoint(x,y)))throw Error('control_obscured');return {x,y};''')
    browser.tools['click_at_xy'](rect['x'], rect['y'])


def pages(browser, kind):
    values = {}
    for page in range(1, 11):
        page_expr = "[...area(" + json.dumps(kind) + ").querySelectorAll('*')].filter(e=>visible(e)&&!e.children.length&&e.textContent.trim()===" + json.dumps(str(page)) + ')'
        if page > 1:
            count = script(browser, 'return ' + page_expr + '.length;')
            if count == 0:
                break
            if count != 1:
                raise NeedsReview('表格分页不唯一，未修改。')
            click_expression(browser, page_expr + '[0]')
            time.sleep(.35)
        data = script(browser, 'return [...area(' + json.dumps(kind) + ''').querySelectorAll('tr')].filter(visible).map(r=>({text:r.innerText,
            inputs:[...r.querySelectorAll('input')].map(x=>x.value)}));''')
        for row in data:
            match = re.search(r'ID:\s*(\d+)' if kind == 'products' else r'抖音号[：:]\s*([^\s]+)', row['text'])
            if match:
                key = match.group(1)
                if key in values and values[key] != row['inputs']:
                    raise NeedsReview('表格分页内容不一致，未提交。')
                values[key] = row['inputs']
    # Return to page one so later paginated checks never skip it.
    first = "[...area(" + json.dumps(kind) + ").querySelectorAll('*')].filter(e=>visible(e)&&!e.children.length&&e.textContent.trim()==='1')"
    if script(browser, 'return ' + first + '.length;') == 1:
        click_expression(browser, first + '[0]')
        time.sleep(.2)
    return values


def validate_products(browser, expected):
    actual = pages(browser, 'products')
    if set(actual) != set(expected):
        raise NeedsReview('表单商品集合与模板不一致，未提交。')
    for pid, inputs in actual.items():
        if len(inputs) not in (2, 3):
            raise NeedsReview('商品价格库存控件不完整，未提交。')
        if (Decimal(inputs[0]) * 100 != expected[pid]['price'] or Decimal(inputs[1]) != expected[pid]['stock']
                or (len(inputs) == 3 and inputs[2] not in ('', '0'))):
            raise NeedsReview('表单价格/单主播库存/追加库存与模板不一致，未提交。')


def date_values(browser):
    return browser.js("[...document.querySelectorAll('.byted-date-time-range-picker-value')].map(e=>e.textContent.trim())")


def copy_dates(browser, source):
    from datetime import datetime
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = max(datetime.fromtimestamp(int(source['start_time'])), today)
    end = datetime.fromtimestamp(int(source['end_time']))
    if start.strftime('%H:%M:%S') != '00:00:00' or end.strftime('%H:%M:%S') != '23:59:59':
        raise NeedsReview('复制模板包含非整日时段，需要单独核对日期控件，未提交。')
    script(browser, "const e=document.querySelector('.byted-date-time-range-picker-item');if(!e||!visible(e)||e.disabled)throw Error('date_control_missing');e.click();return true;")
    time.sleep(.4)
    for date in (start, end):
        month = f'{date.year}年{date.month}月'
        expression = "(()=>{const panels=[...document.querySelectorAll('.byted-date-view')].filter(e=>visible(e)&&e.innerText.startsWith("+json.dumps(month)+"));if(panels.length!==1)throw Error('calendar_month_not_visible');const days=[...panels[0].querySelectorAll('.byted-date-item.byted-date-date:not(.byted-date-grid-prev):not(.byted-date-grid-next)')].filter(e=>e.innerText==="+json.dumps(str(date.day))+"&&!e.className.includes('disabled'));if(days.length!==1)throw Error('calendar_day_not_unique');return days[0]})()"
        script(browser, 'const e='+expression+";if(!visible(e))throw Error('date_hidden');e.click();return true;")
        time.sleep(.3)
    script(browser, "const e=document.querySelector('.byted-date-time-range-picker-confirm');if(!e||!visible(e)||e.disabled)throw Error('date_confirm_not_ready');e.click();return true;")
    time.sleep(.3)
    expected = [d.strftime('%Y/%m/%d %H:%M:%S') for d in (start, end)]
    if date_values(browser) != expected:
        raise NeedsReview('复制活动日期回读不符，未提交。')
    return expected


def prepare_authorization(browser, plan, force_copy=False):
    source = plan['source']
    expected_actors = {str(a['douyin_id']) for a in source['anchor_info_list'] if int(a.get('identity_type', 0)) == 1}
    if not expected_actors:
        raise NeedsReview('缺少现有达人模板。')
    browser.bound_activity = str(source['activity_id'])
    query = {'groupid': browser.group, 'root_life_account_id': browser.root, 'life_biz_view_id': '22',
             'enter_from': 'timelimited_spike_page', 'id': browser.bound_activity, 'mode': 'edit'}
    browser.tools['goto_url']('https://life.douyin.com/p/merchant-marketing-tools/live-seckill/edit?' + urlencode(query))
    browser.tools['wait_for_load']()
    time.sleep(5)
    browser.route()
    cap = script(browser, "return area('creators').innerText.match(/选择主播\\s*\\((\\d+)\\/(\\d+)\\)/)?.slice(1);")
    if not cap or int(cap[0]) != len(expected_actors):
        raise NeedsReview('主播数量与模板不符，未提交。')
    copying = force_copy or len(expected_actors) + len(plan['missing']) > int(cap[1])
    if copying and not browser.context.get('allow_copy'):
        raise NeedsReview('现有活动名额不足且未获复制授权；未删除原主播或发布副本。')
    if set(pages(browser, 'creators')) != expected_actors:
        raise NeedsReview('原主播列表与模板不符，未提交。')
    validate_products(browser, plan['products'])
    before_dates = date_values(browser)
    from datetime import datetime
    expected_dates = [datetime.fromtimestamp(int(source[k])).strftime('%Y/%m/%d %H:%M:%S') for k in ('start_time', 'end_time')]
    if before_dates != expected_dates:
        raise NeedsReview('活动日期与模板不符，未提交。')
    if copying:
        query['mode'] = 'copy'
        browser.tools['goto_url']('https://life.douyin.com/p/merchant-marketing-tools/live-seckill/edit?' + urlencode(query))
        browser.tools['wait_for_load']()
        time.sleep(4)
        browser.route()
        # Only the unsaved copy is edited. The source activity is never pruned.
        official = "[...document.querySelectorAll('label')].filter(e=>visible(e)&&e.innerText.trim()==='授权商家/职人号/老板号')"
        checked = script(browser, 'const labels='+official+';return labels.length===1 ? !!labels[0].querySelector("input")?.checked : null;')
        if checked is None:
            raise NeedsReview('未能核对副本商家号渠道，未提交。')
        if checked:
            click_expression(browser, official+'[0]')
            time.sleep(.3)
        for _ in range(45):
            remaining = script(browser, "return area('creators').innerText.match(/选择主播\\s*\\((\\d+)\\/(\\d+)\\)/)?.slice(1);")
            if not remaining:
                raise NeedsReview('副本主播数量无法核对，未提交。')
            if int(remaining[0]) == 0:
                break
            click_expression(browser, "[...area('creators').querySelectorAll('button,a')].find(e=>e.innerText.trim()==='移除')")
            time.sleep(.15)
        else:
            raise NeedsReview('副本继承主播未清理完整，未提交。')
        if len(plan['missing']) > int(remaining[1]):
            raise NeedsReview('请求主播超过单活动容量，需要拆分配置，未提交。')
        expected_actors = set()
        before_dates = copy_dates(browser, source)
        validate_products(browser, plan['products'])
    click_expression(browser, "[...area('creators').querySelectorAll('button')].find(e=>e.innerText.trim()==='批量录入主播抖音号')")
    time.sleep(.4)
    dialog = r'''(()=>{const t=[...document.querySelectorAll('textarea')].filter(visible);if(t.length!==1)throw Error('batch_textarea_not_unique');
      for(let p=t[0].parentElement;p;p=p.parentElement){const b=[...p.querySelectorAll('button')].filter(e=>visible(e)&&e.innerText.trim()==='确定');
        if(p.innerText.includes('批量录入主播抖音号')&&b.length===1)return {textarea:t[0],button:b[0]}}throw Error('batch_dialog_missing')})()'''
    click_expression(browser, dialog + '.textarea')
    browser.tools['type_text']('\n'.join(plan['missing']))
    entered = script(browser, 'return ' + dialog + '.textarea.value;')
    if entered.splitlines() != plan['missing']:
        raise NeedsReview('批量账号输入与指令不符，未提交。')
    click_expression(browser, dialog + '.button')
    expected_after = expected_actors | set(plan['missing'])
    for _ in range(20):
        time.sleep(.5)
        body = browser.js('document.body.innerText')
        if '存在秒杀活动的已选商品' in body:
            raise AuthorizationChanged('平台提示已有重叠授权，需要重新只读查重。')
        if '全部录入失败' in body:
            raise NeedsReview('账号录入失败，请核对抖音号；未提交。')
        count = script(browser, "return area('creators').innerText.match(/选择主播\\s*\\((\\d+)\\//)?.[1];")
        if count is not None and int(count) == len(expected_after):
            break
    if set(pages(browser, 'creators')) != expected_after:
        raise NeedsReview('批量账号没有完整匹配到授权列表，未提交。')
    validate_products(browser, plan['products'])
    if date_values(browser) != before_dates:
        raise NeedsReview('准备过程中活动日期发生变化，未提交。')
    total = len(expected_after) + (0 if copying else sum(int(a.get('identity_type', 0)) != 1 for a in source['anchor_info_list']))
    totals = re.findall(r'主播数[：:]\s*(\d+)个', browser.js('document.body.innerText'))
    if totals != [str(total)]:
        raise NeedsReview('实际投放主播总数与预览不一致，未提交。')
    return {'mode': 'copy' if copying else 'edit', 'activity_id': str(source['activity_id']), 'creators': sorted(expected_after),
            'products': plan['products'], 'dates': before_dates, 'total_anchors': total}


def publish_once(browser, preview):
    context = browser.context
    journal = pc_jobs.load_journal(context['database'], context['job'])
    if not journal or journal['commit_at'] is None or json.loads(journal['data'])['preview'] != preview:
        raise NeedsReview('没有匹配的持久化提交闸门，拒绝发布。')
    with pc_jobs.connection(context['database']) as db:
        db.execute('BEGIN IMMEDIATE')
        changed = db.execute("UPDATE activity_jobs SET stage='publishing',updated=? WHERE id=? AND status='running' AND stage='submitting' AND created=?",
                             (time.time(),context['job']['id'],context['job']['created'])).rowcount
        if changed != 1:
            raise NeedsReview('提交作业已变化或发布调用已经发生，拒绝重复发布。')
    browser.route()
    q = parse_qs(urlparse(browser.js('location.href')).query)
    if q.get('id') != [preview['activity_id']] or q.get('mode') != [preview['mode']]:
        raise NeedsReview('提交页与预览不一致，停止；需只读复核。')
    # Final UI check is conservative: gate is already committed, failures never re-click.
    if set(pages(browser, 'creators')) != set(preview['creators']):
        raise NeedsReview('最终主播列表变化，停止；需只读复核。')
    validate_products(browser, preview['products'])
    if date_values(browser) != preview['dates']:
        raise NeedsReview('最终时段变化，停止；需只读复核。')
    if re.findall(r'主播数[：:]\s*(\d+)个', browser.js('document.body.innerText')) != [str(preview['total_anchors'])]:
        raise NeedsReview('最终投放主播数变化，停止；需只读复核。')
    expression = "[...document.querySelectorAll('button')].filter(e=>visible(e)&&e.innerText.trim()==='提交')"
    if script(browser, 'return ' + expression + '.length;') != 1:
        raise NeedsReview('提交按钮不唯一，停止；需只读复核。')
    click_expression(browser, expression + '[0]')
    for _ in range(20):
        time.sleep(1)
        if urlparse(browser.js('location.href')).path.endswith('/live-seckill/list'):
            break
        if browser.js("document.body.innerText.includes('提交成功')"):
            break
