import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import subprocess
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "outputs"))
import execution_store
import native_backend
import native_plan_journal
import pc_jobs
from native_http_api import NativeHttpApi
from native_commit import ActivityPermit
from native_plan_journal import PlanPermit
import trigger_worker as w
from native_http_api import safe_status_message
from native_webview_api import SubmissionUncertain
from trigger_gateway import GatewayStore, make_handler

PLAN = "9000000000000000123"
CFG = {"serial": "127.0.0.1:5555", "max_task_age_seconds": 1800,
       "execution_max_age_seconds": 1800, "auto_submit": False,
       "android_device": {"backend": "bluestacks", "execution_backend": "native_api",
                          "adb_endpoint": "127.0.0.1:5555", "autostart": False},
       "pc_activity": {"allow_authorization_write": False, "allow_authorization_copy": True}}
TARGET = {"entity_id": "root:100", "name": "Exact Synthetic Hotel", "merchant_id": "100", "root_id": "100"}


def remote(kind="plan", **changes):
    payload = {"plan_id": PLAN, "allow_write": True}
    if kind == "authorization":
        payload = {"hotel": TARGET["name"], "accounts": ["synthetic_1"], "allow_write": True}
    data = {"id": "synthetic_task", "kind": kind, "payload": payload, "created": time.time(),
            "revision": 1, "lease_token": "synthetic_lease", "read_only": False}
    data.update(changes)
    return data


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.isolated_lock = patch.object(w.tempfile, "gettempdir", return_value=self.temp.name)
        self.isolated_lock.start()
        self.store = w.WorkerStore(Path(self.temp.name) / "worker.sqlite3")
        with self.store.connect() as db:
            db.execute("INSERT INTO merchant_catalog VALUES(?,?,?,?)",
                       (TARGET["entity_id"], TARGET["name"], json.dumps(TARGET), time.time()))
        self.client = Mock()
        self.client.post.side_effect = self.reply
        self.worker = w.Worker(self.store, self.client, "mac-native-1", copy.deepcopy(CFG), "synthetic-adb")
        self.claimed = None

    def tearDown(self):
        self.isolated_lock.stop()
        self.temp.cleanup()

    def reply(self, path, body):
        if path.endswith("/claim"):
            value, self.claimed = self.claimed, None
            return {"task": value}
        if path.endswith("/heartbeat"):
            return {"ok": True, "task": {"revision": 1, "read_only": False}}
        if path.endswith("/gate"):
            return {"allowed": True, "committed": body["stage"] == "commit", "revision": body["revision"],
                    "read_only": body["stage"] == "commit"}
        if path.endswith("/report"):
            return {"task": {"id": body["task_id"], "status": body["status"]}}
        raise AssertionError(path)

    def fence(self, task=None):
        row = self.store.accept(task or remote())
        return row, w.LeaseFence(self.store, self.client, "mac-native-1", row, CFG)

    def report(self, row, **changes):
        report = {"worker_id": "mac-native-1", "task_id": row["id"], "lease_token": row["lease_token"],
                  "revision": row["revision"], "status": "succeeded", "result": {"text": "verified"},
                  "details": {}, "committed": False}
        report.update(changes)
        return report

    def test_no_legacy_events_notification_tables_or_import(self):
        with self.store.connect() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({"events", "outbox"}.intersection(tables))
        source = Path(w.__file__).read_text()
        self.assertNotIn("chat_id", source)
        self.assertNotIn("outbox_loop", source)
        self.assertNotIn("group_msg", source)

    def test_catalog_seed_reads_only_directory_once(self):
        origin = Path(self.temp.name) / "old.sqlite3"
        with sqlite3.connect(origin) as db:
            db.executescript("CREATE TABLE merchant_catalog(entity_id TEXT,name TEXT,data TEXT,updated REAL);"
                             "CREATE TABLE events(secret TEXT);CREATE TABLE tasks(secret TEXT);CREATE TABLE outbox(secret TEXT);")
            db.execute("INSERT INTO merchant_catalog VALUES(?,?,?,?)", ("second", "Second", json.dumps(dict(TARGET, entity_id="second")), 1))
            db.execute("INSERT INTO events VALUES('private-event')")
        before = origin.read_bytes()
        self.assertEqual(self.store.catalog_from(origin), 1)
        self.assertEqual(origin.read_bytes(), before)
        origin.unlink()
        self.assertEqual(self.store.catalog_from(origin), 2)

    def test_config_drops_credentials_and_global_write_permissions(self):
        config = Path(self.temp.name) / "config.json"
        config.write_text(json.dumps({"app_secret": "never-copy", "app_id": "legacy",
                                     "auto_submit": True, "pc_activity": {"allow_authorization_write": True},
                                     "android_device": {"adb_endpoint": "127.0.0.1:5555"}}))
        loaded = w.load_config(config)
        self.assertNotIn("app_secret", loaded)
        self.assertNotIn("app_id", loaded)
        self.assertFalse(loaded["auto_submit"])
        self.assertFalse(loaded["pc_activity"]["allow_authorization_write"])
        self.assertTrue(native_backend.enabled(loaded))

    def test_health_distinguishes_worker_device_root_app_and_unprobed_native_interface(self):
        responses = [
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "uid=0(root) gid=0(root)\n", ""),
            subprocess.CompletedProcess([], 0, "4321\n", ""),
            subprocess.CompletedProcess([], 0, "8765\n", ""),
        ]
        with patch.object(w.subprocess, "run", side_effect=responses) as run:
            first = self.worker.health()
            second = self.worker.health()
        runtime = first["runtime"]
        self.assertEqual(runtime["android_device"]["status"], "available")
        self.assertEqual(runtime["root"]["status"], "available")
        self.assertEqual(runtime["business_app"]["status"], "running")
        self.assertEqual(runtime["native_interface"]["status"], "unknown")
        self.assertEqual(runtime["native_interface"]["reason"], "processes_present_attach_not_probed")
        self.assertEqual(second["runtime"], runtime)
        self.assertEqual(run.call_count, 4)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(all(command[:3] == ["synthetic-adb", "-s", "127.0.0.1:5555"] for command in commands))
        self.assertFalse(any("connect" in command or "start" in command for command in commands))

    def test_health_device_timeout_short_circuits_without_claiming_readiness(self):
        with patch.object(w.subprocess, "run", side_effect=subprocess.TimeoutExpired("adb", 3)) as run:
            runtime = self.worker.health()["runtime"]
        self.assertEqual(run.call_count, 1)
        self.assertEqual(runtime["android_device"], {"status": "unavailable", "reason": "adb_timeout"})
        self.assertEqual(runtime["root"]["status"], "unknown")
        self.assertEqual(runtime["business_app"]["status"], "unknown")
        self.assertEqual(runtime["native_interface"]["status"], "unknown")

    def test_health_missing_app_reports_native_unavailable_without_starting_it(self):
        responses = [
            subprocess.CompletedProcess([], 0, "device\n", ""),
            subprocess.CompletedProcess([], 0, "uid=0(root)\n", ""),
            subprocess.CompletedProcess([], 1, "", ""),
        ]
        with patch.object(w.subprocess, "run", side_effect=responses) as run:
            runtime = self.worker.health()["runtime"]
        self.assertEqual(run.call_count, 3)
        self.assertEqual(runtime["business_app"]["status"], "stopped")
        self.assertEqual(runtime["native_interface"], {"status": "unavailable", "reason": "app_not_running"})

    def test_metadata_probe_never_touches_android(self):
        with patch.object(w.subprocess, "run") as run:
            runtime = self.worker.health(False)["runtime"]
        run.assert_not_called()
        self.assertEqual(runtime["android_device"]["reason"], "metadata_probe_skipped")

    def test_task_creation_generation_stable_after_retry(self):
        task = remote()
        first = self.store.accept(task)
        renewed = dict(task, created=time.time() + 5, lease_token="new_lease")
        second = self.store.accept(renewed)
        self.assertEqual(first["created"], second["created"])
        self.assertEqual(first["received"], second["received"])
        self.assertEqual(second["lease_token"], "new_lease")
        self.assertEqual(self.worker.local_plan(second)["created"], first["created"])

    def test_exact_plan_cannot_get_second_remote_identity(self):
        self.store.accept(remote())
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.accept(remote(id="different"))

    def test_unknown_write_default_is_readonly(self):
        task = remote()
        task["payload"].pop("allow_write")
        row = self.store.accept(task)
        self.assertTrue(row["read_only"])

    def test_exact_authorization_choice_never_uses_fuzzy_name(self):
        with self.assertRaises(w.InputNeeded):
            w.exact_target(self.store, {"hotel": "Synthetic"})
        self.assertEqual(w.exact_target(self.store, {"hotel": TARGET["name"]}), TARGET)
        duplicate = dict(TARGET, entity_id="another", merchant_id="200")
        with self.store.connect() as db:
            db.execute("INSERT INTO merchant_catalog VALUES(?,?,?,?)",
                       ("another", duplicate["name"], json.dumps(duplicate), time.time()))
        with self.assertRaises(w.InputNeeded) as ctx:
            w.exact_target(self.store, {"hotel": TARGET["name"]})
        self.assertEqual(len(ctx.exception.candidates), 2)

    def test_trailing_operation_resolves_unique_exact_hotel_and_reports_evidence(self):
        hotel = {"entity_id": "root:yihe", "name": "怡禾酒店(广州塔客村店)",
                 "merchant_id": "201", "root_id": "201"}
        with self.store.connect() as db:
            db.execute("INSERT INTO merchant_catalog VALUES(?,?,?,?)",
                       (hotel["entity_id"], hotel["name"], json.dumps(hotel), time.time()))
        task = remote(kind="authorization")
        task["payload"]["hotel"] = hotel["name"] + "秒杀"
        row, fence = self.fence(task)
        with patch("web_activity.run", return_value={"status": "needs_input", "text": "preview"}):
            result = self.worker.execute(row, fence)
        evidence = result["evidence"]["hotel_resolution"]
        self.assertEqual(result["hotel"], hotel["name"])
        self.assertEqual(evidence["input"], hotel["name"] + "秒杀")
        self.assertEqual(evidence["operation"], "秒杀")
        self.assertEqual(evidence["resolved_hotel"], hotel["name"])
        self.assertEqual(evidence["match_mode"], "exact_name_key_after_operation_suffix")
        separated = w.exact_target(self.store, {"hotel": hotel["name"] + "｜开团  "})
        self.assertEqual(separated["name"], hotel["name"])
        self.assertEqual(separated["hotel_resolution"]["operation"], "开团")

    def test_trailing_operation_never_chooses_between_similar_hotels(self):
        hotels = [
            {"entity_id": "root:yihe-1", "name": "怡禾酒店(广州塔客村店)", "merchant_id": "201"},
            {"entity_id": "root:yihe-2", "name": "怡禾酒店(广州塔客村二店)", "merchant_id": "202"},
        ]
        with self.store.connect() as db:
            for hotel in hotels:
                db.execute("INSERT INTO merchant_catalog VALUES(?,?,?,?)",
                           (hotel["entity_id"], hotel["name"], json.dumps(hotel), time.time()))
        with self.assertRaises(w.InputNeeded) as ctx:
            w.exact_target(self.store, {"hotel": "怡禾酒店 — 开团"})
        self.assertEqual(ctx.exception.candidates, [])

    def test_operation_word_in_middle_is_not_removed(self):
        hotel = {"entity_id": "root:yihe", "name": "怡禾酒店(广州塔客村店)", "merchant_id": "201"}
        with self.store.connect() as db:
            db.execute("INSERT INTO merchant_catalog VALUES(?,?,?,?)",
                       (hotel["entity_id"], hotel["name"], json.dumps(hotel), time.time()))
        with self.assertRaises(w.InputNeeded):
            w.exact_target(self.store, {"hotel": "怡禾秒杀酒店(广州塔客村店)"})

    def test_trailing_operation_without_exact_catalog_match_is_rejected(self):
        with self.assertRaises(w.InputNeeded) as ctx:
            w.exact_target(self.store, {"hotel": "完全不存在酒店｜开团  "})
        self.assertEqual(ctx.exception.candidates, [])

    def test_authorization_stable_id_and_target_binding(self):
        row = self.store.accept(remote(kind="authorization"))
        first = self.worker.local_activity(row, json.loads(row["payload"]))
        second = self.worker.local_activity(row, json.loads(row["payload"]))
        self.assertEqual(first["id"], "gateway:synthetic_task")
        self.assertEqual(first["created"], second["created"])
        self.assertEqual(json.loads(second["target"]), TARGET)

    def test_alias_and_overlapping_accounts_share_cross_task_dispatch_fence_after_restart(self):
        catalog=dict(TARGET,aliases=["Synthetic Alias"])
        with self.store.connect() as db:
            db.execute("UPDATE merchant_catalog SET data=? WHERE entity_id=?",
                       (json.dumps(catalog),TARGET["entity_id"]))
        first_task=remote(kind="authorization",id="authorization-first",lease_token="lease-first")
        first_task["payload"].update(hotel=TARGET["name"],accounts=["shared_account"])
        second_task=remote(kind="authorization",id="authorization-second",lease_token="lease-second")
        second_task["payload"].update(hotel="Synthetic Alias秒杀",accounts=["shared_account","other_account"],
            params={"action":"authorize_existing","confirmed":True,
                "activity_id":"1234567890123456789","fingerprint":"f"*64})
        first=self.store.accept(first_task);second=self.store.accept(second_task)
        first_job=self.worker.local_activity(first,json.loads(first["payload"]))
        second_job=self.worker.local_activity(second,json.loads(second["payload"]))
        # Both local jobs existed before either crossed a write boundary.  Keep
        # only the stable entity on the peer to cover historical sparse targets.
        with self.store.connect() as db:
            db.execute("UPDATE activity_jobs SET target=?,stage='submitting' WHERE id=?",
                       (json.dumps({"entity_id":TARGET["entity_id"]}),first_job["id"]))
            db.execute("INSERT INTO activity_journal VALUES(?,?,?,?,NULL)",
                       (first_job["id"],first_job["created"],"{}",time.time()))
            db.execute("UPDATE gateway_tasks SET gate_attempt_at=?,gateway_committed=1,last_status='waiting_review' WHERE id=?",
                       (time.time(),first["id"]))
        restarted_store=w.WorkerStore(self.store.path)
        restarted=w.Worker(restarted_store,self.client,"mac-native-1",copy.deepcopy(CFG),"synthetic-adb")
        current=restarted_store.remote(second["id"])
        fence=w.LeaseFence(restarted_store,self.client,"mac-native-1",current,CFG)
        with patch("web_activity.run") as backend:
            blocked=restarted.execute(current,fence)
        self.assertEqual(blocked["status"],"needs_review")
        self.assertEqual(blocked["details"]["reason"],"overlapping_authorization_pending")
        backend.assert_not_called()
        with restarted_store.connect() as db:
            self.assertIsNone(db.execute("SELECT commit_at FROM activity_journal WHERE job_id=?",
                                         (second_job["id"],)).fetchone())

        # Once the first task has a confirmed terminal result, the second task
        # may only re-read the source. Its earlier confirmation is discarded.
        with restarted_store.connect() as db:
            db.execute("UPDATE gateway_tasks SET last_status='succeeded' WHERE id=?",(first["id"],))
        observed={}
        def read_only(job,cfg,store,adb,parameters=None):
            observed.update(write=cfg["pc_activity"]["allow_authorization_write"],parameters=parameters)
            return {"status":"needs_input","text":"账号集合仍有缺失，请重新审阅新预览。",
                "details":{"preview":{"mode":"authorize_existing"}}}
        with patch("web_activity.run",side_effect=read_only) as backend:
            result=restarted.execute(current,fence)
        self.assertEqual(result["status"],"needs_input");self.assertFalse(observed["write"])
        self.assertIsNone(observed["parameters"]);backend.assert_called_once()
        self.client.post.reset_mock();original=Mock()
        with self.assertRaises(w.FenceDenied):
            w.FencedActivityPermit(original,fence).consume("100",{"activity":{}})
        original.consume.assert_not_called();self.client.post.assert_not_called()

        # A new gateway revision after that fresh read is a new consent event;
        # it may handle the still-missing account, subject to all normal gates.
        restarted_store.queue_report(self.report(current,status="needs_input"))
        resumed_task=copy.deepcopy(second_task);resumed_task.update(revision=2,lease_token="lease-second-fresh")
        resumed_task["payload"]["params"]={"action":"authorize_existing","confirmed":True,
            "activity_id":"1234567890123456789","fingerprint":"a"*64}
        resumed=restarted_store.accept(resumed_task)
        fresh_fence=w.LeaseFence(restarted_store,self.client,"mac-native-1",resumed,CFG)
        fresh={}
        def freshly_confirmed(job,cfg,store,adb,parameters=None):
            fresh.update(write=cfg["pc_activity"]["allow_authorization_write"],parameters=parameters)
            return {"status":"waiting_review","text":"single dispatch boundary"}
        with patch("web_activity.run",side_effect=freshly_confirmed):
            restarted.execute(resumed,fresh_fence)
        self.assertTrue(fresh["write"]);self.assertEqual(fresh["parameters"],resumed_task["payload"]["params"])

    def test_expired_received_task_has_no_write(self):
        row, fence = self.fence(remote(created=time.time() - 1900))
        with patch.object(native_backend, "plan", return_value={"status": "needs_review", "text": "expired"}) as backend:
            self.worker.execute(row, fence)
        self.assertFalse(backend.call_args.args[1]["auto_submit"])
        with self.assertRaises(w.FenceDenied):
            fence.preflight()
        self.client.post.assert_not_called()

    def test_revision_or_cancel_heartbeat_revokes_final_gate(self):
        for control in [{"revision": 2}, {"cancel_requested": True}, {"read_only": True}, {"fenced": True}]:
            with self.subTest(control=control):
                row, fence = self.fence(remote(id="task_" + str(len(control)) + str(list(control)[0]),
                                               payload={"plan_id": str(int(PLAN) + len(list(control)[0])), "allow_write": True}))
                fence.observe({"task": control})
                with self.assertRaises(w.FenceDenied):
                    fence.commit()

    def test_native_plan_dispatch_records_fence_then_consumes_once(self):
        row, fence = self.fence()
        task = self.worker.local_plan(row)
        expected = {"root": "100", "body": {"task_id": PLAN}, "snapshot": {"confirm_deadline": time.time() + 90}}
        with self.store.connect() as db:
            db.execute("INSERT INTO task_targets VALUES(?,?,?)", (PLAN, task["created"], json.dumps(TARGET)))
        native_plan_journal.prepare(self.store.path, task, expected)
        self.store.active_fence = fence
        self.store.submission_gate(task, CFG, "confirming")
        permit = PlanPermit(self.store.path, task, expected, 1800)
        account = Mock()
        account.identity.return_value = {"active": {"root": "100", "account_id": "200"}}
        api = NativeHttpApi(account, "100", "200")
        calls = []
        def send(packet):
            current = self.store.remote(row["id"])
            self.assertIsNotNone(current["gate_attempt_at"])
            self.assertTrue(current["gateway_committed"])
            self.assertIsNotNone(native_plan_journal.load(self.store.path, task)["dispatched_at"])
            calls.append(packet)
            return '{"status_code":0}'
        api._fetch_raw = send
        guarded = w.FencedApi(api, fence)
        guarded.submit_plan_once(expected["body"], permit)
        with self.assertRaises(w.FenceDenied):
            guarded.submit_plan_once(expected["body"], permit)
        self.assertEqual(len(calls), 1)
        restarted = w.WorkerStore(self.store.path)
        self.assertTrue(restarted.fenced(restarted.remote(row["id"])))

    def test_native_activity_fence_preserves_existing_durable_consume(self):
        row, fence = self.fence(remote(kind="authorization"))
        job = self.worker.local_activity(row, json.loads(row["payload"]))
        body = {"activity": {"end_time": time.time() + 90}}
        expected = {"root": "100", "accounts": ["synthetic_1"], "preview": {"body": body}}
        pc_jobs.prepare(self.store.path, job, expected)
        pc_jobs.submission_gate(self.store.path, job, 1800, expected)
        wrapped = w.FencedActivityPermit(ActivityPermit(self.store.path, job, expected, 1800), fence)
        wrapped.consume("100", body)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT stage FROM activity_jobs").fetchone()[0], "publishing")
        with self.assertRaises(w.FenceDenied):
            wrapped.consume("100", body)

    def receipt_activity(self, response=None, task=None):
        task=task or remote(kind="authorization")
        row,fence=self.fence(task)
        job=self.worker.local_activity(row,json.loads(row["payload"]))
        body={"activity":{"end_time":time.time()+90}}
        expected={"root":"100","accounts":["synthetic_1"],"preview":{"body":body}}
        pc_jobs.prepare(self.store.path,job,expected)
        pc_jobs.submission_gate(self.store.path,job,1800,expected)
        permit=ActivityPermit(self.store.path,job,expected,1800)
        account=Mock()
        account.identity.return_value={"active":{"root":"100","account_id":"200"}}
        account.agent.exports_sync.dispatch.return_value=response or {"http":200,"raw":'{"status_code":0,"status_msg":"成功"}'}
        api=NativeHttpApi(account,"100","200")
        return row,fence,job,body,permit,account,w.FencedApi(api,fence)

    def receipt_rows(self):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM dispatch_receipts ORDER BY id")]

    def test_response_code_zero_then_scope_error_is_durable_and_not_retried(self):
        row,fence,job,body,permit,account,api=self.receipt_activity()
        identities=[
            {"active":{"root":"100","account_id":"200"}},
            {"active":{"root":"100","account_id":"200"}},
            {"active":{"root":"100","account_id":"201"}},
        ]
        account.identity.side_effect=identities
        with self.assertRaises(SubmissionUncertain):
            api.submit_activity_once(body,permit)
        rows=self.receipt_rows()
        self.assertEqual([r["phase"] for r in rows],["response_received","post_response_scope_error"])
        self.assertEqual(rows[0]["status_code"],0)
        self.assertEqual(rows[0]["http"],200)
        self.assertEqual(len(rows[0]["request_body_sha"]),64)
        self.assertEqual(len(rows[0]["response_sha"]),64)
        self.assertTrue(self.store.fenced(self.store.remote(row["id"])))
        self.assertEqual(self.store.receipt_brief(row["id"])["response_diagnostic_code"],
                         "native_scope_after_response_unverified")
        # Independent guard remains spent even though post-save identity failed.
        with self.assertRaises(w.FenceDenied):fence.commit()
        self.assertEqual(account.agent.exports_sync.dispatch.call_count,1)

    def test_business_rejection_keeps_exact_code_and_does_not_resend(self):
        response={"http":200,"raw":'{"status_code":1440927,"status_msg":"门店权限未通过"}'}
        row,fence,job,body,permit,account,api=self.receipt_activity(response)
        with self.assertRaises(SubmissionUncertain):
            api.submit_activity_once(body,permit)
        receipts=self.receipt_rows()
        self.assertEqual(receipts[-1]["phase"],"business_rejected")
        self.assertEqual(receipts[-1]["status_code"],1440927)
        self.assertEqual(receipts[-1]["status_msg"],"门店权限未通过")
        self.assertEqual(self.store.receipt_brief(row["id"])["platform_status_code"],1440927)
        with self.assertRaises(w.FenceDenied):api.submit_activity_once(body,permit)
        self.assertEqual(account.agent.exports_sync.dispatch.call_count,1)

    def test_lost_transport_response_retains_only_class_and_request_digest(self):
        row,fence,job,body,permit,account,api=self.receipt_activity()
        account.agent.exports_sync.dispatch.side_effect=RuntimeError("Bearer=private_transport_secret")
        with self.assertRaises(SubmissionUncertain):
            api.submit_activity_once(body,permit)
        rows=self.receipt_rows()
        self.assertEqual(rows[0]["phase"],"transport_exception")
        self.assertEqual(rows[0]["error_class"],"RuntimeError")
        self.assertIsNone(rows[0]["response_sha"])
        self.assertIsNone(rows[0]["status_code"])
        self.assertNotIn("private_transport_secret",json.dumps(rows))
        self.assertEqual(self.store.receipt_brief(row["id"])["response_diagnostic_code"],
                         "native_transport_unconfirmed")
        with self.assertRaises(w.FenceDenied):fence.commit()

    def test_callback_persistence_failure_keeps_native_commit_and_reports_unavailable(self):
        task=remote(kind="authorization")
        row,fence,job,body,permit,account,api=self.receipt_activity(task=task)
        with patch.object(self.store,"record_dispatch_receipt",side_effect=sqlite3.OperationalError("private storage detail")):
            with self.assertRaises(SubmissionUncertain):api.submit_activity_once(body,permit)
        self.assertTrue(fence.receipt_failed)
        self.assertTrue(self.store.committed(self.store.remote(row["id"])))
        self.assertEqual(account.agent.exports_sync.dispatch.call_count,1)
        self.assertEqual(self.receipt_rows(),[])
        with self.assertRaises(w.FenceDenied):fence.commit()
        # A later read-only recovery cannot invent a receipt or re-dispatch.
        self.claimed=task
        with patch.object(self.worker,"execute",return_value={"status":"waiting_review","text":"only review"}):
            self.worker.run_once()
        with self.store.connect() as db:
            report=json.loads(db.execute("SELECT body FROM gateway_reports ORDER BY id DESC LIMIT 1").fetchone()[0])
        self.assertEqual(report["details"]["response_diagnostic_code"],"response_record_unavailable")
        self.assertNotIn("private storage detail",json.dumps(report))

    def test_receipt_redacts_embedded_credentials_and_never_stores_response_data(self):
        for value in ["token=synthetic_secret","Cookie: synthetic_secret",
                      "Bearer synthetic_secret","headers={Authorization:synthetic_secret}",
                      "https://example.test/?secret=synthetic_secret",
                      "longopaquecredential000000000000000000000000"]:
            with self.subTest(value=value):
                self.assertNotIn("synthetic_secret",safe_status_message(value))
                self.assertNotEqual(safe_status_message(value),value)
        response={"http":200,"raw":json.dumps({"status_code":0,"status_msg":"token=synthetic_secret",
                    "data":{"token":"deep-private","headers":{"cookie":"nested-private"}}})}
        row,fence,job,body,permit,account,api=self.receipt_activity(response)
        api.submit_activity_once(body,permit)
        saved=json.dumps(self.receipt_rows())
        for value in ["synthetic_secret","deep-private","nested-private"]:
            self.assertNotIn(value,saved)
        self.assertEqual(self.receipt_rows()[-1]["phase"],"scope_verified")
        brief=self.store.receipt_brief(row["id"])
        self.assertFalse({"response_sha","request_body_sha","status_msg","raw","headers"}.intersection(brief))

    def test_final_receipt_failure_after_success_stays_readonly_without_resend(self):
        row,fence,job,body,permit,account,api=self.receipt_activity()
        original=self.store.record_dispatch_receipt
        def save(task_id,summary):
            if summary["phase"]=="scope_verified":
                raise sqlite3.OperationalError("storage after save unavailable")
            return original(task_id,summary)
        with patch.object(self.store,"record_dispatch_receipt",side_effect=save):
            with self.assertRaises(SubmissionUncertain):api.submit_activity_once(body,permit)
        self.assertTrue(fence.receipt_failed)
        self.assertEqual(self.receipt_rows()[0]["phase"],"response_received")
        self.assertEqual(self.receipt_rows()[0]["status_code"],0)
        with self.assertRaises(w.FenceDenied):fence.commit()
        self.assertEqual(account.agent.exports_sync.dispatch.call_count,1)

    def test_http_rejection_is_recorded_before_native_parse(self):
        row,fence,job,body,permit,account,api=self.receipt_activity({"http":403,"raw":'{"status_code":1001,"status_msg":"拒绝访问"}'})
        with self.assertRaises(SubmissionUncertain):api.submit_activity_once(body,permit)
        receipts=self.receipt_rows()
        self.assertEqual(receipts[-1]["phase"],"http_rejected")
        self.assertEqual(receipts[-1]["http"],403)
        self.assertEqual(receipts[-1]["status_code"],1001)

    def test_lost_commit_reply_is_durably_never_retried(self):
        row, fence = self.fence()
        original = self.reply
        def lost(path, payload):
            if path.endswith("/gate") and payload["stage"] == "commit":
                raise w.GatewayUnavailable("lost reply")
            return original(path, payload)
        self.client.post.side_effect = lost
        with self.assertRaises(w.GatewayUnavailable):
            fence.commit()
        self.assertTrue(self.store.fenced(self.store.remote(row["id"])))
        row = w.WorkerStore(self.store.path).remote(row["id"])
        self.assertIsNotNone(row["gate_attempt_at"])
        self.assertFalse(row["gateway_committed"])
        with self.assertRaises(w.FenceDenied):
            fence.commit()
        self.assertEqual(sum(c.args[1].get("stage") == "commit" for c in self.client.post.call_args_list), 1)

    def test_scope_is_rechecked_after_network_gate_before_native_consume(self):
        row, fence = self.fence()
        original = Mock()
        scope = Mock(side_effect=RuntimeError("identity changed during gateway call"))
        guarded = w.FencedPlanPermit(original, fence, scope)
        with self.assertRaises(RuntimeError):
            guarded.consume("100", {"task_id": PLAN})
        scope.assert_called_once()
        original.consume.assert_not_called()
        self.assertTrue(self.store.fenced(self.store.remote(row["id"])))

    def test_old_native_generation_also_forces_readonly(self):
        row, fence = self.fence()
        with self.store.connect() as db:
            db.execute("INSERT INTO native_plan_journal VALUES(?,?,?,?)", (PLAN, row["created"] - 100, "{}", time.time()))
        with patch.object(native_backend, "plan", return_value={"status": "waiting_review", "text": "audit"}) as backend:
            self.worker.execute(row, fence)
        self.assertTrue(backend.call_args.kwargs["review_only"])
        self.assertFalse(backend.call_args.args[1]["auto_submit"])

    def test_inspect_never_creates_business_tasks(self):
        row, fence = self.fence(remote(kind="inspect"))
        with patch.object(native_backend, "inspect_link", return_value={"hotel": "Synthetic", "observation": {"state": "pending"}, "evidence": {}}):
            result = self.worker.execute(row, fence)
        self.assertEqual(result["state"], "pending")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM native_plan_journal").fetchone()[0], 0)

    def test_failed_report_replays_original_before_claim_and_never_reexecutes(self):
        row = self.store.accept(remote())
        body = self.report(row)
        self.store.queue_report(body)
        self.client.post.side_effect = w.GatewayUnavailable("report offline")
        with patch.object(self.worker, "execute") as execute:
            with self.assertRaises(w.GatewayUnavailable):
                self.worker.run_once()
            execute.assert_not_called()
        self.assertEqual(self.store.pending(), [body])
        self.client.post.side_effect = self.reply
        self.worker.run_once()
        self.assertEqual(self.client.post.call_args_list[-3].args, ("/api/worker/report", body))
        self.assertFalse(self.store.pending())

    def test_stale_report_is_archived_to_allow_readonly_reclaim(self):
        row = self.store.accept(remote())
        body = self.report(row)
        self.store.queue_report(body)
        self.client.post.side_effect = w.GatewayUnavailable("stale", 409, "stale_revision")
        self.worker.flush_reports()
        self.assertFalse(self.store.pending())
        self.assertTrue(self.store.remote(row["id"])["blocked"])
        with self.store.connect() as db:
            archived = db.execute("SELECT body,state FROM gateway_reports").fetchone()
        self.assertEqual(json.loads(archived[0]), body)
        self.assertEqual(archived[1], "stale_lease_retained")

    def test_nonstale_report_conflict_keeps_pending(self):
        row = self.store.accept(remote())
        self.store.queue_report(self.report(row))
        self.client.post.side_effect = w.GatewayUnavailable("conflict", 409, "report_conflict")
        with self.assertRaises(w.GatewayUnavailable):
            self.worker.flush_reports()
        self.assertTrue(self.store.pending())

    def test_needs_review_is_needs_input_without_claiming_schedule_saved(self):
        self.claimed = remote(kind="authorization")
        with patch.object(self.worker, "execute", side_effect=w.NeedsReview("No current schedule")):
            self.worker.run_once()
        report = [call.args[1] for call in self.client.post.call_args_list if call.args[0].endswith("/report")][0]
        self.assertEqual(report["status"], "needs_input")
        self.assertFalse(report["details"]["parameters_applied"])
        self.assertFalse(report["committed"])

    def test_autostart_waits_for_emulator_before_any_business_call(self):
        self.worker.cfg["android_device"]["autostart"] = True
        self.worker.cfg["android_device"]["instance"] = "Tiramisu64"
        self.claimed = remote(kind="authorization")
        down = subprocess.CompletedProcess([], 1, "", "")
        with patch("android_runtime.probe", return_value=down) as probe, \
             patch("web_activity.run") as business:
            self.worker.run_once()
        probe.assert_called_once()
        self.assertTrue(probe.call_args.kwargs["allow_launch"])
        business.assert_not_called()
        with self.store.connect() as db:
            report = json.loads(db.execute("SELECT body FROM gateway_reports").fetchone()[0])
        self.assertEqual(report["status"], "waiting_device")
        self.assertEqual(report["details"]["diagnostic_code"], "emulator_not_connected")
        self.assertFalse(report["details"]["dispatch_confirmed"])
        self.assertNotIn("root", report["result"]["text"])

    def test_known_native_failure_retains_safe_recovery_diagnostic(self):
        self.claimed = remote(kind="authorization")
        self.worker.cfg["android_device"]["autostart"] = True
        exc = w.NativeAccountUnavailable("App 内部账号服务暂不可连接：原生连接服务启动后未读到进程")
        with patch.object(self.worker, "execute", side_effect=exc):
            self.worker.run_once()
        with self.store.connect() as db:
            report = json.loads(db.execute("SELECT body FROM gateway_reports").fetchone()[0])
        self.assertEqual(report["status"], "waiting_device")
        self.assertEqual(report["details"]["diagnostic_code"], "runtime_start_unconfirmed")
        self.assertTrue(report["details"]["runtime_autostart"])
        self.assertIn("进程", report["result"]["text"])

    def test_raw_native_transport_error_and_possible_tokens_are_not_reported(self):
        secret = "token=synthetic-private bearer=another-private Cookie=third-private"
        exc = w.NativeAccountUnavailable("App 内部账号服务暂不可连接：" + secret)
        detail = w.safe_native_diagnostic(exc, CFG)
        self.assertEqual(detail["diagnostic_code"], "native_account_unavailable")
        for value in ("synthetic-private", "another-private", "third-private", "Cookie"):
            self.assertNotIn(value, json.dumps(detail))

    def test_confirmed_schedule_resume_keeps_generation_and_identity(self):
        task = remote(kind="authorization")
        first = self.store.accept(task)
        self.store.queue_report(self.report(first, status="needs_input"))
        params = {"template_id": "123", "fingerprint": "f" * 64, "start_time": time.time() + 100,
                  "end_time": time.time() + 200, "confirmed": True}
        updated = copy.deepcopy(task)
        updated.update(revision=2, lease_token="new")
        updated["payload"]["params"] = params
        resumed = self.store.accept(updated)
        self.assertEqual(resumed["created"], first["created"])
        self.assertFalse(resumed["read_only"])
        self.assertEqual(json.loads(resumed["payload"])["params"], params)
        with self.store.connect() as db:
            db.execute("UPDATE gateway_tasks SET gate_attempt_at=? WHERE id=?", (time.time(), first["id"]))
        updated.update(revision=3)
        readonly = self.store.accept(updated)
        self.assertTrue(readonly["read_only"])

    def test_unconfirmed_parameter_resume_cannot_write(self):
        task = remote(kind="authorization")
        row = self.store.accept(task)
        self.store.queue_report(self.report(row, status="needs_input"))
        task = copy.deepcopy(task)
        task["revision"] = 2
        task["payload"]["params"] = {"confirmed": False}
        resumed = self.store.accept(task)
        self.assertTrue(resumed["read_only"])
        self.assertTrue(resumed["blocked"])

    def test_active_authorization_resume_requires_exact_frozen_parameter_shape(self):
        task = remote(kind="authorization")
        first = self.store.accept(task)
        self.store.queue_report(self.report(first, status="needs_input"))
        updated = copy.deepcopy(task)
        updated.update(revision=2, read_only=False, lease_token="active-approved")
        params = {"action": "authorize_existing", "activity_id": "1234567890123456789",
                  "fingerprint": "f" * 64, "confirmed": True}
        updated["payload"].update(allow_write=True, params=params)
        resumed = self.store.accept(updated)
        self.assertFalse(resumed["read_only"])
        self.assertFalse(resumed["blocked"])
        malformed = copy.deepcopy(updated)
        malformed.update(revision=3, lease_token="malformed")
        malformed["payload"]["params"] = {**params, "extra": True}
        rejected = self.store.accept(malformed)
        self.assertTrue(rejected["read_only"])
        self.assertTrue(rejected["blocked"])

    def test_explicit_plan_approval_resume_keeps_exact_generation(self):
        task = remote(read_only=True, payload={"plan_id": PLAN, "allow_write": False})
        original = self.store.accept(task)
        self.store.queue_report(self.report(original, status="needs_input"))
        updated = copy.deepcopy(task)
        updated.update(revision=2, read_only=False, lease_token="approved")
        updated["payload"].update(allow_write=True, params={"action": "approve_plan", "confirmed": True})
        resumed = self.store.accept(updated)
        self.assertFalse(resumed["read_only"])
        self.assertFalse(resumed["blocked"])
        self.assertEqual(resumed["created"], original["created"])
        self.assertEqual(resumed["local_id"], PLAN)

    def test_global_worker_lock_is_independent_of_state_directory(self):
        with w.global_worker_lock():
            with self.assertRaises(RuntimeError):
                with w.global_worker_lock():
                    pass

    def test_new_activity_module_receives_confirmed_params_and_guarded_runtime(self):
        params = {"template_id": "123", "fingerprint": "f" * 64,
                  "start_time": time.time() + 90, "end_time": time.time() + 900, "confirmed": True}
        task = remote(kind="authorization")
        task["payload"]["params"] = params
        row, fence = self.fence(task)
        original_runtime = native_backend.NativeRuntime
        def run(job, cfg, store, adb, parameters=None):
            self.assertEqual(parameters, params)
            self.assertTrue(cfg["pc_activity"]["allow_authorization_write"])
            self.assertIsNot(native_backend.NativeRuntime, original_runtime)
            return {"status": "needs_input", "text": "preview", "details": {"preview": {"template_id": "123"}}}
        with patch("web_activity.run", side_effect=run):
            result = self.worker.execute(row, fence)
        self.assertIn("preview", result["details"])
        self.assertIs(native_backend.NativeRuntime, original_runtime)

    def test_heartbeat_runs_in_parallel_and_cancellation_stops_final_commit(self):
        row, fence = self.fence()
        calls = []
        def heartbeat(current=None):
            calls.append(threading.current_thread().name)
            if len(calls) >= 2:
                current.observe({"task": {"revision": 2, "fenced": True}})
            return {"ok": True}
        with patch.object(w, "HEARTBEAT_SECONDS", 0.01), patch.object(self.worker, "heartbeat", side_effect=heartbeat):
            with self.worker.beating(fence):
                time.sleep(0.04)
                with self.assertRaises(w.FenceDenied):
                    fence.commit()
        self.assertIn("gateway-heartbeat", calls)

    def test_watchdog_exits_worker_only_if_business_call_stalls(self):
        row, fence = self.fence()
        with patch.object(w, "HEARTBEAT_SECONDS", 0.005), patch.object(w, "STALL_SECONDS", 0.01), \
                patch.object(w.os, "_exit") as exit_worker, patch.object(native_backend, "NativeAccount") as account:
            with self.worker.beating(fence):
                time.sleep(0.025)
        exit_worker.assert_called_with(75)
        account.assert_not_called()


class GatewayHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.isolated_lock = patch.object(w.tempfile, "gettempdir", return_value=self.temp.name)
        self.isolated_lock.start()
        self.gateway = GatewayStore(Path(self.temp.name) / "gateway.sqlite3", worker_id="mac-native-1")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
            self.gateway, "synthetic-user", "synthetic-worker", public_origin="http://127.0.0.1"))
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        # Runtime bound port is an independent test surface; Host is enforced.
        self.server.RequestHandlerClass = make_handler(self.gateway, "synthetic-user", "synthetic-worker",
            public_origin=f"http://127.0.0.1:{self.port}")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = w.GatewayClient(f"http://127.0.0.1:{self.port}", "synthetic-worker")
        self.store = w.WorkerStore(Path(self.temp.name) / "worker.sqlite3")
        self.worker = w.Worker(self.store, self.client, "mac-native-1", CFG, "synthetic-adb")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.isolated_lock.stop()
        self.temp.cleanup()

    def test_actual_http_claim_report_and_idempotent_replay(self):
        self.gateway.create({"request_id": "synthetic-request", "kind": "plan", "plan_id": PLAN, "allow_write": False})
        with patch.object(native_backend, "plan", return_value={"status": "succeeded", "text": "independent read", "reviews": [{}, {}]}) as backend:
            self.assertTrue(self.worker.run_once())
        self.assertFalse(backend.call_args.args[1]["auto_submit"])
        with self.store.connect() as db:
            body = json.loads(db.execute("SELECT body FROM gateway_reports").fetchone()[0])
        response = self.client.post("/api/worker/report", body)
        self.assertEqual(response["task"]["status"], "succeeded")
        self.assertFalse(self.store.pending())

    def test_actual_http_gate_and_cancel_fencing(self):
        created = self.gateway.create({"request_id": "synthetic-write", "kind": "plan", "plan_id": PLAN, "allow_write": True})
        claimed = self.client.post("/api/worker/claim", {"worker_id": "mac-native-1"})["task"]
        row = self.store.accept(claimed)
        fence = w.LeaseFence(self.store, self.client, "mac-native-1", row, CFG)
        fence.preflight()
        self.gateway.cancel(created["task"]["id"], {"expected_revision": 1})
        fence.observe(self.worker.heartbeat(fence))
        with self.assertRaises(w.FenceDenied):
            fence.commit()
        self.assertIsNone(self.store.remote(row["id"])["gate_attempt_at"])

    def test_gateway_token_errors_are_sanitized_and_typed(self):
        bad = w.GatewayClient(f"http://127.0.0.1:{self.port}", "never-display-this")
        with self.assertRaises(w.GatewayUnavailable) as ctx:
            bad.post("/api/worker/claim", {"worker_id": "mac-native-1"})
        self.assertEqual(ctx.exception.http_status, 401)
        self.assertEqual(ctx.exception.error_code, "unauthorized")
        self.assertNotIn("never-display", str(ctx.exception))

    def test_remote_plain_http_rejected(self):
        with self.assertRaises(ValueError):
            w.GatewayClient("http://example.com", "token")

    def test_probe_is_metadata_only_and_claims_nothing(self):
        config = Path(self.temp.name) / "worker.json"
        config.write_text(json.dumps(CFG))
        with patch.dict(w.os.environ, {"GATEWAY_WORKER_TOKEN": "synthetic-worker"}), \
                patch.object(native_backend, "inspect_link") as inspect, \
                patch.object(native_backend, "plan") as plan, \
                patch("builtins.print") as output:
            result = w.main(["--server", f"http://127.0.0.1:{self.port}", "--config", str(config),
                             "--state-dir", str(Path(self.temp.name) / "probe"), "--probe",
                             "--catalog-db", str(Path(self.temp.name) / "missing.sqlite3")])
        self.assertEqual(result, 0)
        inspect.assert_not_called()
        plan.assert_not_called()
        self.assertEqual(json.loads(output.call_args.args[0])["gateway"], "reachable")
        self.assertTrue(self.gateway.status()["worker"]["online"])

    def test_bearer_request_never_follows_redirect(self):
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/token-target")
                self.send_header("Content-Length", "0")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = w.GatewayClient(f"http://127.0.0.1:{server.server_address[1]}", "private-token")
            with self.assertRaises(w.GatewayUnavailable) as ctx:
                client.post("/api/worker/claim", {"worker_id": "mac-native-1"})
            self.assertEqual(str(ctx.exception), "Gateway redirects are blocked")
            self.assertNotIn("private-token", str(ctx.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
