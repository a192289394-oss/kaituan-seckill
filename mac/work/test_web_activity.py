import copy
import json
from datetime import datetime
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
import pc_jobs
import web_activity as web
from native_activity import LOOKUP_PATH,PRECHECK_PATH
from native_webview_api import NativeWebViewApi

OLD='9000000000000000123';NEW='9000000000000000999';ROOT='7000000000000000456'


def template(now):
    return {'activity_id':int(OLD),'merchant_act_id':'old-merchant-record','activity_name':'Synthetic expired',
        'activity_status':3,'coupon_type':20,'discount_type':web.DISCOUNT_TYPE,'start_time':int(now)-86400,
        'end_time':int(now)-10,'update_time':10,'sell_out_style':1,'extra_map':{'business_setting':'preserved'},
        'anchor_info_list':[{'uid':'123','identity_type':1,'douyin_id':'old123'}],
        'anchor_broker_info_list':[{'uid':'777','BrokerId':'old-broker'}],
        'alliance_task_relation_info':{'alliance_task_id':'old-task','broker_id':'old-broker'},
        'sku_list':[{'sku_id':456,'product_id':789,'activity_detail_id':'old-detail',
            'coupon_id':9000000000000000555,'fixed_price':9900,'total_quantity':2000,'left_quantity':0,
            'product_info':{'product_name':'Synthetic room','sold_count':0},'purchase_limit':2,
            'dss_stock_info_list':[{'total_quantity':200,'fixed_price':9000,'coupon_id':9000000000000000666}],
            'anchor_list':[{'uid':'123','identity_type':1,'fixed_price':9900,'total_quantity':2000,
                'left_quantity':0,'coupon_id':9000000000000000777}]}]}


class WebActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=time.time()
        self.store=SimpleNamespace(path=Path(self.tmp.name)/'local.sqlite3')
        self.cfg={'max_task_age_seconds':86400,'execution_max_age_seconds':86400,
            'pc_activity':{'allow_authorization_write':True,'allow_authorization_copy':False}}
        self.job={'id':'synthetic-web-job','kind':'authorization','accounts':json.dumps(['new123']),
            'target':json.dumps({'root_id':ROOT,'merchant_id':ROOT}),
            'status':'running','stage':'created','created':self.now}
        with pc_jobs.connection(self.store.path) as db:
            db.execute('CREATE TABLE activity_jobs(id TEXT PRIMARY KEY,kind TEXT,accounts TEXT,target TEXT,status TEXT,stage TEXT,created REAL,updated REAL)')
            db.execute('INSERT INTO activity_jobs VALUES(?,?,?,?,?,?,?,?)',
                tuple(self.job[k] for k in ('id','kind','accounts','target','status','stage','created'))+(self.now,))
            pc_jobs.init_schema(db)
        self.old=template(self.now);self.activities=[self.old]
        self.current_products=[{'product_id':'789','product_name':'Synthetic room','sold_start_time':int(self.now)-86400,
            'sold_end_time':int(self.now)+30*86400,'avail_qty':100000,'is_deny':False,'deny_reason':'',
            'sku_list':[{'id':'456','is_deny':False}],
            'use_date':{'use_date_type':1,'use_start_date':datetime.fromtimestamp(self.now,web.BEIJING).strftime('%Y-%m-%d'),
                'use_end_date':datetime.fromtimestamp(self.now+30*86400,web.BEIJING).strftime('%Y-%m-%d')}}]
        self.params={'template_id':OLD,'fingerprint':web.fingerprint(self.old),
            'start_time':int(self.now)+3600,'end_time':int(self.now)+7200,'confirmed':True}
        self.api=object.__new__(NativeWebViewApi);self.api.expected_root=ROOT
        self.api.assert_scope=Mock();self.api.read=Mock(side_effect=self.read)
        self.api._fetch_raw=Mock(return_value='{"status_code":0}')
    def tearDown(self):self.tmp.cleanup()
    def read(self,path,params=None,body=None):
        if path==web.CURRENT_PRODUCT_PATH:
            d={'status_code':0,'product_list':copy.deepcopy(self.current_products),'total':len(self.current_products)}
        elif path.endswith('/list'):
            d={'status_code':0,'activities':[{'activity_id':a['activity_id'],
                'activity_status':a['activity_status'],'start_time':a['start_time'],'end_time':a['end_time']}
                for a in self.activities],
                'pagination':{'has_more':False}}
        elif path.endswith('/info'):
            found=[a for a in self.activities if str(a['activity_id'])==params['activity_id']]
            d={'status_code':0,'activity':copy.deepcopy(found[0])}
        elif path==LOOKUP_PATH:
            d={'status_code':0,'success_anchor_list':[{'uid':234,'douyin_id':'new123','user_type':3}]}
        elif path==PRECHECK_PATH:d={'status_code':0,'pre_check_result':{}}
        else:raise AssertionError(path)
        return json.dumps(d),d
    def execute(self,params=None):return web.run_api(self.job,self.cfg,self.store,self.api,params)
    def make_saved(self,body,status=1):
        a=copy.deepcopy(body['activity']);a['activity_id']=int(NEW);a['activity_status']=status
        a['create_time']=int(self.now);a['update_time']=123
        for sku in a['sku_list']:
            sku['total_quantity']=sum(g['total_quantity'] for g in sku['anchor_list'])
            for grant in sku['anchor_list']:grant['coupon_id']=9000000000000000888;grant['left_quantity']=grant['total_quantity']
        return a
    def saved_on_send(self,packet):
        self.activities.append(self.make_saved(packet['data']))
        return '{"status_code":0}'

    def test_missing_dates_yield_exact_preview_without_write(self):
        result=self.execute();self.assertEqual(result['status'],'needs_input')
        p=result['details']['preview'];self.assertEqual(p['template_id'],OLD)
        self.assertEqual(p['products'],[{'id':'789','name':'Synthetic room','price_cents':9900,'stock_per_creator':2000}])
        self.assertNotIn('start_time',p);self.assertNotIn('end_time',p)
        self.assertEqual(p['current_product_check']['status'],'required')
        self.api._fetch_raw.assert_not_called();self.assertIsNone(pc_jobs.load_journal(self.store.path,self.job))
    def test_active_missing_authorization_requires_frozen_same_task_confirmation(self):
        self.old.update(activity_status=2,start_time=int(self.now)-100,end_time=int(self.now)+86400)
        self.old['sku_list'][0]['left_quantity']=2000
        self.old['sku_list'][0]['anchor_list'][0]['left_quantity']=2000
        discovered=self.execute();self.assertEqual(discovered['status'],'needs_input')
        frozen=discovered['details']['preview']
        self.assertEqual(frozen['mode'],'authorize_existing');self.assertEqual(frozen['activity_id'],OLD)
        self.assertEqual(frozen['requested_accounts'],['new123']);self.assertEqual(frozen['missing_accounts'],['new123'])
        self.assertEqual(frozen['products'][0]['price_cents'],9900)
        self.assertEqual(frozen['products'][0]['stock_per_creator'],2000)
        self.assertEqual(frozen['end_time'],self.old['end_time'])
        self.api._fetch_raw.assert_not_called()
        params={'action':'authorize_existing','confirmed':True,
            'activity_id':frozen['activity_id'],'fingerprint':frozen['fingerprint']}
        result=self.execute(params);self.assertEqual(result['status'],'waiting_review')
        self.assertEqual(self.api._fetch_raw.call_count,1)
        self.assertFalse(any(c.args[0]==web.CURRENT_PRODUCT_PATH for c in self.api.read.call_args_list))
    def test_multiple_heterogeneous_templates_require_selection(self):
        second=copy.deepcopy(self.old);second['activity_id']=9000000000000000111
        second['sku_list'][0]['fixed_price']=8800;second['sku_list'][0]['anchor_list'][0]['fixed_price']=8800
        self.activities.append(second)
        result=self.execute();self.assertNotIn('preview',result['details']);self.assertEqual(len(result['details']['candidates']),2)
        self.api._fetch_raw.assert_not_called()
    def test_incomplete_or_duplicate_page_never_produces_preview(self):
        self.api.read.side_effect=lambda *a,**k:('',{'activities':[],'pagination':{}})
        with self.assertRaises(web.NeedsReview):self.execute()
        self.api._fetch_raw.assert_not_called()
    def test_fingerprint_ignores_sales_remaining_and_update_time(self):
        before=web.fingerprint(self.old);self.old['update_time']+=1
        self.old['sku_list'][0]['left_quantity']=5;self.old['sku_list'][0]['product_info']['sold_count']=999
        self.assertEqual(before,web.fingerprint(self.old))
        self.old['sku_list'][0]['anchor_list'][0]['total_quantity']+=1
        self.assertNotEqual(before,web.fingerprint(self.old))
    def test_only_observed_display_cdn_paths_do_not_change_fingerprint(self):
        self.old['anchor_info_list'][0]['avatar']={'uri':'stable-avatar-id','url_list':['https://cdn.example/avatar?signature=old']}
        self.old['sku_list'][0]['product_info']['image_list']=['https://cdn.example/room?signature=old']
        original=copy.deepcopy(self.old);before=web.fingerprint(self.old)
        self.assertEqual(original,self.old)
        self.old['anchor_info_list'][0]['avatar']['url_list']=['https://cdn.other/avatar?signature=fresh']
        self.old['sku_list'][0]['product_info']['image_list']=['https://cdn.other/room?signature=fresh']
        self.assertEqual(before,web.fingerprint(self.old))
        self.old['sku_list'][0]['product_info']['product_name']='Changed named product'
        self.assertNotEqual(before,web.fingerprint(self.old))
    def test_cdn_exception_preserves_business_ids_price_stock_limit_and_actor_identity(self):
        before=web.fingerprint(self.old)
        changes=[(('sku_list',0,'product_id'),999),(('sku_list',0,'fixed_price'),8800),
            (('sku_list',0,'anchor_list',0,'total_quantity'),1000),
            (('sku_list',0,'purchase_limit'),3),(('anchor_info_list',0,'uid'),'999')]
        for path,value in changes:
            with self.subTest(path=path):
                modified=copy.deepcopy(self.old);parent=modified
                for key in path[:-1]:parent=parent[key]
                parent[path[-1]]=value
                self.assertNotEqual(before,web.fingerprint(modified))
        modified=copy.deepcopy(self.old);modified['extra_map']['business_callback_url']='https://business.example/changed'
        self.assertNotEqual(before,web.fingerprint(modified))
    def test_strict_confirmation_dates_fingerprint_and_fields(self):
        bad=[dict(self.params,confirmed=False),dict(self.params,fingerprint='x'*64),
            dict(self.params,start_time=int(self.now)),dict(self.params,end_time=self.params['start_time']),
            dict(self.params,start_time=float('nan')),dict(self.params,end_time=float('inf')),
            dict(self.params,start_time=True),dict(self.params,price_cents=1)]
        for params in bad:
            with self.subTest(params=params):
                self.assertEqual(self.execute(params)['status'],'needs_input')
        self.api._fetch_raw.assert_not_called()
    def test_future_create_preserves_price_per_creator_stock_and_only_requested_accounts(self):
        original=copy.deepcopy(self.old);self.api._fetch_raw.side_effect=self.saved_on_send
        result=self.execute(self.params);self.assertEqual(result['status'],'waiting_review')
        body=self.api._fetch_raw.call_args[0][0]['data'];a=body['activity'];sku=a['sku_list'][0]
        self.assertEqual(self.old,original)
        for old_id in ('activity_id','merchant_act_id','coupon_id','activity_detail_id'):
            self.assertNotIn(old_id,a);self.assertNotIn(old_id,sku)
        self.assertNotIn('alliance_task_relation_info',a);self.assertEqual(a['anchor_broker_info_list'],[])
        self.assertEqual(a['extra_map'],original['extra_map']);self.assertEqual(sku['purchase_limit'],2)
        self.assertEqual((sku['fixed_price'],sku['total_quantity']),(9900,2000))
        self.assertEqual(a['anchor_info_list'],[{'uid':'234','identity_type':1,'douyin_id':'new123'}])
        self.assertEqual(sku['dss_stock_info_list'],[]);self.assertEqual(len(sku['anchor_list']),1)
        self.assertNotIn('coupon_id',sku['anchor_list'][0])
        lookups=[c.kwargs['body'] for c in self.api.read.call_args_list if c.args[0]==LOOKUP_PATH]
        self.assertEqual(lookups[0]['start_time'],self.params['start_time']);self.assertNotIn('exist_activity_id',lookups[0])
        self.assertEqual(sum(c.args[0]==PRECHECK_PATH for c in self.api.read.call_args_list),2)
        current_queries=[c.kwargs['params'] for c in self.api.read.call_args_list if c.args[0]==web.CURRENT_PRODUCT_PATH]
        self.assertEqual(len(current_queries),2)
        self.assertNotIn('product_id_list',current_queries[0]);self.assertEqual(current_queries[0]['mkt_activity_type'],2)
        self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_future_saved_branch_reads_twice_and_never_resends(self):
        self.api._fetch_raw.side_effect=self.saved_on_send;self.execute(self.params)
        self.api.read.reset_mock();result=self.execute()
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['details']['state'],'pending')
        self.assertIn('待生效',result['text']);self.assertEqual(len(result['reviews']),2)
        self.assertEqual(sum(c.args[0].endswith('/list') for c in self.api.read.call_args_list),2)
        self.assertEqual(self.api._fetch_raw.call_count,1)
        self.assertEqual(self.execute(self.params)['status'],'succeeded');self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_timeout_after_dispatch_is_read_only_even_after_restart(self):
        self.api._fetch_raw.side_effect=TimeoutError()
        self.assertEqual(self.execute(self.params)['status'],'waiting_review')
        self.assertEqual(self.execute(self.params)['status'],'waiting_review');self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_new_start_time_checked_again_at_final_dispatch_boundary(self):
        clock_patch=patch('web_activity.time.time',return_value=self.params['start_time'])
        self.api.assert_scope.side_effect=lambda:clock_patch.start()
        try:
            with self.assertRaises(web.NativeDispatchDenied):self.execute(self.params)
        finally:clock_patch.stop()
        self.api._fetch_raw.assert_not_called()
        self.api.assert_scope.side_effect=None
        self.assertEqual(self.execute(self.params)['status'],'waiting_review')
        self.api._fetch_raw.assert_not_called()
    def test_second_precheck_soft_error_blocks_send(self):
        original=self.read;count=0
        def read(path,params=None,body=None):
            nonlocal count
            if path==PRECHECK_PATH:
                count+=1
                if count==2:return '',{'status_code':0,'pre_check_result':{'blocked':'product'}}
            return original(path,params,body)
        self.api.read.side_effect=read
        self.assertEqual(self.execute(self.params)['status'],'needs_input');self.api._fetch_raw.assert_not_called()
    def test_changed_template_after_precheck_blocks_send(self):
        original=self.read
        def read(path,params=None,body=None):
            if path==PRECHECK_PATH:self.old['sku_list'][0]['purchase_limit']=5
            return original(path,params,body)
        self.api.read.side_effect=read
        self.assertEqual(self.execute(self.params)['status'],'needs_input');self.api._fetch_raw.assert_not_called()
    def test_exact_existing_future_configuration_is_independently_proven_without_create(self):
        creators={'new123':{'uid':'234','douyin_id':'new123','identity_type':1}}
        body=web.creation_payload(self.old,['new123'],creators,ROOT,self.params['start_time'],self.params['end_time'])
        self.activities.append(self.make_saved(body))
        result=self.execute(self.params)
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['details']['mode'],'already_configured')
        self.assertEqual(len(result['reviews']),2);self.api._fetch_raw.assert_not_called()
        self.assertIsNone(pc_jobs.load_journal(self.store.path,self.job))
    def test_partial_or_different_existing_future_overlap_blocks_duplicate_create(self):
        creators={'new123':{'uid':'234','douyin_id':'new123','identity_type':1}}
        body=web.creation_payload(self.old,['new123'],creators,ROOT,self.params['start_time'],self.params['end_time'])
        existing=self.make_saved(body);existing['sku_list'][0]['anchor_list'][0]['fixed_price']=1
        self.activities.append(existing)
        self.assertEqual(self.execute(self.params)['status'],'needs_input');self.api._fetch_raw.assert_not_called()
    def test_saved_uid_mapping_does_not_require_douyin_id_to_be_repeated_in_readback(self):
        self.api._fetch_raw.side_effect=self.saved_on_send;self.execute(self.params)
        self.activities[-1]['anchor_info_list'][0].pop('douyin_id')
        self.assertEqual(self.execute()['status'],'succeeded')
        self.activities[-1]['anchor_info_list'][0]['douyin_id']='WrongAccount'
        self.assertEqual(self.execute()['status'],'waiting_review');self.assertEqual(self.api._fetch_raw.call_count,1)
    def test_original_template_or_saved_price_change_not_claimed_success(self):
        self.api._fetch_raw.side_effect=self.saved_on_send;self.execute(self.params)
        self.activities[-1]['sku_list'][0]['anchor_list'][0]['fixed_price']=1
        self.assertEqual(self.execute()['status'],'waiting_review');self.assertEqual(self.api._fetch_raw.call_count,1)
        self.activities[-1]['sku_list'][0]['anchor_list'][0]['fixed_price']=9900
        self.old['sku_list'][0]['purchase_limit']=3
        self.assertEqual(self.execute()['status'],'waiting_review')
    def test_auto_allocation_or_read_only_permission_does_not_submit(self):
        self.cfg['pc_activity']['allow_authorization_write']=False
        self.assertEqual(self.execute(self.params)['status'],'needs_input');self.api._fetch_raw.assert_not_called()
        self.cfg['pc_activity']['allow_authorization_write']=True
        self.old['extra_map']['auto_assign_user_limit']='10';self.params['fingerprint']=web.fingerprint(self.old)
        result=self.execute(self.params)
        self.assertEqual(result['status'],'needs_input');self.assertTrue(result['details']['blocked'])
        self.api._fetch_raw.assert_not_called()
    def test_unverified_coupon_configuration_blocks_before_platform_requests(self):
        self.old['sku_list'][0]['coupon_config']={'other_rights':'unknown'}
        self.params['fingerprint']=web.fingerprint(self.old)
        result=self.execute(self.params)
        self.assertEqual(result['status'],'needs_input');self.assertTrue(result['details']['blocked'])
        self.assertEqual(result['details']['preview']['products'][0]['price_cents'],9900)
        self.assertFalse(any(c.args[0] in (LOOKUP_PATH,PRECHECK_PATH) for c in self.api.read.call_args_list))
        self.api._fetch_raw.assert_not_called()
    def test_current_expired_product_blocks_create_despite_empty_platform_precheck(self):
        self.current_products[0]['sold_end_time']=int(self.now)-100
        result=self.execute(self.params)
        self.assertEqual(result['status'],'needs_input');self.assertTrue(result['details']['blocked'])
        check=result['details']['current_product_check']
        self.assertEqual(check['status'],'blocked');self.assertEqual(check['legal_candidate_ids'],[])
        self.api._fetch_raw.assert_not_called()
    def test_current_use_date_expired_or_missing_never_uses_old_snapshot(self):
        self.current_products[0]['use_date']['use_end_date']='2020-01-01'
        self.assertEqual(self.execute(self.params)['details']['current_product_check']['status'],'blocked')
        self.current_products[0].pop('use_date')
        self.assertEqual(self.execute(self.params)['details']['current_product_check']['status'],'unknown')
        self.api._fetch_raw.assert_not_called()
    def test_current_product_invalid_deny_or_exact_sku_stays_unknown(self):
        self.current_products[0]['is_deny']='Unknown contract'
        self.assertEqual(self.execute(self.params)['details']['current_product_check']['status'],'unknown')
        self.current_products[0]['is_deny']=False;self.current_products[0]['sku_list'][0]['id']='DifferentSku'
        self.assertEqual(self.execute(self.params)['details']['current_product_check']['status'],'unknown')
        self.api._fetch_raw.assert_not_called()
    def test_official_optional_deny_flag_is_retained_as_unknown_value_without_inventing_false(self):
        self.current_products[0].pop('is_deny');self.current_products[0]['sku_list'][0].pop('is_deny')
        check=web.current_product_check(self.api,self.old,self.params['start_time'],self.params['end_time'])
        self.assertEqual(check['status'],'verified')
        self.assertIsNone(check['products'][0]['platform_is_deny']);self.assertTrue(check['products'][0]['candidate_returned'])
    def test_current_product_candidates_include_every_completed_page(self):
        original=copy.deepcopy(self.current_products[0])
        other=copy.deepcopy(original);other.update(product_id='790',product_name='Second current room')
        other['sku_list'][0].update(id='457',sku_amount=12300,suggest_activity_amount=11000)
        pages={0:[original],1:[other]}
        def read(path,params=None,body=None):
            self.assertEqual(path,web.CURRENT_PRODUCT_PATH)
            return '',{'status_code':0,'product_list':copy.deepcopy(pages[params['cursor']]),'total':2}
        self.api.read.side_effect=read
        check=web.current_product_check(self.api,self.old,self.params['start_time'],self.params['end_time'])
        self.assertEqual(check['status'],'verified')
        self.assertEqual([row['id'] for row in check['current_candidates']],['789','790'])
        self.assertEqual(check['current_candidates'][1]['price_cents'],12300)
        self.assertEqual(check['current_candidates'][1]['suggested_price_cents'],11000)
        self.assertEqual([call.kwargs['params']['cursor'] for call in self.api.read.call_args_list],[0,1])
    def test_supply_changes_between_current_product_gates_block_dispatch(self):
        original=self.read
        def read(path,params=None,body=None):
            if path==PRECHECK_PATH:self.current_products[0]['is_deny']=True;self.current_products[0]['deny_reason']='Current supply blocked'
            return original(path,params,body)
        self.api.read.side_effect=read
        result=self.execute(self.params)
        self.assertEqual(result['status'],'needs_input');self.assertEqual(result['details']['current_product_check']['status'],'blocked')
        self.api._fetch_raw.assert_not_called()
    def test_post_dispatch_review_only_reads_diagnostics_and_never_redispatches(self):
        self.api._fetch_raw.side_effect=TimeoutError();self.execute(self.params)
        before=pc_jobs.load_journal(self.store.path,self.job)
        self.current_products[0]['is_deny']=True;self.current_products[0]['deny_reason']='Current supply blocked'
        self.api.read.reset_mock();self.api._fetch_raw.side_effect=AssertionError('must not dispatch after commit')
        result=self.execute(self.params)
        self.assertEqual(result['status'],'waiting_review')
        self.assertEqual(result['details']['submission_result'],'unconfirmed')
        self.assertNotIn('dispatch_receipt_missing',result['details'])
        self.assertEqual(result['details']['current_product_check']['status'],'blocked')
        self.assertTrue(any(c.args[0]==web.CURRENT_PRODUCT_PATH for c in self.api.read.call_args_list))
        self.assertEqual(self.api._fetch_raw.call_count,1)
        self.assertEqual(pc_jobs.load_journal(self.store.path,self.job),before)
    def test_runtime_is_dynamic_native_backend_attribute_for_gateway_fence(self):
        runtime=Mock();runtime.__enter__=Mock(return_value=SimpleNamespace(api=self.api));runtime.__exit__=Mock(return_value=False)
        cfg=dict(self.cfg,serial='127.0.0.1:5555',android_device={'backend':'bluestacks','adb_endpoint':'127.0.0.1:5555'})
        with patch.object(web.native_backend,'NativeRuntime',return_value=runtime) as constructor:
            result=web.run(self.job,cfg,self.store,'synthetic-adb')
        self.assertEqual(result['status'],'needs_input');constructor.assert_called_once()
    def test_web_only_execution_store_supports_create_and_review_without_notification_tables(self):
        from execution_store import Store
        self.store=Store(Path(self.tmp.name)/'web-only.sqlite3')
        with self.store.connect() as db:
            db.execute('INSERT INTO activity_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (self.job['id'],'authorization','','','','[]',self.job['accounts'],self.job['target'],
                    'running','created','',self.now,self.now))
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('outbox',tables);self.assertNotIn('messages',tables)
        self.api._fetch_raw.side_effect=self.saved_on_send
        self.assertEqual(self.execute(self.params)['status'],'waiting_review')
        self.assertEqual(self.execute()['status'],'succeeded');self.assertEqual(self.api._fetch_raw.call_count,1)


if __name__=='__main__':unittest.main()
