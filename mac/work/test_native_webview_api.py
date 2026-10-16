import json
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
from native_webview_api import NativeWebViewApi,AppReadUnavailable,select_page,verify_scope


class NativeApiTests(unittest.TestCase):
    def page(self,url=None):
        return {'type':'page','url':url or 'https://life.douyin.com/h5/alliance/merchant/plan/oriented/info?task_id=7696135169868269594'}

    def fake(self,response):
        api=object.__new__(NativeWebViewApi)
        api.js=lambda expr:response
        api.assert_scope=lambda:None
        return api

    def test_ignores_unrelated_survey_webview(self):
        target=self.page()
        self.assertEqual(select_page([self.page('https://life.douyin.com/h5/evaluation/feelgood/'),target],'7696135169868269594'),target)

    def test_rejects_multiple_matching_views(self):
        with self.assertRaises(AppReadUnavailable):select_page([self.page(),self.page()],'7696135169868269594')

    def test_verified_native_redirect_path(self):
        p=self.page('https://life.douyin.com/h5/alliance/unite_plan/target_plan_detail?task_id=7696135169868269594')
        self.assertIs(select_page([p],'7696135169868269594'),p)

    def test_actual_visible_plan_not_list_order(self):
        hidden=self.page();hidden['description']=json.dumps({'visible':False})
        visible=self.page();visible['description']=json.dumps({'visible':True})
        self.assertIs(select_page([hidden,visible],'7696135169868269594'),visible)

    def test_two_visible_plan_views_still_ambiguous(self):
        p=self.page();p['description']=json.dumps({'visible':True})
        with self.assertRaises(AppReadUnavailable):select_page([p,p],'7696135169868269594')

    def test_rejects_wrong_host_and_id(self):
        for url in ['https://life.douyin.com.evil/h5/alliance/merchant/plan/oriented/info?task_id=7696135169868269594',
                    'https://life.douyin.com/h5/alliance/merchant/plan/oriented/info?task_id=123',
                    'http://life.douyin.com/h5/alliance/merchant/plan/oriented/info?task_id=7696135169868269594']:
            with self.assertRaises(AppReadUnavailable):select_page([self.page(url)],'7696135169868269594')

    def test_never_accepts_submission_route(self):
        api=self.fake(None)
        for path in ['/life/alliance/v1/merchant/broker/operation/confirm/',
                     '/life/marketing/v1/minus_activity/create','https://evil/']:
            with self.assertRaises(ValueError):api.read(path,body={})

    def test_preserves_exact_nineteen_digit_id(self):
        raw='{"status_code":0,"activity_id":7694290066596775951}'
        _,d=self.fake(raw).read('/life/marketing/v1/minus_activity/info')
        self.assertEqual(str(d['activity_id']),'7694290066596775951')

    def test_permission_failure_is_read_unavailable(self):
        with self.assertRaises(AppReadUnavailable):self.fake(json.dumps({'status_code':2128000601})).read('/life/marketing/v1/minus_activity/info')

    def test_raw_missing_or_malformed_is_unavailable(self):
        for raw in [None,{},'not json','[]']:
            with self.assertRaises(AppReadUnavailable):self.fake(raw).read('/life/marketing/v1/minus_activity/info')

    def test_read_only_post_requires_body(self):
        with self.assertRaises(ValueError):self.fake(None).read('/life/marketing/v1/minus_activity/list')
        with self.assertRaises(ValueError):self.fake(None).read('/life/marketing/v1/minus_activity/info',body={})

    def test_actual_account_must_match_not_just_company(self):
        verify_scope({'root':'6969100408069310500','account_id':'1751535089597512'},'6969100408069310500','1751535089597512')
        with self.assertRaises(AppReadUnavailable):verify_scope({'root':'6969100408069310500','account_id':'1732648773900301'},'6969100408069310500','1751535089597512')

    def test_switch_mid_read_discards_response(self):
        api=self.fake('{"status_code":0}')
        calls=[]
        def check():
            calls.append(True)
            if len(calls)==2:raise AppReadUnavailable('scope changed')
        api.assert_scope=check
        with self.assertRaises(AppReadUnavailable):api.read('/life/marketing/v1/minus_activity/info')


if __name__=='__main__':unittest.main()
