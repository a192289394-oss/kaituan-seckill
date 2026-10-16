import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
import pc_jobs
from pc_executor import NeedsReview
from native_activity import authorization_payload,lookup_body,resolve_creators,verify_precheck,LOOKUP_PATH,PRECHECK_PATH
from native_commit import ActivityPermit,NativeDispatchDenied
from native_webview_api import NativeWebViewApi,SubmissionUncertain,wire_value
import native_activity_executor


def source():
    now=int(time.time())
    return {'activity_id':9000000000000000123,'activity_name':'Synthetic','activity_status':2,
        'coupon_type':20,'discount_type':'merchant_live_flash_promotion','start_time':now-100,'end_time':now+86400,
        'sell_out_style':1,'extra_map':{'auto_live_flash_config':'preserve'},
        'anchor_info_list':[{'uid':'123','douyin_id':'old123','identity_type':1}],
        'sku_list':[{'sku_id':456,'product_id':789,'fixed_price':9900,'left_quantity':90,
            'anchor_list':[{'uid':'123','identity_type':1,'fixed_price':9900,'total_quantity':100,'left_quantity':90,'coupon_id':9000000000000000789}]}]}


class PayloadTests(unittest.TestCase):
    def creators(self):return {'new123':{'uid':'234','douyin_id':'new123','identity_type':1}}

    def test_edit_preserves_old_coupon_price_inventory_and_window(self):
        s=source();before=copy.deepcopy(s)
        p=authorization_payload(s,['new123'],self.creators(),'10001')
        a=p['body']['activity'];grants=a['sku_list'][0]['anchor_list']
        self.assertEqual(s,before)
        self.assertEqual(p['mode'],'edit');self.assertEqual(a['activity_id'],'9000000000000000123')
        self.assertEqual(grants[0]['coupon_id'],'9000000000000000789')
        self.assertEqual((grants[0]['fixed_price'],grants[0]['total_quantity']),(9900,100))
        self.assertNotIn('left_quantity',grants[0])
        self.assertEqual((grants[1]['fixed_price'],grants[1]['total_quantity']),(9900,100))
        self.assertEqual((a['start_time'],a['end_time']),(s['start_time'],s['end_time']))
        self.assertEqual(a['extra_map'],s['extra_map'])

    def test_copy_never_duplicates_existing_actors_or_coupons(self):
        p=authorization_payload(source(),['new123'],self.creators(),'10001',max_anchors=1)
        a=p['body']['activity'];self.assertEqual(p['mode'],'copy')
        self.assertNotIn('activity_id',a);self.assertEqual([x['uid'] for x in a['anchor_info_list']],['234'])
        self.assertEqual([x['uid'] for x in a['sku_list'][0]['anchor_list']],['234'])
        self.assertNotIn('coupon_id',a['sku_list'][0]['anchor_list'][0])

    def test_existing_creator_requires_recheck_no_unchanged_save(self):
        a=self.creators();a['new123']['uid']='123'
        with self.assertRaises(NeedsReview):authorization_payload(source(),['new123'],a,'10001')

    def test_wrong_template_type_or_inactive_stops(self):
        for key,value in [('activity_status',3),('coupon_type',10),('discount_type','other')]:
            s=source();s[key]=value
            with self.assertRaises(NeedsReview):authorization_payload(s,['new123'],self.creators(),'10001')

    def test_different_prices_or_stock_not_guessed(self):
        s=source();s['sku_list'][0]['anchor_list'].append({'uid':'111','identity_type':1,'fixed_price':9901,'total_quantity':100})
        with self.assertRaises(NeedsReview):authorization_payload(s,['new123'],self.creators(),'10001')

    def test_lookup_exact_case_and_source_id(self):
        b=lookup_body(source(),['20209988M','50749840482'])
        self.assertEqual(b['douyin_ids'],'20209988M 50749840482');self.assertEqual(b['user_type'],3)
        self.assertEqual(b['exist_activity_id'],'9000000000000000123')

    def test_lookup_result_full_exact_mapping(self):
        d={'status_code':0,'success_anchor_list':[{'uid':234,'douyin_id':'new123','user_type':3}]}
        self.assertEqual(resolve_creators(d,['new123']),self.creators())
        for bad in [{'status_code':0,'success_anchor_list':[]},
                    {'status_code':0,'success_anchor_list':[{'uid':'234','douyin_id':'New123','user_type':3}]},
                    {'status_code':0,'success_anchor_list':[{'uid':'234','douyin_id':'new123','user_type':1}]}]:
            with self.assertRaises(NeedsReview):resolve_creators(bad,['new123'])

    def test_wire_preserves_int64_values_recursively(self):
        self.assertEqual(wire_value({'id':9000000000000000123,'list':[9000000000000000456,True,9900]}),
                         {'id':'9000000000000000123','list':['9000000000000000456',True,9900]})

    def test_readback_aggregate_is_not_per_creator_save_quantity(self):
        s=source();s['sku_list'][0]['total_quantity']=42000
        s['sku_list'][0]['anchor_list'][0]['total_quantity']=2000
        p=authorization_payload(s,['new123'],self.creators(),'10001')
        sku=p['body']['activity']['sku_list'][0]
        self.assertEqual(sku['total_quantity'],2000)
        self.assertEqual([g['total_quantity'] for g in sku['anchor_list']],[2000,2000])
        self.assertEqual(s['sku_list'][0]['total_quantity'],42000)

    def test_http_success_with_precheck_errors_is_not_ready(self):
        verify_precheck({'status_code':0,'pre_check_result':{}})
        for key in ['pre_check_result','sku_block_msg_map','product_validation_result','double_check_info']:
            r={'status_code':0,'pre_check_result':{},key:{'blocked':'sku'}}
            with self.assertRaises(NeedsReview):verify_precheck(r)

    def test_authorization_fingerprint_is_stable_for_readback_counters_but_binds_business_terms(self):
        s=source();requested=['new123'];missing=['new123']
        s['sku_list'][0]['product_info']={'product_name':'Room','sold_count':0,
            'image_list':['https://cdn.example/signed-old']}
        before=native_activity_executor.authorization_fingerprint(s,requested,missing)
        s['update_time']=999;s['sku_list'][0]['left_quantity']=1
        s['sku_list'][0]['product_info']['sold_count']=100
        s['sku_list'][0]['product_info']['image_list']=['https://cdn.example/signed-a']
        self.assertEqual(before,native_activity_executor.authorization_fingerprint(s,requested,missing))
        s['sku_list'][0]['anchor_list'][0]['fixed_price']+=1
        self.assertNotEqual(before,native_activity_executor.authorization_fingerprint(s,requested,missing))


class NativeCommitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'queue.sqlite3';self.now=time.time()
        self.job={'id':'synthetic_1','created':self.now,'accounts':'["new123"]','stage':'created'}
        with pc_jobs.connection(self.db) as db:
            db.execute('CREATE TABLE activity_jobs(id TEXT PRIMARY KEY,status TEXT,stage TEXT,created REAL,target TEXT,accounts TEXT,updated REAL)')
            pc_jobs.init_schema(db)
            db.execute('INSERT INTO activity_jobs VALUES(?,?,?,?,?,?,?)',('synthetic_1','running','created',self.now,'{"root_id":"10001"}','["new123"]',self.now))
        preview=authorization_payload(source(),['new123'],{'new123':{'uid':'234','douyin_id':'new123','identity_type':1}},'10001')
        self.expected={'root':'10001','accounts':['new123'],'source':source(),'preview':preview}

    def tearDown(self):self.tmp.cleanup()
    def gate(self):
        pc_jobs.prepare(self.db,self.job,self.expected);pc_jobs.submission_gate(self.db,self.job,1800,self.expected)
    def permit(self):return ActivityPermit(self.db,self.job,self.expected)
    def confirmation(self,preview):
        return {'action':'authorize_existing','confirmed':True,
            'activity_id':preview['activity_id'],'fingerprint':preview['fingerprint']}
    def api(self):
        a=object.__new__(NativeWebViewApi);a.expected_root='10001';a.assert_scope=Mock();a._fetch_raw=Mock(return_value='{"status_code":0,"activity_id":9000000000000000123}')
        return a

    def test_no_durable_gate_no_request(self):
        a=self.api()
        with self.assertRaises(NativeDispatchDenied):a.submit_activity_once(self.expected['preview']['body'],self.permit())
        a._fetch_raw.assert_not_called()

    def test_exactly_once_including_new_permit_after_restart(self):
        self.gate();a=self.api();a.submit_activity_once(self.expected['preview']['body'],self.permit())
        with self.assertRaises(NativeDispatchDenied):a.submit_activity_once(self.expected['preview']['body'],self.permit())
        self.assertEqual(a._fetch_raw.call_count,1)

    def test_timeout_is_review_only_never_resend(self):
        self.gate();a=self.api();a._fetch_raw.side_effect=TimeoutError()
        with self.assertRaises(SubmissionUncertain):a.submit_activity_once(self.expected['preview']['body'],self.permit())
        with self.assertRaises(NativeDispatchDenied):a.submit_activity_once(self.expected['preview']['body'],self.permit())
        self.assertEqual(a._fetch_raw.call_count,1)

    def test_cancel_before_dispatch_wins(self):
        self.gate()
        with pc_jobs.connection(self.db) as db:db.execute("UPDATE activity_jobs SET status='cancelled'")
        a=self.api()
        with self.assertRaises(NativeDispatchDenied):a.submit_activity_once(self.expected['preview']['body'],self.permit())
        a._fetch_raw.assert_not_called()

    def test_mutated_packet_or_root_cannot_use_committed_preview(self):
        self.gate();body=copy.deepcopy(self.expected['preview']['body']);body['activity']['sku_list'][0]['fixed_price']+=1
        with self.assertRaises(NativeDispatchDenied):self.permit().consume('10001',body)
        with self.assertRaises(NativeDispatchDenied):self.permit().consume('10002',self.expected['preview']['body'])

    def test_source_changes_or_regeneration_prevent_send(self):
        self.gate()
        with pc_jobs.connection(self.db) as db:db.execute('UPDATE activity_jobs SET created=created+1')
        with self.assertRaises(NativeDispatchDenied):self.permit().consume('10001',self.expected['preview']['body'])

    def test_expiry_between_the_two_gates_prevents_dispatch(self):
        self.gate()
        with patch('native_commit.time.time',return_value=self.now+1801):
            with self.assertRaises(NativeDispatchDenied):self.permit().consume('10001',self.expected['preview']['body'])

    def test_existing_branch_uses_fresh_independent_reads_not_submit(self):
        s=source();s['anchor_info_list'][0]['douyin_id']='new123'
        a=self.api();calls=[]
        def read(path,params=None,body=None):
            calls.append(path)
            if path.endswith('/list'):
                d={'status_code':0,'activities':[s],'pagination':{'has_more':False}}
            else:d={'status_code':0,'activity':s}
            return json.dumps(d),d
        a.read=read;a.submit_activity_once=Mock()
        result=native_activity_executor.run({'job':self.job,'database':self.db,'allow_write':False,'max_age':1800},a)
        self.assertEqual(result['status'],'succeeded');self.assertEqual(len(result['reviews']),2)
        self.assertEqual(calls.count('/life/marketing/v1/minus_activity/list'),3)
        a.submit_activity_once.assert_not_called()

    def test_new_branch_dispatches_once_and_restores_to_read_only(self):
        s=self.expected['source'];a=self.api();calls=[]
        def read(path,params=None,body=None):
            calls.append(path)
            if path.endswith('/list'):d={'status_code':0,'activities':[s],'pagination':{'has_more':False}}
            elif path.endswith('/info'):d={'status_code':0,'activity':s}
            elif path==LOOKUP_PATH:d={'status_code':0,'success_anchor_list':[{'uid':'234','douyin_id':'new123','user_type':3}]}
            elif path==PRECHECK_PATH:d={'status_code':0,'pre_check_result':{}}
            else:raise AssertionError(path)
            return json.dumps(d),d
        a.read=read;context={'job':self.job,'database':self.db,'allow_write':True,'max_age':1800}
        discovered=native_activity_executor.run(context,a)
        self.assertEqual(discovered['status'],'needs_input')
        preview=discovered['details']['preview']
        self.assertEqual(preview['mode'],'authorize_existing')
        self.assertEqual(preview['activity_id'],'9000000000000000123')
        self.assertEqual(preview['requested_accounts'],['new123'])
        self.assertEqual(preview['missing_accounts'],['new123'])
        self.assertEqual(preview['end_time'],s['end_time'])
        self.assertEqual(preview['products'],[{'id':'789','sku_id':'456','name':'商品 789',
            'price_cents':9900,'stock_per_creator':100}])
        self.assertEqual(len(preview['fingerprint']),64)
        self.assertNotIn(LOOKUP_PATH,calls);self.assertNotIn(PRECHECK_PATH,calls)
        a._fetch_raw.assert_not_called();self.assertIsNone(pc_jobs.load_journal(self.db,self.job))
        self.assertEqual(native_activity_executor.run(context,a,self.confirmation(preview))['status'],'waiting_review')
        self.assertEqual(a._fetch_raw.call_count,1)
        write_preflight_calls=sum(path in (LOOKUP_PATH,PRECHECK_PATH) for path in calls)
        self.assertEqual(native_activity_executor.run(context,a)['status'],'waiting_review')
        self.assertEqual(sum(path in (LOOKUP_PATH,PRECHECK_PATH) for path in calls),write_preflight_calls)
        self.assertEqual(a._fetch_raw.call_count,1)

    def test_full_preview_changed_after_precheck_never_dispatches(self):
        s=self.expected['source'];a=self.api()
        def read(path,params=None,body=None):
            if path.endswith('/list'):d={'status_code':0,'activities':[s],'pagination':{'has_more':False}}
            elif path.endswith('/info'):d={'status_code':0,'activity':s}
            elif path==LOOKUP_PATH:d={'status_code':0,'success_anchor_list':[{'uid':'234','douyin_id':'new123','user_type':3}]}
            elif path==PRECHECK_PATH:
                s['sku_list'][0]['anchor_list'][0]['coupon_id']=9000000000000000999
                d={'status_code':0,'pre_check_result':{}}
            else:raise AssertionError(path)
            return json.dumps(d),d
        a.read=read
        context={'job':self.job,'database':self.db,'allow_write':True,'max_age':1800}
        discovered=native_activity_executor.run(context,a)
        result=native_activity_executor.run(context,a,self.confirmation(discovered['details']['preview']))
        self.assertEqual(result['status'],'queued');a._fetch_raw.assert_not_called()
        self.assertIsNone(pc_jobs.load_journal(self.db,self.job))

    def test_changed_frozen_activity_is_rejected_before_lookup_or_precheck(self):
        s=self.expected['source'];a=self.api();calls=[]
        def read(path,params=None,body=None):
            calls.append(path)
            if path.endswith('/list'):d={'status_code':0,'activities':[s],'pagination':{'has_more':False}}
            elif path.endswith('/info'):d={'status_code':0,'activity':s}
            elif path in (LOOKUP_PATH,PRECHECK_PATH):raise AssertionError('confirmation mismatch reached a platform write preflight')
            else:raise AssertionError(path)
            return json.dumps(d),d
        a.read=read;context={'job':self.job,'database':self.db,'allow_write':True,'max_age':1800}
        discovered=native_activity_executor.run(context,a);old=discovered['details']['preview']
        s['sku_list'][0]['anchor_list'][0]['fixed_price']=9800;s['sku_list'][0]['fixed_price']=9800
        result=native_activity_executor.run(context,a,self.confirmation(old))
        self.assertEqual(result['status'],'needs_input')
        self.assertNotEqual(result['details']['preview']['fingerprint'],old['fingerprint'])
        self.assertNotIn(LOOKUP_PATH,calls);self.assertNotIn(PRECHECK_PATH,calls)
        a._fetch_raw.assert_not_called();self.assertIsNone(pc_jobs.load_journal(self.db,self.job))

    def test_confirmation_contract_is_exact_and_cannot_smuggle_business_fields(self):
        s=self.expected['source'];a=self.api();calls=[]
        def read(path,params=None,body=None):
            calls.append(path)
            if path.endswith('/list'):d={'status_code':0,'activities':[s],'pagination':{'has_more':False}}
            elif path.endswith('/info'):d={'status_code':0,'activity':s}
            else:raise AssertionError(path)
            return json.dumps(d),d
        a.read=read;context={'job':self.job,'database':self.db,'allow_write':True,'max_age':1800}
        preview=native_activity_executor.run(context,a)['details']['preview'];valid=self.confirmation(preview)
        for bad in [dict(valid,confirmed=False),dict(valid,action='create'),
                    dict(valid,activity_id=int(preview['activity_id'])),dict(valid,price_cents=1)]:
            with self.subTest(bad=bad):
                self.assertEqual(native_activity_executor.run(context,a,bad)['status'],'needs_input')
        self.assertNotIn(LOOKUP_PATH,calls);self.assertNotIn(PRECHECK_PATH,calls)
        a._fetch_raw.assert_not_called()

    def test_copy_required_web_preview_is_always_blocked_and_never_becomes_a_create(self):
        for allow_copy in (False,True):
            with self.subTest(allow_copy=allow_copy):
                s=copy.deepcopy(self.expected['source']);grant=s['sku_list'][0]['anchor_list'][0]
                for uid in range(1000,1059):
                    s['anchor_info_list'].append({'uid':str(uid),'douyin_id':'old'+str(uid),'identity_type':1})
                    s['sku_list'][0]['anchor_list'].append({**grant,'uid':str(uid),'coupon_id':9000000000000000000+uid})
                a=self.api();calls=[]
                def read(path,params=None,body=None):
                    calls.append(path)
                    if path.endswith('/list'):d={'status_code':0,'activities':[s],'pagination':{'has_more':False}}
                    elif path.endswith('/info'):d={'status_code':0,'activity':s}
                    else:raise AssertionError(path)
                    return json.dumps(d),d
                a.read=read
                result=native_activity_executor.run({'job':self.job,'database':self.db,
                    'allow_write':True,'allow_copy':allow_copy,'max_age':1800},a)
                self.assertEqual(result['status'],'needs_input');preview=result['details']['preview']
                self.assertTrue(preview['copy_required']);self.assertTrue(preview['blocked'])
                confirmed=native_activity_executor.run({'job':self.job,'database':self.db,
                    'allow_write':True,'allow_copy':allow_copy,'max_age':1800},a,self.confirmation(preview))
                self.assertEqual(confirmed['status'],'needs_input')
                self.assertTrue(confirmed['details']['preview']['blocked'])
                self.assertTrue(result['details']['blocked']);self.assertNotIn(LOOKUP_PATH,calls)
                self.assertNotIn(PRECHECK_PATH,calls);a._fetch_raw.assert_not_called()
                self.assertIsNone(pc_jobs.load_journal(self.db,self.job))

    def test_invalid_lifetime_is_not_an_unbounded_permission(self):
        for age in [float('inf'),float('nan'),True,0]:
            with self.assertRaises(ValueError):ActivityPermit(self.db,self.job,self.expected,age)


if __name__=='__main__':unittest.main()
