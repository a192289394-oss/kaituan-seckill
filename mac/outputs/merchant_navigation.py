"""Text-only native navigation. No plan submission and no screenshots."""
import logging
import re
import time
import xml.etree.ElementTree as ET
from message_intent import name_key, resolve_name
from android_runtime import swipe_reference

MERCHANT = 'com.bytedance.ls.merchant'
CRM = 'com.bytedance.lifeservice.crm'
LOG = logging.getLogger('kaituan.navigation')
COOP_LIST = 'merchant-infinite-scroll-container'


def root(d):
    return ET.fromstring(d.dump_hierarchy())


def texts(d):
    return [n.get('text') for n in root(d).iter('node')
            if n.get('package') in (MERCHANT, CRM) and n.get('text')]


def dismiss_usage_survey(d, ts):
    """Dismiss the observed optional survey, never business confirmation dialogs."""
    if '欢迎使用管理版专属视图' in ts and '立即体验' in ts:
        d(text='立即体验').click(timeout=3)
        return True
    for rid,label in (('tv_guide_next_btn','下一步'),('guide_order_next_btn','完成')):
        if label in ts and d(resourceId=MERCHANT+':id/'+rid).exists:
            d(resourceId=MERCHANT+':id/'+rid).click(timeout=3)
            return True
    if ('抖音来客使用评价' in ts
            and any('使用体验做出评价' in text for text in ts)):
        d.press('back')
        return True
    return False


def wait(d, predicate, timeout=20, label='商家切换页面'):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        ts = texts(d)
        if dismiss_usage_survey(d, ts):
            time.sleep(.7)
            continue
        if any('暂无网络' in t or '无法连接到网络' in t for t in ts):
            raise RuntimeError('手机业务页面无法联网')
        if any('网络接口异常' in t for t in ts):
            raise RuntimeError('手机业务页面接口暂时异常，请刷新重试')
        time.sleep(.7)
    raise RuntimeError(label + '未达到预期状态，未提交')


def tap(d, n):
    b = list(map(int, re.findall(r'\d+', n.get('bounds', ''))))
    w, h = d.window_size()
    if len(b) != 4 or not (0 <= b[0] < b[2] <= w and 0 <= b[1] < b[3] <= h):
        raise RuntimeError('目标控件正在移动或不在屏幕内，未点击')
    d.click((b[0]+b[2])//2, (b[1]+b[3])//2)
    time.sleep(1.2)


def account_rows(r):
    parents = {c: p for p in r.iter() for c in p}
    out = []
    for n in r.iter('node'):
        if n.get('resource-id') == MERCHANT+':id/tv_merchant_account_group_name':
            p=parents.get(n)
            while p is not None:
                if p.get('resource-id') == MERCHANT+':id/ll_group_account_item':
                    out.append((n.get('text'),{'switch_account':p}));break
                p=parents.get(p)
        if n.get('resource-id') != MERCHANT + ':id/account_name':
            continue
        p = n
        while p in parents:
            p = parents[p]
            nodes = list(p.iter('node'))
            if sum(x.get('resource-id') == MERCHANT + ':id/account_name' for x in nodes) != 1:
                break
            actions = {x.get('resource-id', '').split('/')[-1]: x for x in nodes}
            if 'switch_account' in actions or 'show_on_homepage' in actions:
                out.append((n.get('text'), actions))
                break
    return out


def current_account(ts):
    # Other saved merchants also appear on the homepage; only the Current card counts.
    accounts = set()
    for s in ts:
        m = re.fullmatch(r'(.+?)(?:总部子账号|门店子账号|区域子账号|超级管理员)当前(?:待办.*)?', s)
        if m:
            accounts.add(m.group(1))
    if len(accounts) != 1:
        raise RuntimeError('无法唯一核对来客“当前”商户，未提交')
    return accounts.pop()


def settle_home(d, expected):
    def ready():
        if d.app_current().get('package') != MERCHANT:
            return False
        ts = texts(d)
        if dismiss_usage_survey(d, ts):
            return False
        if '选择登录的版本' in ts and '行业通用版' in ts:
            d(text='行业通用版').click(timeout=3)
            d(text='确认登录').click(timeout=3)
            return False
        if '我是管理者' in ts or '我是管理者/运营者' in ts:
            time.sleep(.8)
            d(text='我是管理者/运营者' if '我是管理者/运营者' in ts else '我是管理者').click(timeout=3)
            return False
        if '商户管理' in ts or '个人中心' in ts:
            d.press('back')
            return False
        if '首页' in ts and d(resourceId=MERCHANT + ':id/tv_user_nickname').exists:
            d(text='首页').click(timeout=3)
            return False
        if '商品管理' not in ts:
            return False
        return True
    wait(d, ready, 40, '来客经营首页')
    # Cached home cards can temporarily omit Current even after a completed switch.
    # The native personal-center Company row is authoritative for the active context.
    def personal_ready():
        ts = texts(d)
        if dismiss_usage_survey(d, ts):
            return False
        # The SSO version picker can arrive after the old home briefly rendered.
        if '选择登录的版本' in ts and '行业通用版' in ts:
            d(text='行业通用版').click(timeout=3)
            d(text='确认登录').click(timeout=3)
            return False
        for label in ('我是管理者/运营者','我是管理者'):
            if label in ts:
                d(text=label).click(timeout=3)
                return False
        if d(resourceId=MERCHANT + ':id/tv_user_nickname').exists:
            return True
        if d(text='我的').exists:
            d(text='我的').click(timeout=3)
        else:
            try:
                open_profile_drawer(d)
            except RuntimeError:
                # Business tiles can render before native bottom navigation/avatar.
                return False
        return False
    wait(d, personal_ready, label='来客我的页面')
    drawer = d(resourceId=MERCHANT + ':id/biz_view_title').exists
    time.sleep(.8)
    d(resourceId=MERCHANT + ':id/tv_user_nickname').click(timeout=3)
    wait(d, lambda: '个人中心' in texts(d), label='来客个人中心')
    wait(d, lambda: profile_company(root(d)) is not None, label='来客公司身份')
    actual = profile_company(root(d))
    if actual != expected:
        raise RuntimeError(f'当前公司为【{actual}】，与目标账号【{expected}】不一致，未提交')
    d.press('back')
    if drawer:
        wait(d, lambda: d.app_current().get('activity', '').endswith('MainActivity')
             and d(resourceId=MERCHANT + ':id/iv_go_back').exists, label='返回个人侧栏')
        time.sleep(.8)
        d(resourceId=MERCHANT + ':id/iv_go_back').click(timeout=3)
        wait(d, lambda: not d(resourceId=MERCHANT + ':id/tv_user_nickname').exists, label='关闭个人侧栏')
    else:
        wait(d, lambda: d(text='首页').exists, label='返回来客我的页面')
        d(text='首页').click(timeout=3)
    wait(d, lambda: '商品管理' in texts(d), timeout=40, label='返回来客经营首页')


def open_profile_drawer(d):
    # Field-verified industry-version avatar: identify its small top-left hit target.
    w, h = d.window_size()
    choices = []
    for n in root(d).iter('node'):
        b = list(map(int, re.findall(r'\d+', n.get('bounds', ''))))
        if (n.get('package') == MERCHANT and n.get('clickable') == 'true' and not n.get('text')
                and not n.get('content-desc') and len(b) == 4 and 0 < b[0] < w*.2
                and b[2] < w*.25 and h*.035 < b[1] < h*.1
                and 60 < b[2]-b[0] < 250 and 40 < b[3]-b[1] < 150):
            choices.append(n)
    if len(choices) != 1:
        raise RuntimeError('行业通用版头像入口不唯一，未猜测点击')
    tap(d, choices[0])


def profile_company(r):
    parents = {c: p for p in r.iter() for c in p}
    for n in r.iter('node'):
        if n.get('resource-id') != MERCHANT + ':id/tv_item_title' or n.get('text') not in ('公司', '切换公司'):
            continue
        p = n
        while p in parents:
            p = parents[p]
            nodes = list(p.iter('node'))
            if sum(x.get('resource-id') == MERCHANT + ':id/tv_item_title' for x in nodes) != 1:
                break
            hints = [x.get('text') for x in nodes if x.get('resource-id') == MERCHANT + ':id/tv_item_hint']
            if len(hints) == 1:
                return hints[0]
    return None


def open_management(d):
    if getattr(d,'native_adb',False) is True:
        result=d.shell(['am','start','-W','-a','android.intent.action.VIEW',
            '-d','snssdk299467://account/choose','-p',MERCHANT])
        if result.exit_code:raise RuntimeError('ADB 公司选择内部入口无法打开')
        wait(d,lambda:any(t in texts(d) for t in ('商户管理','选择你的公司')),
             label='ADB 公司选择页面加载')
        return
    d.app_start(MERCHANT)
    for _ in range(9):
        ts = texts(d)
        if dismiss_usage_survey(d, ts):
            time.sleep(.7)
            continue
        if '商户管理' in ts or '选择你的公司' in ts:
            return
        if '切换公司' in ts:
            d(text='切换公司').click(timeout=3)
            wait(d,lambda:any(t in texts(d) for t in ('商户管理','选择你的公司')),label='商户管理列表加载')
            return
        if '个人中心' in ts:
            label = '公司' if '公司' in ts else '切换公司'
            d(text=label).click(timeout=3)
        elif d(resourceId=MERCHANT + ':id/tv_user_nickname').exists:
            d(resourceId=MERCHANT + ':id/tv_user_nickname').click(timeout=3)
        elif '我的' in ts:
            d(text='我的').click(timeout=3)
        elif '我是管理者' in ts:
            d(text='我是管理者').click(timeout=3)
        elif '行业通用版' in ts and '管理' in ts:
            options = []
            for n in root(d).iter('node'):
                b = list(map(int, re.findall(r'\d+', n.get('bounds', ''))))
                if n.get('text') == '管理' and len(b) == 4 and 0 < b[2]-b[0] < 300 and 0 < b[3]-b[1] < 150:
                    options.append(n)
            if len(options) == 1:
                tap(d, options[0])
            else:
                raise RuntimeError('行业通用版商户管理入口不明确')
        else:
            d.press('back')
        time.sleep(1.5)
    raise RuntimeError('无法进入来客商户管理')


def scan_accounts(d, name, action=False):
    # Reset scroll; no removal of the user's displayed merchants to make room.
    for _ in range(6):
        swipe_reference(d,520,600,520,1950,.25)
    signatures = set()
    matches = {}
    all_names = set()
    for _ in range(100):
        wait(d,lambda:any(t in texts(d) for t in ('商户管理','选择你的公司')),timeout=40,label='商户管理列表加载')
        rows = account_rows(root(d))
        sig = tuple((n, tuple(sorted(a))) for n, a in rows)
        if sig in signatures:
            if d(text='查看更多商户').exists:
                d(text='查看更多商户').click(timeout=3)
                time.sleep(1)
                signatures.clear()
                continue
            break
        signatures.add(sig)
        for n, a in rows:
            all_names.add(n)
            if n != name:
                continue
            key = (n, a.get('account_tag', {}).get('text'), a.get('user_name', {}).get('text'))
            matches[key] = True
            if action:
                key = 'switch_account' if 'switch_account' in a else 'show_on_homepage'
                tap(d, a[key])
                return key
        swipe_reference(d,520,1950,520,600,.4)
        time.sleep(.4)
    if action:
        raise RuntimeError('未找到可见的目标商户切换按钮')
    return sorted(all_names) if name is None else len(matches)


def direct_switch(d, name):
    open_management(d)
    names = scan_accounts(d, None)
    try:
        name = resolve_name(name, names)
    except ValueError as exc:
        if '多家' in str(exc):
            raise RuntimeError(str(exc)) from exc
        return None
    count = scan_accounts(d, name)
    if count == 0:
        return False
    if count != 1:
        raise RuntimeError('来客存在多个同名账号，需要确认具体商家')
    action = scan_accounts(d, name, True)
    if action == 'show_on_homepage':
        action = scan_accounts(d, name, True)
        if action != 'switch_account':
            raise RuntimeError('商户未能展示到首页，可能已达 20 个上限')
    if d(text='确认切换').wait(timeout=2):
        d(text='确认切换').click(timeout=3)
    settle_home(d, name)
    return name


def crm_candidate_nodes(r):
    nodes = [n for n in r.iter('node') if n.get('package') == CRM and n.get('class') == 'android.widget.TextView']
    out = []
    for label in nodes:
        if label.get('text') != '签约商家':
            continue
        b = list(map(int, re.findall(r'\d+', label.get('bounds', ''))))
        if len(b) != 4:
            continue
        row = []
        for n in nodes:
            nb = list(map(int, re.findall(r'\d+', n.get('bounds', ''))))
            if len(nb) == 4 and nb[0] >= b[2] and nb[1] <= (b[1]+b[3])/2 <= nb[3] and n.get('text'):
                row.append((nb[0], n))
        if row:
            out.append(min(row, key=lambda p:p[0])[1])
    return out


def cooperation_container(r):
    nodes = [n for n in r.iter('node') if n.get('package')==CRM and n.get('resource-id')==COOP_LIST]
    if len(nodes)!=1:
        raise RuntimeError('合作列表未达到预期状态，未进入搜索框，未提交')
    return nodes[0]


def cooperation_cards(r):
    """Observed Cooperation webview card headings, NOT global search results."""
    container = cooperation_container(r)
    cards = []
    excluded = {'酒旅','距离','代运营','首次签约','再次签约','定向发单','订单续约',
        '30天支付GMV','30天核销GMV','商家经营分','导航','联系商家','商家待办未处理'}
    for card in container.iter('node'):
        children = list(card)
        if not children:
            continue
        heading = children[0]
        label = heading.get('text','')
        direct_text = {n.get('text') for n in children}
        # Clipped cards may begin at a metric/person, not the real index-0 heading.
        if (heading.get('class')=='android.widget.TextView' and heading.get('index')=='0'
                and label and label not in excluded and '酒旅' in direct_text
                and ('距离' in direct_text or '代运营' in direct_text)):
            cards.append(heading)
    return cards


def cooperation_snapshot(d):
    deadline = time.monotonic()+60
    while time.monotonic()<deadline:
        r = root(d)
        all_text = texts_from_root(r)
        try:
            container = cooperation_container(r)
        except RuntimeError:
            # Pull-to-refresh temporarily replaces the entire list with skeletons.
            if '合作管理' in all_text and any('loading' in t.lower() or '加载' in t for t in all_text):
                time.sleep(1)
                continue
            raise
        ts = [n.get('text','') for n in container.iter('node')]
        if any('暂无网络' in t or '无法连接到网络' in t for t in texts_from_root(r)):
            raise RuntimeError('手机业务页面无法联网')
        if not any('加载中' in t or '正在加载' in t or 'loading' in t.lower() for t in ts):
            return r
        time.sleep(1)
    raise RuntimeError('合作列表加载未达到预期状态，未把部分列表当作完整名单')


def texts_from_root(r):
    return [n.get('text','') for n in r.iter('node') if n.get('package') in (CRM,MERCHANT)]


def cooperation_swipe(d, r, toward_top=False):
    bounds = list(map(int,re.findall(r'\d+',cooperation_container(r).get('bounds',''))))
    w,h = d.window_size()
    if len(bounds)!=4 or not (0<=bounds[0]<bounds[2]<=w and 0<=bounds[1]<bounds[3]<=h):
        raise RuntimeError('合作列表范围不明确，未猜测滑动')
    x=(bounds[0]+bounds[2])//2
    high=int(bounds[1]+(bounds[3]-bounds[1])*.12)
    low=int(bounds[1]+(bounds[3]-bounds[1])*.88)
    d.swipe(x,high if toward_top else low,x,low if toward_top else high,.45)
    time.sleep(.7)


def cooperation_signature(r):
    return tuple((n.get('text'),n.get('bounds')) for n in cooperation_cards(r))


def reset_cooperation_top(d, max_pages=180):
    previous,stable=None,0
    for _ in range(max_pages):
        r=cooperation_snapshot(d);signature=cooperation_signature(r)
        stable=stable+1 if signature and signature==previous else 0
        if stable>=2:
            return
        previous=signature
        cooperation_swipe(d,r,toward_top=True)
    raise RuntimeError('合作列表未达到预期顶部，未提交')


def merge_cooperation_page(seen, page):
    # Adjacent swipes overlap. Preserve real duplicate names, don't deduplicate
    # two different contract cards into a falsely unique merchant.
    if not page:
        return seen
    overlap=0
    for size in range(1,min(len(seen),len(page))+1):
        if seen[-size:]==page[:size]:
            overlap=size
    return seen+page[overlap:]


def cooperation_end(r):
    ts = [n.get('text','') for n in cooperation_container(r).iter('node')]
    ts = [t.strip() for t in ts if t.strip()]
    # A merchant metric saying "暂无数据" is not the list's end marker.
    return bool(ts and re.fullmatch(
        r'(?:没有更多(?:了|数据)?|暂无更多(?:数据)?|已加载全部(?:内容)?|(?:已经)?到底[了啦]|无更多(?:数据)?|暂无商家|暂无数据)[~～。.!！]*',ts[-1]))


def scan_cooperation_names(d,max_pages=180):
    names=[];previous=None;stable=0
    for page_index in range(max_pages):
        r=cooperation_snapshot(d)
        page=[n.get('text') for n in cooperation_cards(r)]
        names=merge_cooperation_page(names,page)
        if page_index%10==0:
            LOG.info('cooperation list scanning page=%s cards=%s',page_index+1,len(names))
        signature=cooperation_signature(r)
        stable=stable+1 if signature==previous else 0
        if cooperation_end(r):
            LOG.info('cooperation list fully scanned cards=%s pages=%s',len(names),page_index+1)
            return names
        if stable>=3:
            raise RuntimeError('合作列表未达到预期结束状态，没有把滑动卡住误判为查无商家')
        previous=signature
        cooperation_swipe(d,r)
    raise RuntimeError('合作列表未扫描完整，未选择第一家匹配结果')


def find_cooperation_card(d,name,max_pages=180,toward_top=False):
    previous=None;stable=0
    for _ in range(max_pages):
        r=cooperation_snapshot(d)
        signature=cooperation_signature(r)
        stable=stable+1 if signature==previous else 0
        if stable>=3:
            break
        previous=signature
        matches=[n for n in cooperation_cards(r) if n.get('text')==name]
        if len(matches)>1:
            raise RuntimeError('同名商家有多个合作入口，未提交')
        if matches:
            node=matches[0]
            bounds=list(map(int,re.findall(r'\d+',node.get('bounds',''))))
            container_bounds=list(map(int,re.findall(r'\d+',cooperation_container(r).get('bounds',''))))
            if len(bounds)==4 and container_bounds[1]<=bounds[1]<bounds[3]<=container_bounds[3]:
                tap(d,node)
                return
            if len(bounds)==4:
                cooperation_swipe(d,r,toward_top=bounds[1]<container_bounds[1])
                continue
        if not toward_top and cooperation_end(r):
            break
        cooperation_swipe(d,r,toward_top=toward_top)
    raise RuntimeError('复定位未找到目标合作卡片，列表可能变化，未提交')


def crm_switch(d, hotel, cfg):
    # Cold start can show only bottom tabs while web content is still loading.
    # Enter Cooperation explicitly; Back alone can leave us on a blank Home/chat.
    entered = False
    for restart in range(2):
        # Fresh Cooperation webview also removes stale search/filter/scroll state.
        # No data or credentials are cleared.
        d.app_start(CRM, stop=True)
        for _ in range(8):
            if d(resourceId=COOP_LIST).exists and d(text='合作管理').exists:
                entered = True
                break
            if d(text='合作').exists:
                d(text='合作').click(timeout=3)
                wait(d,lambda:d(resourceId=COOP_LIST).exists,timeout=75,label='销帮合作列表加载')
                entered = True
                break
            d.press('back')
            time.sleep(.8)
        if entered:
            break
    else:
        raise RuntimeError('无法进入销帮合作列表，未提交')
    # The user confirmed that global search misses existing Cooperation merchants.
    # Never focus/type into it, even as a fallback.
    d(text='服务中').click(timeout=3)
    time.sleep(1.5)
    reset_cooperation_top(d)
    names=scan_cooperation_names(d)
    resolved=resolve_name(hotel,names)
    if sum(name_key(n)==name_key(resolved) for n in names)!=1:
        raise RuntimeError('同名商家对应多条合作记录，需要确认合作账号，未提交')
    if names.index(resolved)>len(names)//2:
        find_cooperation_card(d,resolved,toward_top=True)
    else:
        reset_cooperation_top(d)
        find_cooperation_card(d,resolved)
    wait(d, lambda: '商家后台' in texts(d))
    ts = texts(d)
    if name_key(f'{resolved}({resolved})') not in {name_key(t) for t in ts}:
        raise RuntimeError('销帮详情商家与门店名称不是目标的精确匹配，需确认映射')
    d(text='商家后台').click()
    expected = cfg.get('account_mappings', {}).get(resolved, resolved)
    settle_home(d, expected)
    return resolved, expected


def reuse_current_hotel(d, hotel, company):
    """Reuse a live hotel-named account, never a differently named company guess.

    A differently named company cannot establish which child store is selected.
    Such accounts keep their verified navigation route until store-level native
    evidence is available. Region/group accounts have their own stronger gate.
    """
    if name_key(hotel) != name_key(company):
        return False
    try:
        d.app_start(MERCHANT, stop=True)
        wait(d, lambda: '商品管理' in texts(d), timeout=15, label='当前酒店首页')
        ts = texts(d)
        # Some native home layouts omit Current while the authoritative Company
        # row remains available. This is the same identity gate as direct_switch.
        if any('当前' in t for t in ts) and current_account(ts) != company:
            return False
        if any('区域子账号当前' in t for t in ts):
            return False
        settle_home(d, company)
        after = texts(d)
        if any('当前' in t for t in after) and current_account(after) != company:
            return False
        if any('区域子账号当前' in t for t in after):
            return False
        return True
    except RuntimeError as exc:
        LOG.info('current hotel identity not reusable: %s', exc)
        return False


def switch_merchant(d, hotel, cfg):
    target = cfg.get('_catalog_target')
    if target:
        if target.get('route') == 'unverified_child':
            raise RuntimeError('已找到酒店及所属集团，但该品牌的集团共用规则尚未核实，未提交')
        entry = target.get('entry_name') or target['name']
        mapped = cfg.get('account_mappings',{}).get(entry)
        company = target.get('company') or mapped or entry
        scoped_cfg = dict(cfg, account_mappings={**cfg.get('account_mappings',{}), entry:company})
        if not target.get('shared_brand') and entry == target['name'] and reuse_current_hotel(d,entry,company):
            return '已核对当前酒店',company,target['name']
        if target.get('shared_brand'):
            def verify_region():
                ts = texts(d)
                if entry not in ts or current_account(ts) != company:
                    raise RuntimeError('集团公司与具体区域身份未同时核对成功，未提交')
            # Leave an old plan/blank account-management WebView without retaining
            # its cached content. Restarting the app retains login and identity.
            d.app_start(MERCHANT,stop=True)
            try:
                settle_home(d,company)
                verify_region()
                return '已核对当前集团区域',company,target['name']
            except RuntimeError as exc:
                LOG.info('group current identity not reusable: %s',exc)
            try:
                if direct_switch(d,company):
                    verify_region()
                    return '来客商户管理/已核对集团区域',company,target['name']
            except RuntimeError as exc:
                LOG.info('group direct switch unavailable: %s',exc)
        if not target.get('shared_brand') and company == entry:
            try:
                account = direct_switch(d, company)
                if account:
                    return '来客商户管理/目录匹配',account,target['name']
            except RuntimeError as exc:
                LOG.info('ordinary direct switch unavailable hotel=%s: %s',entry,exc)
        _, account = crm_switch(d,entry,scoped_cfg)
        if target.get('shared_brand'):
            verify_region()
        return '销帮合作列表/集团户' if target.get('shared_brand') else '销帮合作列表/目录匹配',account,target['name']
    # Previously verified company/store mappings are also a small canonical directory.
    try:
        hotel = resolve_name(hotel, list(cfg.get('account_mappings', {})))
    except ValueError:
        pass
    expected = cfg.get('account_mappings', {}).get(hotel, hotel)
    if reuse_current_hotel(d,hotel,expected):
        return '已核对当前酒店',expected,hotel
    direct_error = ''
    if expected == hotel:
        try:
            account = direct_switch(d, expected)
            if account:
                return '来客商户管理', account, account
        except RuntimeError as exc:
            direct_error = str(exc)
    try:
        resolved, account = crm_switch(d, hotel, cfg)
        return '销帮合作列表', account, resolved
    except Exception as exc:
        raise RuntimeError(f'未能安全切换到【{hotel}】：{exc}' + (f'；来客：{direct_error}' if direct_error else '')) from exc
