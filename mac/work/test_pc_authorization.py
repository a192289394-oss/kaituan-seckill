import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs'))
from pc_authorization import parse_activity_response, verify_existing_authorizations


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.source = {'end_time': 300, 'sku_list': [{'sku_id': 'sku1', 'fixed_price': 9900}, {'sku_id': 'sku2', 'fixed_price': 9900}]}
        self.activity = {'activity_id': '9000000000000000123', 'activity_status': 2, 'start_time': 100, 'end_time': 300,
                         'anchor_info_list': [{'uid': 'u1', 'douyin_id': 'account1'}],
                         'sku_list': [{'sku_id': sku, 'anchor_list': [{'uid': 'u1', 'fixed_price': 9900, 'left_quantity': 8}]} for sku in ['sku1', 'sku2']]}

    def report(self, activities=None, accounts=None):
        return verify_existing_authorizations(self.source, activities or [self.activity], accounts or ['account1'], 200)

    def test_raw_json_preserves_large_numeric_id(self):
        raw = '{"status_code":0,"activity":{"activity_id":9000000000000000123}}'
        self.assertEqual(str(parse_activity_response(raw, '9000000000000000123')['activity_id']), '9000000000000000123')

    def test_rounded_or_wrong_id_is_rejected(self):
        for value in [9000000000000000000, 9e18, '123']:
            with self.assertRaises(ValueError):
                parse_activity_response(json.dumps({'status_code': 0, 'activity': {'activity_id': value}}), '9000000000000000123')

    def test_existing_coverage_never_publishes_duplicate(self):
        report = self.report()
        self.assertEqual(report['status'], 'already_authorized')
        self.assertFalse(report['should_publish'])

    def test_product_authorization_is_checked_not_just_activity_membership(self):
        self.activity['sku_list'][1]['anchor_list'] = []
        self.assertEqual(self.report()['missing'], {'account1': ['sku2']})

    def test_split_coverage_across_activities(self):
        other = copy.deepcopy(self.activity)
        self.activity['sku_list'] = self.activity['sku_list'][:1]
        other['activity_id'] = '9000000000000000456'
        other['sku_list'] = other['sku_list'][1:]
        self.assertEqual(self.report([self.activity, other])['status'], 'already_authorized')

    def test_all_accounts_required(self):
        self.assertEqual(self.report(accounts=['account1', 'account2'])['missing']['account2'], ['sku1', 'sku2'])

    def test_wrong_price_blocks_instead_of_creating_overlap(self):
        self.activity['sku_list'][0]['anchor_list'][0]['fixed_price'] = 10000
        self.assertEqual(self.report()['status'], 'blocked_existing_conflict')

    def test_exhausted_inventory_is_not_permission_to_replenish(self):
        self.activity['sku_list'][0]['anchor_list'][0]['left_quantity'] = 0
        self.assertEqual(self.report()['status'], 'blocked_existing_conflict')

    def test_shorter_authorization_window_is_not_complete(self):
        self.activity['end_time'] = 250
        self.assertEqual(self.report()['status'], 'blocked_existing_conflict')

    def test_inactive_and_future_activities_not_proof(self):
        self.activity['activity_status'] = 3
        self.assertEqual(self.report()['status'], 'needs_configuration')
        self.activity['activity_status'] = 2
        self.activity['start_time'] = 210
        self.assertEqual(self.report()['status'], 'needs_configuration')

    def test_expired_template_rejected(self):
        self.source['end_time'] = 190
        with self.assertRaises(ValueError):
            self.report()


if __name__ == '__main__':
    unittest.main()
