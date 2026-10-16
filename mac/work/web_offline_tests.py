"""Pure web/native regressions; no real configuration or old message listener."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'outputs'),str(ROOT/'work')]
modules=['test_trigger_gateway','test_trigger_worker','test_web_activity','test_native_plan','test_native_plan_executor','test_native_activity','test_native_account','test_native_bootstrap','test_native_runtime','test_native_webview_api','test_android_runtime']
result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
raise SystemExit(0 if result.wasSuccessful() else 1)
