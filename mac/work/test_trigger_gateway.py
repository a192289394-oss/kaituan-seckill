import concurrent.futures
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / 'server' / 'trigger_gateway.py'
SPEC = importlib.util.spec_from_file_location('trigger_gateway', SOURCE)
gw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gw)


class FakeClock:
    def __init__(self):
        self.now = 1800000000.
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.db = Path(self.temp.name) / 'queue.sqlite3'
        self.store = gw.GatewayStore(self.db, worker_id='mac-one', clock=self.clock, secret_values=('very-private-token',))
    def tearDown(self):
        self.temp.cleanup()
    def create(self, **extra):
        body = dict(request_id='request-1', kind='plan', plan_id='1234567890123456789', allow_write=True)
        body.update(extra)
        return self.store.create(body)['task']
    def legacy_read_only(self, task):
        """Seed a stored read-only plan. New creates cannot omit allow_write."""
        with self.store.tx() as conn:
            payload = json.loads(conn.execute("SELECT payload FROM tasks WHERE id=?", (task['id'],)).fetchone()['payload'])
            payload.update(allow_write=False, read_only=True)
            conn.execute("UPDATE tasks SET payload=?, read_only=1 WHERE id=?", (gw.canonical(payload), task['id']))
        return task
    def claim(self):
        return self.store.claim('mac-one')['task']
    def body(self, task, **extra):
        return dict(worker_id='mac-one', task_id=task['id'], lease_token=task['lease_token'], revision=task['revision'], **extra)
    def error(self, code, fn):
        with self.assertRaises(gw.APIError) as cm:
            fn()
        self.assertEqual(cm.exception.code, code)
    def report(self, task, status='succeeded', **extra):
        return self.store.report(self.body(task, status=status, result={'summary': 'Verified'}, **extra))['task']

    def test_recovery_retry_preserves_generation_permission_and_commit(self):
        task=self.store.create({'request_id':'manual-recovery','kind':'authorization','hotel':'Synthetic','accounts':['new123']})['task']
        claim=self.store.claim('mac-one')['task']
        packet={'worker_id':'mac-one','task_id':task['id'],'lease_token':claim['lease_token'],'revision':claim['revision']}
        self.store.report(dict(packet,status='waiting_device',result={'text':'temporary'},committed=False))
        recovered=self.store.retry(task['id'],{'expected_revision':1})['task']
        self.assertEqual(recovered['created'],task['created']);self.assertEqual(recovered['revision'],1)
        self.assertTrue(recovered['read_only']);self.assertFalse(recovered['payload']['allow_write'])
        self.assertEqual(recovered['status'],'queued')
        claim=self.store.claim('mac-one')['task']
        with self.assertRaises(gw.APIError):self.store.retry(task['id'],{'expected_revision':1})

    def test_plan_requires_explicit_write_and_echoes_mode(self):
        self.error('plan_write_required', lambda: self.store.create(dict(request_id='omitted', kind='plan', plan_id='1234567890123456789')))
        self.error('plan_write_required', lambda: self.store.create(dict(request_id='off', kind='plan', plan_id='1234567890123456789', allow_write=False)))
        task = self.create()
        self.assertFalse(task['read_only'])
        self.assertEqual(task['mode'], 'write')
        self.assertEqual(task['payload']['plan_id'], '1234567890123456789')
        auth = self.store.create(dict(request_id='auth-ro', kind='authorization', hotel='Hotel', accounts=['account-1']))['task']
        self.assertTrue(auth['read_only'])
        self.assertEqual(auth['mode'], 'read_only')
        self.assertFalse(auth['payload']['allow_write'])
        self.error('plan_id', lambda: self.store.create(dict(request_id='bad', kind='plan', plan_id=1234567890123456789, allow_write=True)))
        self.error('plan_id', lambda: self.store.create(dict(request_id='bad', kind='plan', plan_id='123', allow_write=True)))

    def test_exact_id_and_business_duplicate_alias_remain_idempotent(self):
        task = self.create(allow_write=True)
        duplicate = self.store.create(dict(request_id='request-2', kind='plan', plan_id='1234567890123456789', allow_write=True))
        self.assertTrue(duplicate['business_duplicate'])
        self.assertEqual(task['id'], duplicate['task']['id'])
        self.error('request_conflict', lambda: self.store.create(dict(request_id='request-2', kind='plan', plan_id='1234567890123456780', allow_write=True)))
        self.assertTrue(self.store.create(dict(request_id='request-1', kind='plan', plan_id='1234567890123456789', allow_write=True))['duplicate'])

    def test_concurrent_duplicate_only_one_task(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda i: self.store.create(dict(request_id=f'request-{i}', kind='plan', plan_id='1234567890123456789', allow_write=True)), range(10)))
        self.assertEqual(len({r['task']['id'] for r in results}), 1)
        self.assertEqual(len(self.store.list_tasks()['tasks']), 1)

    def test_authorization_requires_explicit_single_hotel_and_accounts(self):
        self.error('hotel', lambda: self.store.create(dict(request_id='a', kind='authorization', accounts=['abc'])))
        self.error('accounts', lambda: self.store.create(dict(request_id='a', kind='authorization', hotel='Hotel', accounts=[])))
        a = self.store.create(dict(request_id='a', kind='authorization', hotel='Hotel', accounts=['abc', 'def']))
        b = self.store.create(dict(request_id='b', kind='authorization', hotel='Hotel', accounts=['def', 'abc']))
        self.assertEqual(a['task']['id'], b['task']['id'])

    def test_terminal_authorization_allows_fresh_generation_but_old_request_replays_old_task(self):
        first_body = dict(request_id='authorization-1', kind='authorization', hotel='Hotel', accounts=['abc'])
        first = self.store.create(first_body)['task']
        claim = self.claim()
        finished = self.report(claim)
        self.assertEqual(finished['status'], 'succeeded')
        second_body = dict(request_id='authorization-2', kind='authorization', hotel='Hotel', accounts=['abc'])
        second = self.store.create(second_body)
        self.assertFalse(second['duplicate'])
        self.assertNotEqual(first['id'], second['task']['id'])
        self.assertEqual(self.store.create(first_body)['task']['id'], first['id'])
        active_duplicate = self.store.create(dict(second_body, request_id='authorization-3'))
        self.assertTrue(active_duplicate['business_duplicate'])
        self.assertEqual(active_duplicate['task']['id'], second['task']['id'])

    def test_expired_authorization_is_released_during_create_without_prior_list(self):
        first = self.store.create(dict(request_id='authorization-1', kind='authorization', hotel='Hotel', accounts=['abc']))['task']
        self.clock.advance(gw.TASK_SECONDS + 1)
        second = self.store.create(dict(request_id='authorization-2', kind='authorization', hotel='Hotel', accounts=['abc']))['task']
        self.assertNotEqual(first['id'], second['id'])
        tasks = {task['id']: task for task in self.store.list_tasks()['tasks']}
        self.assertEqual(tasks[first['id']]['status'], 'expired')
        self.assertEqual(tasks[second['id']]['status'], 'queued')

    def test_terminal_plan_id_remains_permanently_deduplicated(self):
        first = self.create()
        claim = self.claim()
        self.report(claim)
        duplicate = self.store.create(dict(request_id='request-2', kind='plan', plan_id='1234567890123456789', allow_write=True))
        self.assertTrue(duplicate['business_duplicate'])
        self.assertEqual(first['id'], duplicate['task']['id'])

    def test_inspect_never_authorizes_write(self):
        self.error('inspect_read_only', lambda: self.store.create(dict(request_id='i', kind='inspect', plan_id='1234567890123456789', allow_write=True)))

    def test_fixed_single_worker_no_second_concurrent_dispatch(self):
        self.create()
        first = self.claim()
        self.assertIsNone(self.claim())
        self.error('worker_pinned', lambda: self.store.claim('another-mac'))
        self.assertEqual(first['worker_id'], 'mac-one')

    def test_expired_lease_recovers_same_task_read_only_and_fences_old_report(self):
        task = self.create(allow_write=True)
        first = self.claim()
        self.assertFalse(first['read_only'])
        self.clock.advance(91)
        self.error('lease_expired', lambda: self.report(first))
        next_claim = self.claim()
        self.assertEqual(task['id'], next_claim['id'])
        self.assertTrue(next_claim['read_only'])
        self.assertNotEqual(first['lease_token'], next_claim['lease_token'])
        self.error('stale_lease', lambda: self.report(first))

    def test_heartbeat_renews_but_cannot_resurrect_expired_lease(self):
        self.create()
        task = self.claim()
        self.clock.advance(60)
        runtime = {'android_device': {'status': 'unavailable', 'reason': 'adb_not_device'},
                   'root': {'status': 'unknown', 'reason': 'android_not_ready'},
                   'business_app': {'status': 'unknown', 'reason': 'android_not_ready'},
                   'native_interface': {'status': 'unknown', 'reason': 'android_not_ready'}}
        h = self.store.heartbeat(self.body(task, health={'runtime': runtime}))
        self.assertGreater(h['task']['lease_until'], task['lease_until'])
        status = self.store.status()
        self.assertTrue(status['worker']['online'])
        self.assertTrue(status['worker']['gateway_online'])
        self.assertEqual(status['worker']['health']['runtime'], runtime)
        self.clock.advance(91)
        status = self.store.status()
        self.assertFalse(status['worker']['online'])
        self.assertFalse(status['worker']['gateway_online'])
        self.assertEqual(status['worker']['health']['runtime'], runtime)
        self.error('lease_expired', lambda: self.store.heartbeat(self.body(task)))

    def test_heartbeat_rejects_non_object_health_shape(self):
        self.store.heartbeat({'worker_id': 'mac-one', 'health': ['misleading', 'shape']})
        self.assertEqual(self.store.status()['worker']['health'], {})

    def test_commit_requires_two_gates_and_is_durable_before_result(self):
        self.create(allow_write=True)
        task = self.claim()
        self.error('preflight_required', lambda: self.store.gate(self.body(task, stage='commit')))
        self.assertTrue(self.store.gate(self.body(task, stage='preflight'))['allowed'])
        self.assertTrue(self.store.gate(self.body(task, stage='commit'))['committed'])
        self.assertFalse(self.store.gate(self.body(task, stage='commit'))['allowed'])
        reopened = gw.GatewayStore(self.db, worker_id='mac-one', clock=self.clock)
        self.clock.advance(91)
        recovered = reopened.claim('mac-one')['task']
        self.assertTrue(recovered['committed'])
        self.assertTrue(recovered['read_only'])

    def test_cancel_before_dispatch(self):
        task = self.create(allow_write=True)
        cancelled = self.store.cancel(task['id'], {'expected_revision': 1})['task']
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertIsNone(self.claim())

    def test_claimed_cancel_keeps_lease_and_fences_prior_revision(self):
        self.create(allow_write=True)
        task = self.claim()
        cancelled = self.store.cancel(task['id'], {'expected_revision': 1})['task']
        self.assertEqual(cancelled['status'], 'cancel_requested')
        self.assertEqual(cancelled['worker_id'], 'mac-one')
        self.error('stale_revision', lambda: self.store.gate(self.body(task, stage='commit')))
        self.error('stale_revision', lambda: self.report(task))
        beat = self.store.heartbeat(self.body(task))
        self.assertTrue(beat['task']['fenced'])
        self.assertTrue(beat['task']['cancel_requested'])
        self.assertEqual(beat['task']['lease_until'], task['lease_until'])
        self.clock.advance(91)
        reclaimed = self.claim()
        self.assertEqual(reclaimed['id'], task['id'])
        self.assertTrue(reclaimed['read_only'])
        self.assertEqual(self.report(reclaimed)['status'], 'cancelled')

    def test_report_lost_response_replay_is_durable_and_exact(self):
        self.create()
        task = self.claim()
        body = self.body(task, status='needs_input', result={'summary': 'Need a schedule'})
        first = self.store.report(body)
        self.assertEqual(self.store.report(body), first)
        reopened = gw.GatewayStore(self.db, worker_id='mac-one', clock=self.clock)
        self.assertEqual(reopened.report(body), first)
        self.error('report_conflict', lambda: self.store.report({**body, 'status': 'succeeded'}))
        self.store.resume(task['id'], {'expected_revision': 1, 'params': {'note': 'Recheck'}})
        self.assertEqual(self.store.report(body), first)
        self.assertEqual(self.store.list_tasks()['tasks'][0]['status'], 'queued')

    def test_needs_input_always_fences_prior_write_permission(self):
        self.create(allow_write=True)
        claim = self.claim()
        reported = self.report(claim, 'needs_input')
        self.assertTrue(reported['read_only'])
        self.assertFalse(reported['committed'])
        self.assertIsNone(self.claim())

    def test_cancel_after_commit_only_reviews_and_keeps_evidence(self):
        self.create(allow_write=True)
        task = self.claim()
        self.store.gate(self.body(task, stage='preflight'))
        self.store.gate(self.body(task, stage='commit'))
        cancelled = self.store.cancel(task['id'], {'expected_revision': 1})['task']
        self.assertTrue(cancelled['committed'])
        self.assertEqual(cancelled['revision'], 1)
        reported = self.report(task, 'failed', committed=True, details={'evidence': 'Network unavailable'})
        self.assertEqual(reported['status'], 'waiting_review')
        self.assertTrue(reported['read_only'])
        self.assertIsNone(self.claim())
        self.clock.advance(31)
        self.assertTrue(self.claim()['read_only'])

    def test_needs_input_resume_same_id_new_revision_and_read_only(self):
        self.create(allow_write=True)
        task = self.claim()
        reported = self.report(task, 'needs_input')
        self.assertIsNone(self.claim())
        self.error('immutable_target', lambda: self.store.resume(task['id'], dict(expected_revision=1, params={'allow_write': True})))
        resumed = self.store.resume(task['id'], dict(expected_revision=1, params={'note': 'Please recheck'}))['task']
        self.assertEqual(resumed['id'], task['id'])
        self.assertEqual(resumed['revision'], 2)
        self.assertTrue(resumed['read_only'])
        self.assertFalse(resumed['payload']['allow_write'])
        self.error('stale_revision', lambda: self.store.resume(task['id'], {'expected_revision': 1}))

    def test_queued_task_expires_but_committed_review_does_not(self):
        task = self.create()
        self.clock.advance(86401)
        self.assertIsNone(self.claim())
        self.assertEqual(self.store.list_tasks()['tasks'][0]['status'], 'expired')

    def schedule_waiting_task(self):
        self.store.create(dict(request_id='authorization', kind='authorization', hotel='Hotel', accounts=['account-1'], allow_write=True))
        task = self.claim()
        self.report(task, 'needs_input', details={'preview': {'template_id': '1234567890123456789', 'fingerprint': 'a' * 64, 'products': [{'price': 99, 'stock': 10}]}})
        return task, dict(template_id='1234567890123456789', fingerprint='a' * 64, start_time=self.clock() + 3600, end_time=self.clock() + 86400, confirmed=True)

    def test_schedule_confirmation_matches_frozen_preview_same_task_and_new_revision(self):
        task, params = self.schedule_waiting_task()
        resumed = self.store.resume(task['id'], {'expected_revision': 1, 'params': params})['task']
        self.assertEqual(resumed['id'], task['id'])
        self.assertEqual(resumed['created'], task['created'])
        self.assertEqual(resumed['revision'], 2)
        self.assertFalse(resumed['read_only'])
        self.assertTrue(resumed['payload']['allow_write'])
        self.assertEqual(resumed['payload']['params'], params)
        self.assertEqual(resumed['payload']['accounts'], ['account-1'])
        next_claim = self.claim()
        self.assertFalse(next_claim['read_only'])
        self.assertTrue(self.store.gate(self.body(next_claim, stage='preflight'))['allowed'])

    def test_active_authorization_preview_can_be_explicitly_approved_on_same_task(self):
        created = self.store.create(dict(request_id='active-auth', kind='authorization', hotel='Hotel', accounts=['new123'], allow_write=True))['task']
        claim = self.claim()
        preview = {'mode': 'authorize_existing', 'activity_id': '1234567890123456789',
                   'fingerprint': 'a' * 64, 'accounts': ['new123'],
                   'products': [{'id': '10', 'price_cents': 9900, 'stock_per_creator': 2000}]}
        awaiting = self.store.report(self.body(claim, status='needs_input', result={'text': '缺少授权'}, details={'preview': preview}))['task']
        self.assertTrue(awaiting['read_only'])
        params = {'action': 'authorize_existing', 'confirmed': True,
                  'activity_id': preview['activity_id'], 'fingerprint': preview['fingerprint']}
        resumed = self.store.resume(created['id'], {'expected_revision': 1, 'params': params})['task']
        self.assertEqual(resumed['id'], created['id'])
        self.assertEqual(resumed['revision'], 2)
        self.assertFalse(resumed['read_only'])
        self.assertTrue(resumed['payload']['allow_write'])
        self.assertEqual(resumed['payload']['accounts'], ['new123'])
        claimed = self.claim()
        self.assertFalse(claimed['read_only'])
        self.assertTrue(self.store.gate(self.body(claimed, stage='preflight'))['allowed'])

    def test_active_authorization_approval_rejects_changed_or_blocked_preview(self):
        cases = [
            ({'mode': 'authorize_existing', 'activity_id': '1234567890123456789', 'fingerprint': 'a' * 64},
             {'activity_id': '1234567890123456780'}, 'preview_changed'),
            ({'mode': 'authorize_existing', 'activity_id': '1234567890123456789', 'fingerprint': 'a' * 64, 'blocked': True},
             {}, 'preview_changed'),
        ]
        for index, (preview, change, code) in enumerate(cases):
            with self.subTest(index=index):
                temp = tempfile.TemporaryDirectory()
                try:
                    store = gw.GatewayStore(Path(temp.name) / 'queue.sqlite3', worker_id='mac-one', clock=self.clock)
                    task = store.create(dict(request_id=f'auth-{index}', kind='authorization', hotel='Hotel', accounts=['new123']))['task']
                    claim = store.claim('mac-one')['task']
                    store.report(dict(worker_id='mac-one', task_id=claim['id'], lease_token=claim['lease_token'],
                                      revision=claim['revision'], status='needs_input', result={}, details={'preview': preview}))
                    params = {'action': 'authorize_existing', 'confirmed': True,
                              'activity_id': '1234567890123456789', 'fingerprint': 'a' * 64, **change}
                    with self.assertRaises(gw.APIError) as cm:
                        store.resume(task['id'], {'expected_revision': 1, 'params': params})
                    self.assertEqual(cm.exception.code, code)
                finally:
                    temp.cleanup()

    def test_active_authorization_approval_cannot_revive_expired_decision_window(self):
        created = self.store.create(dict(request_id='active-auth', kind='authorization', hotel='Hotel', accounts=['new123']))['task']
        claim = self.claim()
        preview = {'mode': 'authorize_existing', 'activity_id': '1234567890123456789', 'fingerprint': 'a' * 64}
        self.store.report(self.body(claim, status='needs_input', result={}, details={'preview': preview}))
        self.clock.advance(gw.TASK_SECONDS + 1)
        params = {'action': 'authorize_existing', 'confirmed': True,
                  'activity_id': preview['activity_id'], 'fingerprint': preview['fingerprint']}
        self.error('task_expired', lambda: self.store.resume(created['id'], {'expected_revision': 1, 'params': params}))

    def test_schedule_rejects_unverified_template_nonfinite_bool_and_price_fields(self):
        task, params = self.schedule_waiting_task()
        cases = [('preview_changed', {'fingerprint': 'b' * 64}), ('template_id', {'template_id': 1234567890123456789}),
                 ('confirmation', {'confirmed': 1}), ('confirmation', {'confirmed': False}),
                 ('schedule_time', {'start_time': True}), ('schedule_time', {'end_time': float('inf')}),
                 ('schedule_time', {'start_time': self.clock() - 1}), ('schedule_time', {'end_time': params['start_time']}),
                 ('immutable_target', {'price': 1}), ('schedule_fields', {'extra': 1})]
        for code, change in cases:
            with self.subTest(code=code, change=change):
                self.error(code, lambda: self.store.resume(task['id'], {'expected_revision': 1, 'params': {**params, **change}}))

    def test_schedule_confirmation_refuses_expired_original_execution_window(self):
        task, params = self.schedule_waiting_task()
        self.clock.advance(86401)
        params.update(start_time=self.clock() + 3600, end_time=self.clock() + 86400)
        self.error('task_expired', lambda: self.store.resume(task['id'], {'expected_revision': 1, 'params': params}))

    def test_schedule_may_select_one_exact_verified_candidate_without_default_preview(self):
        self.store.create(dict(request_id='authorization', kind='authorization', hotel='Hotel', accounts=['account-1']))
        task = self.claim()
        candidates = [{'template_id': '1234567890123456789', 'fingerprint': 'a' * 64, 'products': [{'price_cents': 99, 'stock_per_creator': 1}]},
                      {'template_id': '1234567890123456780', 'fingerprint': 'b' * 64, 'products': [{'price_cents': 199, 'stock_per_creator': 2}]}]
        self.report(task, 'needs_input', details={'candidates': candidates})
        params = dict(template_id=candidates[1]['template_id'], fingerprint=candidates[1]['fingerprint'], start_time=self.clock()+3600, end_time=self.clock()+86400, confirmed=True)
        resumed = self.store.resume(task['id'], {'expected_revision': 1, 'params': params})['task']
        self.assertFalse(resumed['read_only'])
        self.assertEqual(resumed['payload']['params']['template_id'], candidates[1]['template_id'])
        self.assertEqual(resumed['details']['candidates'][1]['products'], candidates[1]['products'])

    def test_duplicate_candidate_identity_is_not_silently_selected(self):
        self.store.create(dict(request_id='authorization', kind='authorization', hotel='Hotel', accounts=['account-1']))
        task = self.claim()
        candidate = {'template_id': '1234567890123456789', 'fingerprint': 'a' * 64}
        self.report(task, 'needs_input', details={'candidates': [candidate, candidate]})
        params = dict(**candidate, start_time=self.clock()+3600, end_time=self.clock()+86400, confirmed=True)
        self.error('preview_changed', lambda: self.store.resume(task['id'], {'expected_revision': 1, 'params': params}))

    def test_read_only_plan_explicit_approval_same_task_and_idempotent_revision(self):
        self.legacy_read_only(self.create())
        task = self.claim()
        self.report(task, 'needs_input', details={'reason': 'approval_required'})
        body = {'expected_revision': 1, 'params': {'confirmed': True, 'action': 'approve_plan'}}
        resumed = self.store.resume(task['id'], body)
        self.assertFalse(resumed['task']['read_only'])
        self.assertTrue(resumed['task']['payload']['allow_write'])
        self.assertEqual(resumed['task']['revision'], 2)
        self.assertEqual(resumed['task']['created'], task['created'])
        self.assertEqual(resumed['task']['payload']['plan_id'], task['payload']['plan_id'])
        self.assertEqual(self.store.resume(task['id'], body), resumed)
        reopened = gw.GatewayStore(self.db, worker_id='mac-one', clock=self.clock)
        self.assertEqual(reopened.resume(task['id'], body), resumed)
        self.error('stale_revision', lambda: self.store.resume(task['id'], {**body, 'params': {'note': 'Different'}}))

    def test_plan_approval_requires_strict_confirmation_and_optional_preview_fingerprint(self):
        self.legacy_read_only(self.create())
        task = self.claim()
        self.report(task, 'needs_input', details={'preview': {'fingerprint': 'a' * 64}})
        params = {'confirmed': True, 'action': 'approve_plan'}
        self.error('plan_confirmation', lambda: self.store.resume(task['id'], {'expected_revision': 1, 'params': params}))
        self.error('preview_changed', lambda: self.store.resume(task['id'], {'expected_revision': 1, 'params': {**params, 'fingerprint': 'b' * 64}}))
        self.error('immutable_target', lambda: self.store.resume(task['id'], {'expected_revision': 1, 'params': {**params, 'fingerprint': 'a' * 64, 'plan_id': '1234567890123456780'}}))
        self.error('plan_confirmation', lambda: self.store.resume(task['id'], {'expected_revision': 1, 'params': {**params, 'fingerprint': 'a' * 64, 'confirmed': 1}}))
        self.assertFalse(self.store.resume(task['id'], {'expected_revision': 1, 'params': {**params, 'fingerprint': 'a' * 64}})['task']['read_only'])

    def test_plan_approval_cannot_revive_expired_or_committed_task(self):
        self.legacy_read_only(self.create())
        task = self.claim()
        self.report(task, 'needs_input')
        self.clock.advance(86401)
        self.error('task_expired', lambda: self.store.resume(task['id'], {'expected_revision': 1, 'params': {'confirmed': True, 'action': 'approve_plan'}}))

    def test_expired_running_task_cannot_commit(self):
        self.create(allow_write=True)
        self.clock.advance(86390)
        task = self.claim()
        self.store.gate(self.body(task, stage='preflight'))
        self.clock.advance(11)
        self.error('task_expired', lambda: self.store.gate(self.body(task, stage='commit')))

    def test_no_lease_token_or_credential_in_public_evidence(self):
        self.create()
        task = self.claim()
        reported = self.store.report(self.body(task, status='succeeded', result={'token': 'topsecret', 'summary': 'very-private-token', 'nested': {'headers': {'Cookie': 'secret'}}}))['task']
        self.assertNotIn('lease_token', reported)
        content = json.dumps(reported)
        self.assertNotIn('very-private-token', content)
        self.assertNotIn('topsecret', content)
        self.assertEqual(reported['result']['token'], '[redacted]')
        self.assertGreater(len(self.store.audit(task['id'])['events']), 2)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.clock = FakeClock()
        cls.store = gw.GatewayStore(Path(cls.temp.name) / 'queue.db', worker_id='mac', clock=cls.clock)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), gw.make_handler(cls.store, 'user-token', 'worker-token',
                                        public_origin='https://example.test', allowed_hosts=['example.test']))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_address[1]}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)
        cls.temp.cleanup()
    def req(self, path, body=None, token=None, headers=None):
        h = {'Host': 'example.test', 'Content-Type': 'application/json'}
        if token:
            h['Authorization'] = 'Bearer ' + token
        h.update(headers or {})
        request = urllib.request.Request(self.url + path, data=None if body is None else json.dumps(body).encode(), headers=h)
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as e:
            response = e
        with response:
            return response.status, dict(response.headers), json.loads(response.read())

    def test_user_and_worker_auth_separate(self):
        self.assertEqual(self.req('/api/tasks')[0], 401)
        self.assertEqual(self.req('/api/tasks', token='worker-token')[0], 401)
        self.assertEqual(self.req('/api/worker/claim', {'worker_id': 'mac'}, token='user-token')[0], 401)
        self.assertEqual(self.req('/api/status', token='user-token')[0], 200)

    def test_host_and_origin_enforced_even_with_bearer(self):
        self.assertEqual(self.req('/api/status', token='user-token', headers={'Host': 'evil.test'})[0], 403)
        self.assertEqual(self.req('/api/status', token='user-token', headers={'Origin': 'https://evil.test'})[0], 403)

    def test_login_cookie_http_only_and_same_origin_mutation(self):
        self.assertEqual(self.req('/api/login', {'token': 'user-token'})[0], 403)
        code, headers, result = self.req('/api/login', {'token': 'user-token'}, headers={'Origin': 'https://example.test'})
        self.assertEqual(code, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        self.assertIn('Secure', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.req('/api/tasks', headers={'Cookie': cookie})[0], 200)
        body = dict(request_id='http-request', kind='inspect', plan_id='1234567890123456789')
        self.assertEqual(self.req('/api/tasks', body, headers={'Cookie': cookie})[0], 403)
        self.assertEqual(self.req('/api/tasks', body, headers={'Cookie': cookie, 'Origin': 'https://example.test'})[0], 200)
        self.assertEqual(self.req('/api/worker/claim', {'worker_id': 'mac'}, headers={'Cookie': cookie})[0], 401)
        code, headers, result = self.req('/api/logout', {}, headers={'Cookie': cookie, 'Origin': 'https://example.test'})
        self.assertEqual(code, 200)
        self.assertIn('Secure', headers['Set-Cookie'])
        self.assertEqual(self.req('/api/tasks', headers={'Cookie': cookie})[0], 401)

    def test_plan_post_requires_allow_write_and_echoes_mode(self):
        code, _, body = self.req('/api/tasks', {'request_id': 'plan-omit', 'kind': 'plan', 'plan_id': '1234567890123456789'}, token='user-token')
        self.assertEqual(code, 400)
        self.assertEqual(body['error'], 'plan_write_required')
        code, _, body = self.req('/api/tasks', {'request_id': 'plan-write', 'kind': 'plan', 'plan_id': '1234567890123456789', 'allow_write': True}, token='user-token')
        self.assertEqual(code, 200)
        self.assertEqual(body['task']['mode'], 'write')
        self.assertFalse(body['task']['read_only'])

    def test_login_rate_limit_trusts_loopback_x_real_ip_only(self):
        self.assertEqual(gw.login_client_ip('127.0.0.1', '203.0.113.8'), '203.0.113.8')
        self.assertEqual(gw.login_client_ip('::1', '203.0.113.8'), '203.0.113.8')
        self.assertEqual(gw.login_client_ip('127.0.0.1', '203.0.113.8, 198.51.100.1'), '127.0.0.1')
        self.assertEqual(gw.login_client_ip('127.0.0.1', None), '127.0.0.1')
        self.assertEqual(gw.login_client_ip('203.0.113.5', '198.51.100.1'), '203.0.113.5')
        spoof = {'Origin': 'https://example.test', 'X-Forwarded-For': '198.51.100.50'}
        for _ in range(10):
            self.assertEqual(self.req('/api/login', {'token': 'nope'}, headers={**spoof, 'X-Real-IP': '203.0.113.10'})[0], 401)
        self.assertEqual(self.req('/api/login', {'token': 'nope'}, headers={**spoof, 'X-Real-IP': '203.0.113.10'})[0], 429)
        self.assertEqual(self.req('/api/login', {'token': 'user-token'}, headers={'Origin': 'https://example.test', 'X-Real-IP': '203.0.113.11', 'X-Forwarded-For': '203.0.113.10'})[0], 200)

    def test_gateway_refuses_start_without_worker_id(self):
        env = os.environ.copy()
        env.pop('GATEWAY_WORKER_ID', None)
        env['GATEWAY_USER_TOKEN'] = 'user-token-value'
        env['GATEWAY_WORKER_TOKEN'] = 'worker-token-value'
        env['GATEWAY_PUBLIC_ORIGIN'] = 'https://example.test'
        with tempfile.TemporaryDirectory() as temp:
            proc = subprocess.run([sys.executable, str(SOURCE), '--db', str(Path(temp) / 'queue.sqlite3')],
                                   env=env, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('GATEWAY_WORKER_ID', proc.stderr)
        self.assertNotIn('user-token-value', proc.stderr)
        self.assertNotIn('worker-token-value', proc.stderr)

    def test_invalid_json_rejected_and_no_secret_echo(self):
        code, headers, result = self.req('/api/login', {'token': '\u79d8\u5bc6'}, headers={'Origin': 'https://example.test'})
        self.assertEqual(code, 401)
        self.assertNotIn('\u79d8\u5bc6', json.dumps(result, ensure_ascii=False))
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.req('/api/tasks', [], token='user-token')[0], 400)


class StaticBundleContractTests(unittest.TestCase):
    def test_plan_link_parser_handles_official_share_layers_and_copy_wrapping(self):
        source = (Path(__file__).resolve().parents[1] / 'outputs' / 'trigger-ui' / 'app.js').read_text()
        match = re.search(r"function parsePlanId\(input\) \{.*?^\}", source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match)
        program = 'class UserError extends Error {}\n' + match.group(0) + r'''
const id = '7696422786704967690';
const direct = 'https://life.douyin.com/h5/alliance/merchant/plan/oriented/info?enter_from=institution_platform&task_id=' + id + '&mode=broker_entrance';
const deep = 'snssdk299467://webview?trans_status_bar=1&hide_nav_bar=1&disable_bounces=1&should_full_screen=1&show_loading=0&hybrid_sdk_version=bullet&use_bdx=1&disable_swipe=0&url=' + encodeURIComponent(direct);
const shared = 'https://life.douyin.com/h5/download?redirect_url=' + encodeURIComponent(deep);
// The reported input has a newline between '%' and '2526mode'.
const wrapped = shared.replace('%2526mode', '%\n2526mode');
const valid = [id, direct, deep, shared, wrapped, encodeURIComponent(shared),
  encodeURIComponent(encodeURIComponent(shared)), direct + '&task_id=' + id];
const invalid = [
  'https://example.test/?task_id=' + id,
  'https://life.douyin.com.example.test/h5/alliance/merchant/plan/oriented/info?task_id=' + id,
  'https://life.douyin.com/h5/other?task_id=' + id,
  direct + '&task_id=7696422786704967691',
  direct + '&plan_id=7696422786704967691',
  direct.replace(id, id + '00'), direct.replace(id, id.slice(0, 17)),
  shared.replace('%2526mode', '%QZmode'),
  shared + '&redirect_url=' + encodeURIComponent(deep),
  'https://life.douyin.com/h5/download?redirect_url=' + encodeURIComponent('https://example.test/?task_id=' + id),
  'snssdk299467://other?url=' + encodeURIComponent(direct),
  direct.replace('https://', 'http://'), direct.replace('https://', 'https://user@'),
  direct + '#task_id=' + id, id.slice(0, 8) + ' ' + id.slice(8), '', 'x'.repeat(16385)
];
process.stdout.write(JSON.stringify({
  valid: valid.map(input => parsePlanId(input)),
  invalid: invalid.map(input => { try { parsePlanId(input); return false; } catch (e) { return e instanceof UserError; } })
}));
'''
        result = subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True)
        results = json.loads(result.stdout)
        self.assertEqual(results['valid'], ['7696422786704967690'] * 8)
        self.assertTrue(all(results['invalid']), results['invalid'])
        self.assertIn("payload.plan_id = parsePlanId($('#link').value)", source)

    def test_index_assets_load_through_the_same_gateway_contract(self):
        """The gateway deliberately rejects query strings, including on static files."""
        with tempfile.TemporaryDirectory() as temp:
            store = gw.GatewayStore(Path(temp) / 'queue.db', worker_id='mac')
            static = Path(__file__).resolve().parents[1] / 'outputs' / 'trigger-ui'
            server = ThreadingHTTPServer(('127.0.0.1', 0), gw.make_handler(
                store, 'user-token', 'worker-token', public_origin='https://example.test',
                allowed_hosts=['example.test'], static=static))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_address[1]}'
                def fetch(path):
                    request = urllib.request.Request(base + path, headers={
                        'Host': 'example.test', 'Authorization': 'Bearer user-token'})
                    with urllib.request.urlopen(request, timeout=3) as response:
                        return response.status, response.read()
                status, body = fetch('/')
                self.assertEqual(status, 200)
                refs = re.findall(rb'(?:src|href)="((?:app\.js|style\.css)[^"]*)"', body)
                self.assertEqual(sorted(refs), [b'app.js', b'style.css'])
                for ref in refs:
                    self.assertEqual(fetch('/' + ref.decode())[0], 200)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_product_relation_requires_matching_product_and_sku(self):
        source = (Path(__file__).resolve().parents[1] / 'outputs' / 'trigger-ui' / 'app.js').read_text()
        helpers = '\n'.join(line for line in source.splitlines()
                            if line.startswith('function productKey(') or line.startswith('function productRelation('))
        self.assertIn('function productKey(', helpers)
        self.assertIn('function productRelation(', helpers)
        program = helpers + r'''
const oldProductKeys = new Set([productKey({id: 'same-product', sku_id: 'old-sku'})]);
process.stdout.write(JSON.stringify([
  productRelation(oldProductKeys, {id: 'same-product', sku_id: 'old-sku'}),
  productRelation(oldProductKeys, {id: 'same-product', sku_id: 'new-sku'})
]));
'''
        result = subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout), ['旧模板精确命中', '当前候选 · 未授权'])

    def test_task_request_id_retries_failures_but_rotates_after_success(self):
        source = (Path(__file__).resolve().parents[1] / 'outputs' / 'trigger-ui' / 'app.js').read_text()
        match = re.search(r"async function submitTask\(payload\) \{.*?^\}", source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match)
        program = match.group(0) + r'''
let pendingRequest = null;
const calls = [];
let fail = true;
async function api(path, body) {
  if (path !== 'tasks') throw new Error('unexpected path');
  calls.push(body.request_id);
  if (fail) { fail = false; throw new Error('network unavailable'); }
  return {duplicate: false};
}
(async () => {
  try { await submitTask({kind: 'authorization'}); } catch (_) {}
  await submitTask({kind: 'authorization'});
  await submitTask({kind: 'authorization'});
  process.stdout.write(JSON.stringify(calls));
})().catch(error => { console.error(error); process.exit(1); });
'''
        result = subprocess.run(['node', '-e', program], check=True, capture_output=True, text=True)
        calls = json.loads(result.stdout)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], calls[1])
        self.assertNotEqual(calls[1], calls[2])


if __name__ == '__main__':
    unittest.main()
