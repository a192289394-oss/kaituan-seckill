"""Validate PC page observations before interpreting business data.

A matching URL is routing evidence, not sufficient authorization to submit.
"""
from urllib.parse import urlparse, parse_qs


def validate_activity_captures(payload, urls):
    if not isinstance(payload, dict):
        raise RuntimeError('PC 页面返回格式无效，请重新读取。')
    captures = payload.get('captures') or []
    if not isinstance(captures, list) or any(not isinstance(c, dict) for c in captures):
        raise RuntimeError('PC 页面返回格式无效，请重新读取。')
    for cap in captures:
        page = urlparse(cap.get('url') or '')
        text = cap.get('text') or ''
        if (page.hostname == 'sso.oceanengine.com' or '/login' in page.path
                or any(w in text for w in ('发送验证码', '立即登录', '扫码登录'))):
            raise RuntimeError('PC 登录已失效，请在项目专用浏览器中登录林客后重试。')
    if payload.get('status') == 'auth_required':
        raise RuntimeError('PC 登录已失效，请在项目专用浏览器中登录林客后重试。')
    if payload.get('status') != 'ok':
        raise RuntimeError('PC 页面探测未成功，不能判断商品或活动是否存在。')
    if len(captures) != 2 or {c.get('label') for c in captures} != {'seckill', 'goods'}:
        raise RuntimeError('PC 商品或秒杀页面读取不完整，不能判断活动是否存在。')
    for cap in captures:
        actual = urlparse(cap.get('url') or '')
        expected = urlparse(urls[cap['label']])
        if actual.scheme != 'https' or actual.hostname != 'life.douyin.com' or actual.path != expected.path:
            raise RuntimeError('PC 未进入目标来客页面，请重新完成商家附身。')
        query, wanted = parse_qs(actual.query), parse_qs(expected.query)
        for key in ('groupid', 'root_life_account_id'):
            if not wanted.get(key) or query.get(key) != wanted[key]:
                raise RuntimeError('PC 当前页面商家路由与目标不一致，请重新附身；未读取为有效卡片。')
        # Field-verified: Laike may remove the view hint during SPA navigation.
        # The two merchant identifiers remain mandatory; a conflicting hint is not.
        if query.get('life_biz_view_id') and query['life_biz_view_id'] != wanted.get('life_biz_view_id'):
            raise RuntimeError('PC 当前业务视图与目标不一致。')
        text = (cap.get('text') or '').strip()
        if not text:
            raise RuntimeError('PC 页面为空白或尚未加载完成，不能当成没有秒杀活动。')
        if any(w in text for w in ('无权限', '暂无权限', '没有权限', '页面不存在', '网络异常', '加载失败')):
            raise RuntimeError('PC 页面提示权限或加载异常，不能作为商品/活动结果。')
        heading = '秒杀' if cap['label'] == 'seckill' else '商品'
        if heading not in text:
            raise RuntimeError('PC 页面内容尚未就绪，请等待加载后重新读取。')
    return captures
