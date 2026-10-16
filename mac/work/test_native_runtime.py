from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
from native_runtime import NativeRuntime
from native_account import NativeAccountUnavailable


class NativeRuntimeTests(unittest.TestCase):
    def test_no_plan_no_webview_needed(self):
        account=Mock();account.switch.return_value={'active':{'account_id':'20001'}};api=Mock()
        with patch('native_runtime.NativeAccount',return_value=account),patch('native_runtime.NativeHttpApi',return_value=api) as factory:
            with NativeRuntime('adb','127.0.0.1:5555','10001','10001') as r:self.assertIs(r.api,api)
            factory.assert_called_once_with(account,'10001','20001')
        account.device.shell.assert_not_called();account.close.assert_called_once();api.close.assert_called_once()
    def test_failed_switch_closes_single_owner(self):
        account=Mock();account.switch.side_effect=NativeAccountUnavailable('switch')
        with patch('native_runtime.NativeAccount',return_value=account),patch('native_runtime.NativeHttpApi') as factory:
            with self.assertRaises(NativeAccountUnavailable):
                with NativeRuntime('adb','127.0.0.1:5555','10001','10002'):pass
        account.close.assert_called_once();factory.assert_not_called()
    def test_failed_http_scope_closes_account(self):
        account=Mock();account.switch.return_value={'active':{'account_id':'20001'}}
        with patch('native_runtime.NativeAccount',return_value=account),patch('native_runtime.NativeHttpApi',side_effect=RuntimeError('scope')):
            with self.assertRaises(RuntimeError):
                with NativeRuntime('adb','127.0.0.1:5555','10001','10001'):pass
        account.close.assert_called_once()
    def test_close_idempotent(self):
        r=NativeRuntime('adb','127.0.0.1:5555','10001','10001');r.api=Mock();r.account=Mock()
        api,account=r.api,r.account;r.close();r.close()
        api.close.assert_called_once();account.close.assert_called_once()


if __name__=='__main__':unittest.main()
