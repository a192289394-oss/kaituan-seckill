import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
from execution_store import Store,TaskCancelled
import web_catalog as merchant_catalog
import native_plan_executor as executor
from native_plan import inspect_plan
from native_plan_journal import prepare,PlanPermit,load
from native_commit import NativeDispatchDenied
from native_webview_api import NativeWebViewApi,SubmissionUncertain
from pc_executor import NeedsReview
from test_native_plan import PLAN,DRAFT,PRODUCTS,TARGET,response


class PlanExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'queue.sqlite3')
        self.now=time.time();self.cfg={'max_task_age_seconds':1800}
        self.task={'task_id':PLAN,'created':self.now,'stage':'queued','hotel':'Synthetic'}
        with self.store.connect() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)',
                (PLAN,'Synthetic','test','running','queued','','test','test',self.now,self.now))
        merchant_catalog.bind_target(self.store,self.task,TARGET)
        self.pending=response();self.pending['task_detail']['data']['task_confirm_end_time']=self.now+3600
        self.pending['task_draft_detail']['task']['data']['task_confirm_end_time']=self.now+3600
        o=inspect_plan(PLAN,TARGET,PRODUCTS,self.pending)
        self.expected={'root':TARGET['root_id'],'snapshot':o['snapshot'],'fingerprint':o['fingerprint'],
            'body':{'operation_type':5,'task_id':PLAN,'task_draft_id':DRAFT}}
        self.api=object.__new__(NativeWebViewApi);self.api.expected_root=TARGET['root_id']
        self.api.assert_scope=Mock();self.api._fetch_raw=Mock(return_value='{"status_code":0}')
        self.api.read=Mock(side_effect=self.read)

    def tearDown(self):self.tmp.cleanup()
    def read(self,path,params=None,body=None):
        if path.endswith('/detail/get/'):d=copy.deepcopy(self.pending)
        elif path.endswith('/permission/check/'):d={'status_code':0,'has_perm':True}
        elif path.endswith('/activity/get/'):d={'status_code':0,'ActivityInfoList':[]}
        else:raise AssertionError(path)
        return json.dumps(d),d
    def permit(self):return PlanPermit(self.store.path,self.task,self.expected,1800)
    def gate(self):
        self.store.submission_gate(self.task,self.cfg,'api_prepared')
        prepare(self.store.path,self.task,self.expected)
        self.store.submission_gate(self.task,self.cfg,'confirming')
    def execute(self,allow=True):return executor.run(self.task,self.cfg,self.store,TARGET,PRODUCTS,self.api,allow)
    def sql(self,query,args=()):
        with self.store.connect() as db:db.execute(query,args)
    def active(self):
        self.pending['task_detail']['status']=3
        self.pending['task_draft_detail']['task_draft_status']=2

    def test_no_journal_no_send(self):
        with self.assertRaises(NativeDispatchDenied):self.api.submit_plan_once(self.expected['body'],self.permit())
        self.api._fetch_raw.assert_not_called()
    def test_once_even_after_restart(self):
        self.gate();self.api.submit_plan_once(self.expected['body'],self.permit())
        with self.assertRaises(NativeDispatchDenied):self.api.submit_plan_once(self.expected['body'],self.permit())
        self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_uncertain_timeout_never_resends(self):
        self.gate();self.api._fetch_raw.side_effect=TimeoutError()
        with self.assertRaises(SubmissionUncertain):self.api.submit_plan_once(self.expected['body'],self.permit())
        self.assertEqual(self.execute()['status'],'waiting_review')
        self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_cancel_after_prepare_blocks_dispatch(self):
        self.gate();self.sql('INSERT INTO task_controls VALUES(?,?,?)',(PLAN,self.now+1,'test_cancel'))
        with self.assertRaises(NativeDispatchDenied):self.api.submit_plan_once(self.expected['body'],self.permit())
        self.api._fetch_raw.assert_not_called()
    def test_changed_generation_blocks_dispatch(self):
        self.gate();self.sql('UPDATE tasks SET created=created+1')
        with self.assertRaises(NativeDispatchDenied):self.permit().consume(TARGET['root_id'],self.expected['body'])
    def test_changed_binding_blocks_dispatch(self):
        self.gate();self.sql('UPDATE task_targets SET data=?',(json.dumps({'root_id':'999'}),))
        with self.assertRaises(NativeDispatchDenied):self.permit().consume(TARGET['root_id'],self.expected['body'])
    def test_changed_packet_blocks_dispatch(self):
        self.gate();body=dict(self.expected['body'],operation_type=4)
        with self.assertRaises(NativeDispatchDenied):self.permit().consume(TARGET['root_id'],body)
    def test_expiry_at_final_boundary(self):
        self.gate()
        with patch('native_plan_journal.time.time',return_value=self.now+1801):
            with self.assertRaises(NativeDispatchDenied):self.permit().consume(TARGET['root_id'],self.expected['body'])
    def test_plan_deadline_at_final_boundary(self):
        self.expected['snapshot']['confirm_deadline']=self.now+10;self.gate()
        with patch('native_plan_journal.time.time',return_value=self.now+10):
            with self.assertRaises(NativeDispatchDenied):self.permit().consume(TARGET['root_id'],self.expected['body'])
    def test_prepare_cannot_reset_dispatched_journal(self):
        self.gate();self.api.submit_plan_once(self.expected['body'],self.permit())
        self.sql("UPDATE tasks SET stage='queued'")
        with self.assertRaises(NativeDispatchDenied):prepare(self.store.path,self.task,self.expected)
    def test_new_generation_cannot_erase_uncertain_old_dispatch(self):
        self.gate();self.api.submit_plan_once(self.expected['body'],self.permit())
        self.task['created']+=1
        self.sql("UPDATE tasks SET stage='queued',created=created+1")
        merchant_catalog.bind_target(self.store,self.task,TARGET)
        with self.assertRaises(NativeDispatchDenied):prepare(self.store.path,self.task,self.expected)
    def test_new_branch_dispatches_once_and_recovery_reviews_twice(self):
        self.assertEqual(self.execute()['status'],'waiting_review')
        self.assertIsNotNone(load(self.store.path,self.task)['dispatched_at'])
        self.active();self.api.read.reset_mock()
        r=self.execute();self.assertEqual(r['status'],'succeeded');self.assertEqual(len(r['reviews']),2)
        self.assertEqual(self.api.read.call_count,2);self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_active_branch_never_writes(self):
        self.active();r=self.execute();self.assertEqual(r['status'],'succeeded');self.assertEqual(len(r['reviews']),2)
        self.api._fetch_raw.assert_not_called()
    def test_changed_draft_after_commit_not_claimed_success(self):
        self.execute();self.active()
        for t in [self.pending['task_detail'],self.pending['task_draft_detail']['task']]:t['data']['task_draft_id']='9000000000000000999'
        self.pending['task_draft_detail']['task_draft_id']='9000000000000000999'
        self.assertEqual(self.execute()['status'],'waiting_review');self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_changed_draft_terms_between_gates_no_send(self):
        original=self.read;count=0
        def read(path,params=None,body=None):
            nonlocal count
            if path.endswith('/detail/get/'):
                count+=1
                if count==2:
                    self.pending['task_draft_detail']['task']['data']['product_list'][0]['commission_rate']+=1
            return original(path,params,body)
        self.api.read.side_effect=read
        with self.assertRaises(NeedsReview):self.execute()
        self.api._fetch_raw.assert_not_called()
    def test_changed_draft_terms_after_commit_waits_without_resend(self):
        self.execute();self.active()
        self.pending['task_draft_detail']['task']['data']['product_list'][0]['actual_price']+=1
        self.assertEqual(self.execute()['status'],'waiting_review')
        self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_legacy_journal_retains_existing_readback_contract(self):
        self.gate();self.api.submit_plan_once(self.expected['body'],self.permit());self.active()
        legacy=copy.deepcopy(self.expected);legacy['snapshot'].pop('draft_terms')
        self.sql('UPDATE native_plan_journal SET data=?',(json.dumps(legacy),))
        result=self.execute()
        self.assertEqual(result['status'],'succeeded');self.assertEqual(len(result['reviews']),2)
        self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_changed_terms_between_gates_no_send(self):
        original=self.read;count=0
        def read(path,params=None,body=None):
            nonlocal count
            if path.endswith('/detail/get/'):
                count+=1
                if count==2:self.pending['task_detail']['data']['product_list'][0]['commission_rate']+=1
            return original(path,params,body)
        self.api.read.side_effect=read
        with self.assertRaises(NeedsReview):self.execute()
        self.api._fetch_raw.assert_not_called()
    def test_no_write_permission_means_no_dispatch(self):
        self.assertEqual(self.execute(False)['status'],'needs_review');self.api._fetch_raw.assert_not_called()
    def test_permission_revoked_between_gates_no_send(self):
        original=self.read;count=0
        def read(path,params=None,body=None):
            nonlocal count
            if path.endswith('/permission/check/'):
                count+=1
                if count==2:return '',{'status_code':0,'has_perm':False}
            return original(path,params,body)
        self.api.read.side_effect=read
        with self.assertRaises(NeedsReview):self.execute()
        self.api._fetch_raw.assert_not_called()
    def test_marketing_changes_between_gates_no_send(self):
        original=self.read;count=0
        def read(path,params=None,body=None):
            nonlocal count
            if path.endswith('/activity/get/'):
                count+=1
                if count==2:return '',{'status_code':0,'ActivityInfoList':[{'MarketingActivityID':'9000000000000000789','MarketingActivityType':20}]}
            return original(path,params,body)
        self.api.read.side_effect=read
        with self.assertRaises(NeedsReview):self.execute()
        self.api._fetch_raw.assert_not_called()
    def test_missing_journal_after_final_stage_no_send(self):
        self.task['stage']='confirming';self.active()
        self.assertEqual(self.execute()['status'],'needs_review');self.api._fetch_raw.assert_not_called()


if __name__=='__main__':unittest.main()
