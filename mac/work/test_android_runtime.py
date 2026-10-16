import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outputs"))
import android_runtime


def cfg(autostart=True):
    return {"serial": "127.0.0.1:5555",
            "android_device": {"backend": "bluestacks", "adb_endpoint": "127.0.0.1:5555",
                               "instance": "Tiramisu64", "autostart": autostart}}


class AndroidRuntimeProbeTests(unittest.TestCase):
    def setUp(self):
        android_runtime._last_launch = 0.0

    def test_ready_device_does_not_connect_or_launch(self):
        ready = subprocess.CompletedProcess([], 0, "device\n", "")
        with patch("android_runtime.subprocess.run", return_value=ready) as run, \
             patch("android_runtime.subprocess.Popen") as popen:
            result = android_runtime.probe(cfg(), "adb")
        self.assertEqual(result.stdout.strip(), "device")
        popen.assert_not_called()
        self.assertEqual(run.call_args.args[0], ["adb", "-s", "127.0.0.1:5555", "get-state"])
        self.assertEqual(run.call_count, 1)

    def test_absent_device_connects_then_launches_named_instance_once(self):
        down = subprocess.CompletedProcess([], 1, "", "not found")
        calls = []

        def run(args, **_kwargs):
            calls.append(args)
            return down

        with patch("android_runtime.os.path.isfile", return_value=True), \
             patch("android_runtime.subprocess.run", side_effect=run), \
             patch("android_runtime.subprocess.Popen") as popen:
            android_runtime.probe(cfg(), "adb")
            android_runtime.probe(cfg(), "adb")
        self.assertEqual(calls[0], ["adb", "-s", "127.0.0.1:5555", "get-state"])
        self.assertEqual(calls[1], ["adb", "connect", "127.0.0.1:5555"])
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], [android_runtime.PLAYER, "--instance", "Tiramisu64"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_autostart_off_reconnects_without_launching(self):
        down = subprocess.CompletedProcess([], 1, "", "")
        with patch("android_runtime.subprocess.run", return_value=down) as run, \
             patch("android_runtime.subprocess.Popen") as popen:
            android_runtime.probe(cfg(False), "adb", allow_launch=True)
        popen.assert_not_called()
        self.assertIn(["adb", "connect", "127.0.0.1:5555"], [call.args[0] for call in run.call_args_list])

    def test_missing_player_stays_disconnected(self):
        down = subprocess.CompletedProcess([], 1, "", "")
        with patch("android_runtime.os.path.isfile", return_value=False), \
             patch("android_runtime.subprocess.run", return_value=down), \
             patch("android_runtime.subprocess.Popen") as popen:
            result = android_runtime.probe(cfg(), "adb")
        popen.assert_not_called()
        self.assertNotEqual((result.stdout or "").strip(), "device")
