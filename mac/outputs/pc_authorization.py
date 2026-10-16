"""Cross-activity authorization verification; read-only, never publishes.

Decode raw API response text in Python, not JS Response.json(): 19-digit activity
IDs exceed JavaScript's safe integer range. The requested ID must match exactly.
"""
import json


def parse_activity_response(text, expected_id):
    payload = json.loads(text)
    if int(payload.get('status_code', -1)) != 0:
        raise ValueError('活动详情接口未成功')
    activity = payload.get('activity') or {}
    actual = activity.get('activity_id')
    if isinstance(actual, (float, bool)) or str(actual) != str(expected_id):
        raise ValueError('活动编号不一致或发生精度丢失')
    return activity


def verify_existing_authorizations(source, activities, accounts, now):
    """All requested accounts × all source products must be independently proven.

    Existing but exhausted/mismatched grants are conflicts, not permission to
    replenish inventory or create another overlapping activity.
    """
    wanted = list(dict.fromkeys(accounts))
    if not wanted or any(not isinstance(x, str) or not x.strip() for x in wanted):
        raise ValueError('需要明确主播抖音号')
    products = {str(s['sku_id']): int(s['fixed_price']) for s in source['sku_list']}
    if not products or len(products) != len(source['sku_list']):
        raise ValueError('模板商品为空或编号重复')
    required_end = int(source['end_time'])
    if required_end <= now:
        raise ValueError('模板授权时段已结束')
    covered = {account: {} for account in wanted}
    conflicts = []
    for activity in activities:
        if int(activity['activity_status']) != 2:
            continue
        if not int(activity['start_time']) <= now < int(activity['end_time']):
            continue
        activity_id = activity['activity_id']
        if isinstance(activity_id, (float, bool)):
            raise ValueError('活动编号必须完整保留')
        for anchor in activity.get('anchor_info_list', []):
            account = str(anchor.get('douyin_id', ''))
            if account not in covered:
                continue
            uid = str(anchor['uid'])
            for sku in activity.get('sku_list', []):
                sku_id = str(sku['sku_id'])
                if sku_id not in products:
                    continue
                matches = [x for x in sku.get('anchor_list', []) if str(x['uid']) == uid]
                if not matches:
                    continue
                if len(matches) != 1:
                    raise ValueError('同一商品的主播授权记录不唯一')
                grant = matches[0]
                reasons = []
                if int(grant['fixed_price']) != products[sku_id]:
                    reasons.append('price_mismatch')
                if int(grant['left_quantity']) <= 0:
                    reasons.append('inventory_exhausted')
                if int(activity['end_time']) < required_end:
                    reasons.append('ends_before_requested_window')
                if reasons:
                    conflicts.append({'account': account, 'sku_id': sku_id,
                                      'activity_id': str(activity_id), 'reasons': reasons})
                    continue
                covered[account][sku_id] = {
                    'activity_id': str(activity_id), 'end_time': int(activity['end_time']),
                    'price': int(grant['fixed_price']), 'remaining': int(grant['left_quantity'])}
    missing = {a: sorted(set(products) - set(rows)) for a, rows in covered.items()}
    all_covered = all(not items for items in missing.values())
    status = ('already_authorized' if all_covered else
              'blocked_existing_conflict' if conflicts else 'needs_configuration')
    return {'status': status, 'coverage': covered, 'missing': missing,
            'conflicts': conflicts, 'should_publish': False}
