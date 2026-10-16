import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
from native_plan import inspect_plan,approval_packet
from pc_executor import NeedsReview
from plan_owner import ResolutionUnavailable

PLAN='9000000000000000123';DRAFT='9000000000000000456'
PRODUCTS=[{'product_id':'1234567890123456','shop_num':1,'shop_poi_id':'7000000000000000123'}]
TARGET={'root_id':'7000000000000000456'}


def response(status=2,draft_status=1):
    t={'task_id':PLAN,'task_type':30,'status':status,'merchant_detail':{'merchant_account_id':TARGET['root_id']},
       'data':{'task_draft_id':DRAFT,'task_confirm_end_time':500,
           'requirement':{'media_type':2},'product_list':[{'product_id':PRODUCTS[0]['product_id'],'commission_rate':1000,'actual_price':9900}]}}
    return {'status_code':0,'task_detail':t,'task_draft_detail':{'task_draft_id':DRAFT,'task_draft_status':draft_status,
        'task':copy.deepcopy(t),'extra':{'OperationType':1},'update_time':100}}


class PlanPacketTests(unittest.TestCase):
    def prepare(self,r=None,permission=None,marketing=None,now=200):
        r=r or response();o=inspect_plan(PLAN,TARGET,PRODUCTS,r)
        return approval_packet(o,r,permission or {'status_code':0,'has_perm':True},marketing or {'status_code':0,'ActivityInfoList':[]},now)

    def test_audited_exact_approve_packet(self):
        self.assertEqual(self.prepare(),{'operation_type':5,'task_id':PLAN,'task_draft_id':DRAFT})

    def test_already_active_is_read_only(self):
        r=response(3,2);self.assertEqual(inspect_plan(PLAN,TARGET,PRODUCTS,r)['state'],'already_active')
        with self.assertRaises(NeedsReview):self.prepare(r)

    def test_draft_id_and_merchant_must_match(self):
        r=response();r['task_draft_detail']['task_draft_id']='9000000000000000999'
        with self.assertRaises(NeedsReview):self.prepare(r)
        r=response();r['task_draft_detail']['task']['merchant_detail']['merchant_account_id']='7000000000000000999'
        with self.assertRaises(ResolutionUnavailable):self.prepare(r)

    def test_live_type_checked_in_plan_and_draft(self):
        for side in ['task_detail','draft']:
            r=response();t=r['task_detail'] if side=='task_detail' else r['task_draft_detail']['task']
            t['data']['requirement']['media_type']=1
            with self.assertRaises(NeedsReview):self.prepare(r)

    def test_permission_and_expiry_block(self):
        with self.assertRaises(NeedsReview):self.prepare(permission={'status_code':0,'has_perm':False})
        with self.assertRaises(NeedsReview):self.prepare(now=500)

    def test_no_silent_approval_of_changes_or_termination(self):
        for operation in [2,3,4,5,6,None]:
            r=response();r['task_draft_detail']['extra']['OperationType']=operation
            with self.assertRaises(NeedsReview):self.prepare(r)

    def test_extra_marketing_requires_existing_configuration(self):
        r=response();r['task_detail']['data']['activity']={'marketing_activity_info':{'NeedMarketingActivity':True}}
        with self.assertRaises(NeedsReview):self.prepare(r)
        m={'status_code':0,'ActivityInfoList':[{'MarketingActivityID':'9000000000000000789','MarketingActivityType':20}]}
        p=self.prepare(r,marketing=m)
        self.assertEqual(p['confirm_update_info']['marketing_activity_list'],m['ActivityInfoList'])

    def test_changed_commission_after_preview_requires_new_read(self):
        r=response();o=inspect_plan(PLAN,TARGET,PRODUCTS,r)
        r['task_detail']['data']['product_list'][0]['commission_rate']=2000
        with self.assertRaises(NeedsReview):approval_packet(o,r,{'status_code':0,'has_perm':True},{'status_code':0,'ActivityInfoList':[]},200)

    def test_draft_terms_change_without_update_time_requires_new_read(self):
        for field,value in [('actual_price',19900),('commission_rate',2000)]:
            with self.subTest(field=field):
                r=response();o=inspect_plan(PLAN,TARGET,PRODUCTS,r)
                r['task_draft_detail']['task']['data']['product_list'][0][field]=value
                self.assertEqual(r['task_draft_detail']['update_time'],100)
                with self.assertRaises(NeedsReview):
                    approval_packet(o,r,{'status_code':0,'has_perm':True},{'status_code':0,'ActivityInfoList':[]},200)
        for field,value in [('requirement',{'media_type':2,'description':'Changed terms'}),
                ('settlement',{'settlement_period':30}),('tiered_commission',{'rate':2000}),
                ('activity',{'marketing_activity_info':{'NeedMarketingActivity':False},'changed':True})]:
            with self.subTest(field=field):
                r=response();o=inspect_plan(PLAN,TARGET,PRODUCTS,r)
                r['task_draft_detail']['task']['data'][field]=value
                with self.assertRaises(NeedsReview):
                    approval_packet(o,r,{'status_code':0,'has_perm':True},{'status_code':0,'ActivityInfoList':[]},200)

    def test_stable_draft_can_differ_from_main_business_terms(self):
        r=response();r['task_draft_detail']['task']['data']['product_list'][0]['commission_rate']=2000
        p=self.prepare(r)
        self.assertEqual(p['task_draft_id'],DRAFT)

    def test_draft_snapshot_is_frozen_and_ignores_sales_count(self):
        r=response();r['task_draft_detail']['task']['data']['requirement']['description']='Original'
        o=inspect_plan(PLAN,TARGET,PRODUCTS,r)
        r['task_draft_detail']['task']['data']['product_list'][0]['sold_count']=123
        p=approval_packet(o,r,{'status_code':0,'has_perm':True},{'status_code':0,'ActivityInfoList':[]},200)
        self.assertEqual(p['task_draft_id'],DRAFT)
        r['task_draft_detail']['task']['data']['requirement']['description']='Changed'
        self.assertEqual(o['snapshot']['draft_terms']['requirement']['description'],'Original')
        with self.assertRaises(NeedsReview):
            approval_packet(o,r,{'status_code':0,'has_perm':True},{'status_code':0,'ActivityInfoList':[]},200)

    def test_sales_count_is_not_a_business_terms_change(self):
        r=response();o=inspect_plan(PLAN,TARGET,PRODUCTS,r)
        r['task_detail']['data']['product_list'][0]['sold_count']=123
        p=approval_packet(o,r,{'status_code':0,'has_perm':True},{'status_code':0,'ActivityInfoList':[]},200)
        self.assertEqual(p['task_draft_id'],DRAFT)


if __name__=='__main__':unittest.main()
