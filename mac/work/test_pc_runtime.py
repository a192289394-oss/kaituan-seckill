"""Offline transport and orphan ownership tests, no network/process termination."""
import json
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs'))
import pc_browser_owner as owner


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.profile=Path(self.temp.name)
        owner.owner_file(self.profile).write_text(json.dumps({'owner_pid':777,'chrome_pid':888,'profile':str(self.profile.resolve())}))
    def tearDown(self):self.temp.cleanup()

    def test_live_owner_never_killed(self):
        with patch.object(owner,'alive',return_value=True),patch.object(owner.os,'kill') as kill:
            with self.assertRaises(RuntimeError):owner.recover(self.profile)
        kill.assert_not_called()

    def test_other_browser_never_killed(self):
        with patch.object(owner,'alive',side_effect=[True,False]),patch.object(owner.subprocess,'check_output',return_value='chrome --user-data-dir=/not/project --headless=new --remote-debugging-port=1'),patch.object(owner.os,'kill') as kill:
            with self.assertRaises(RuntimeError):owner.recover(self.profile)
        kill.assert_not_called()

    def test_proven_orphan_is_terminated(self):
        args=f'chrome --user-data-dir={self.profile.resolve()} --headless=new --remote-debugging-port=1'
        with patch.object(owner,'alive',side_effect=[True,False,False]),patch.object(owner.subprocess,'check_output',return_value=args),patch.object(owner.os,'kill') as kill:
            owner.recover(self.profile)
        kill.assert_called_once_with(888,signal.SIGTERM)
        self.assertFalse(owner.owner_file(self.profile).exists())

    def test_dead_chrome_only_cleans_ownership_file(self):
        with patch.object(owner,'alive',return_value=False),patch.object(owner.os,'kill') as kill:owner.recover(self.profile)
        kill.assert_not_called();self.assertFalse(owner.owner_file(self.profile).exists())


if __name__=='__main__':unittest.main()
