import sys
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
from native_bootstrap import ensure_installed_runtime,SERVER,PACKAGE
from native_account import NativeAccount,NativeAccountUnavailable
from adb_android import AdbAndroid, AdbReadTimeout
import subprocess


class NativeBootstrapTests(unittest.TestCase):
    def device(self,server='99',app='100',version='16.7.19'):
        d=Mock()
        def shell(cmd,timeout=20):
            if cmd==['su','-c','id']:output='uid=0(root)'
            elif cmd==['su','-c',SERVER+' --version']:output=version
            elif cmd==['su','-c','pidof kaituan-frida-server']:output=server
            elif cmd==['pidof',PACKAGE]:output=app
            else:raise AssertionError(cmd)
            return Mock(output=output,exit_code=0)
        d.shell.side_effect=shell;return d
    def test_healthy_runtime_no_launch_no_restart(self):
        d=self.device();self.assertEqual(ensure_installed_runtime(d,'16.7.19',True),100)
        d.app_start.assert_not_called()
    def test_wrong_version_never_overwritten_or_started(self):
        d=self.device(version='17.0.0')
        with self.assertRaises(RuntimeError):ensure_installed_runtime(d,'16.7.19',True)
        d.app_start.assert_not_called()
    def test_read_only_default_no_process_start(self):
        for d in [self.device(server=''),self.device(app='')]:
            with self.assertRaises(RuntimeError):ensure_installed_runtime(d,'16.7.19')
            d.app_start.assert_not_called()
    def test_missing_app_normal_launcher_only(self):
        d=self.device(app='');original=d.shell.side_effect
        def shell(cmd,timeout=20):
            if cmd==['pidof',PACKAGE] and d.app_start.called:return Mock(output='101',exit_code=0)
            return original(cmd,timeout)
        d.shell.side_effect=shell
        self.assertEqual(ensure_installed_runtime(d,'16.7.19',True),101)
        d.app_start.assert_called_once_with(PACKAGE)
    def test_missing_server_restarts_only_loopback_installed_binary(self):
        d=self.device(server='');original=d.shell.side_effect;started=False
        def shell(cmd,timeout=20):
            nonlocal started
            if cmd==['su','-c',SERVER+' -D -l 127.0.0.1:27042']:
                started=True;return Mock(output='',exit_code=0)
            if cmd==['su','-c','pidof kaituan-frida-server'] and started:return Mock(output='103',exit_code=0)
            return original(cmd,timeout)
        d.shell.side_effect=shell
        self.assertEqual(ensure_installed_runtime(d,'16.7.19',True),100)
        d.app_start.assert_not_called()

    def test_adb_transport_timeout_has_specific_safe_type(self):
        device=AdbAndroid('synthetic-adb','127.0.0.1:5555')
        with patch('adb_android.subprocess.run',side_effect=subprocess.TimeoutExpired('private-command',10)):
            with self.assertRaises(AdbReadTimeout) as caught:
                device.shell(['su','-c','synthetic-command'],timeout=10)
        self.assertNotIn('private-command',str(caught.exception))
        self.assertIsInstance(caught.exception,RuntimeError)

    def test_timed_out_start_can_recover_by_independent_pid_read(self):
        d=self.device(server='');original=d.shell.side_effect;started=False
        def shell(cmd,timeout=20):
            nonlocal started
            if cmd==['su','-c',SERVER+' -D -l 127.0.0.1:27042']:
                started=True;raise AdbReadTimeout('transport timeout')
            if cmd==['su','-c','pidof kaituan-frida-server'] and started:
                return Mock(output='103',exit_code=0)
            return original(cmd,timeout)
        d.shell.side_effect=shell
        self.assertEqual(ensure_installed_runtime(d,'16.7.19',True),100)
        d.app_start.assert_not_called()
        d.app_stop.assert_not_called()
        self.assertEqual(sum(call.args[0]==['su','-c','pidof kaituan-frida-server']
                             for call in d.shell.call_args_list),2)

    def test_timed_out_start_without_independent_pid_remains_failed(self):
        d=self.device(server='');original=d.shell.side_effect
        def shell(cmd,timeout=20):
            if cmd==['su','-c',SERVER+' -D -l 127.0.0.1:27042']:
                raise AdbReadTimeout('transport timeout')
            return original(cmd,timeout)
        d.shell.side_effect=shell
        with self.assertRaisesRegex(RuntimeError,'启动后未读到进程'):
            ensure_installed_runtime(d,'16.7.19',True)
        d.app_start.assert_not_called()
        d.app_stop.assert_not_called()

    def test_unknown_listener_or_nontimeout_failure_never_bypasses_start(self):
        for failure in [Mock(output='',exit_code=1),RuntimeError('unknown startup error')]:
            with self.subTest(failure=type(failure).__name__):
                d=self.device(server='');original=d.shell.side_effect
                def shell(cmd,timeout=20):
                    if cmd==['su','-c',SERVER+' -D -l 127.0.0.1:27042']:
                        if isinstance(failure,Exception):raise failure
                        return failure
                    return original(cmd,timeout)
                d.shell.side_effect=shell
                with self.assertRaises(RuntimeError):ensure_installed_runtime(d,'16.7.19',True)
                d.app_start.assert_not_called()
                d.app_stop.assert_not_called()
                self.assertEqual(sum(call.args[0]==['su','-c','pidof kaituan-frida-server']
                                     for call in d.shell.call_args_list),1)
                self.assertFalse(any('kill' in ' '.join(call.args[0]) for call in d.shell.call_args_list))

    def test_existing_multiple_server_pids_are_not_guessed(self):
        d=self.device(server='100 101')
        with self.assertRaisesRegex(RuntimeError,'进程身份未唯一确认'):
            ensure_installed_runtime(d,'16.7.19',True)
        d.app_start.assert_not_called()


class NativeOwnerLockTests(unittest.TestCase):
    def test_other_owner_rejected_and_close_releases_global_lock(self):
        with patch('native_account.AdbAndroid'),patch('native_bootstrap.ensure_installed_runtime',return_value=100),patch('native_account.subprocess.run',return_value=Mock(stdout='45671')),patch('frida.get_device_manager'):
            first=NativeAccount('adb','127.0.0.1:5567')
            try:
                with self.assertRaises(NativeAccountUnavailable):NativeAccount('adb','127.0.0.1:5567')
            finally:first.close()
            second=NativeAccount('adb','127.0.0.1:5567');second.close()
    def test_failed_setup_releases_lock(self):
        with patch('native_account.AdbAndroid'),patch('native_bootstrap.ensure_installed_runtime',side_effect=RuntimeError('not ready')):
            for _ in range(2):
                with self.assertRaisesRegex(NativeAccountUnavailable,'not ready'):NativeAccount('adb','127.0.0.1:5568')


if __name__=='__main__':unittest.main()
