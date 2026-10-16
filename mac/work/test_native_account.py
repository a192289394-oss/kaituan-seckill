import unittest
from unittest.mock import Mock
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
from native_account import NativeAccount,NativeAccountUnavailable,pick_account,verify_identity


class NativeAccountTests(unittest.TestCase):
    def identity(self,life='7174287656027686925',root='6969100408069310500',group='1732648773900301'):
        return {'active':{'life':life,'root':root},'group':group}

    def test_company_is_not_the_child_hotel(self):
        with self.assertRaises(NativeAccountUnavailable):verify_identity(self.identity(life='6969100408069310500'),'6969100408069310500','7174287656027686925','1732648773900301')

    def test_same_root_different_group_rejected(self):
        with self.assertRaises(NativeAccountUnavailable):verify_identity(self.identity(group='1732622240815118'),'6969100408069310500','7174287656027686925','1732648773900301')

    def test_exact_native_ids_accepted(self):
        a=self.identity();self.assertIs(verify_identity(a,'6969100408069310500','7174287656027686925','1732648773900301'),a)

    def test_no_fuzzy_name_fallback(self):
        with self.assertRaises(NativeAccountUnavailable):pick_account([{'account_name':'清远玄真·十七墅','detail':{'life_account_id':'111'}}],'7174287656027686925')

    def test_duplicate_identity_requires_review(self):
        a={'detail':{'life_account_id':7174287656027686925}}
        with self.assertRaises(NativeAccountUnavailable):pick_account([a,a],'7174287656027686925')

    def test_numeric_server_ids_are_compared_exactly(self):
        a={'detail':{'life_account_id':7174287656027686925}}
        self.assertIs(pick_account([a],'7174287656027686925'),a)

    def test_not_any_network_device(self):
        for serial in ['192.168.1.2:5555','usb-device','localhost:5555','127.0.0.1:5555 extra']:
            with self.assertRaises(ValueError):NativeAccount('unused',serial)

    def fake_switch(self,life):
        root='100';group='200'
        parent={'account_id':group,'detail':{'life_account_id':root,'root_life_account_id':root}}
        child={'account_id':'201','detail':{'life_account_id':'101','root_life_account_id':root}}
        a=object.__new__(NativeAccount);a.device=Mock();a.device.app_current.return_value={'package':'com.bytedance.ls.merchant'}
        a.accounts=Mock(side_effect=lambda g=None:[child] if g else [parent])
        a.identity=Mock(return_value={'active':{'life':life,'root':root},'group':group})
        a.agent=Mock();a.agent.exports_sync.switchaccount.return_value={'ok':True}
        a._settle=Mock(return_value={'active':{'life':root,'root':root},'group':group})
        return a
    def test_same_group_child_back_to_company_invokes_normal_group_switch(self):
        a=self.fake_switch('101');a.switch('100','100')
        a.agent.exports_sync.switchgroup.assert_called_once();a.agent.exports_sync.switchaccount.assert_not_called()
        a._settle.assert_called_with('100','100','200')
    def test_same_parent_no_switch_or_foreground_launch(self):
        a=self.fake_switch('100');a.switch('100','100')
        a.agent.exports_sync.switchgroup.assert_not_called();a.device.app_current.assert_not_called()
    def test_same_group_sibling_does_not_switch_company(self):
        a=self.fake_switch('102');a.switch('100','101')
        a.agent.exports_sync.switchgroup.assert_not_called();a.agent.exports_sync.switchaccount.assert_called_once_with('201','100')


if __name__=='__main__':unittest.main()
