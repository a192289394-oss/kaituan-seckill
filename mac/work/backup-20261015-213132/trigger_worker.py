"""Outbound Mac worker with persistent final fencing and report replay.

Final dispatch order: local fence intent -> atomic gateway gate -> existing
native permit.consume -> sole native write. An uncertain gate is never retried.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, HTTPSHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution_store import Store, adb_executable, build_plan_scheme, ROOT
from web_catalog import name_key
import android_runtime
import native_backend
import pc_jobs
from native_commit import ActivityPermit, NativeDispatchDenied
from native_plan_journal import PlanPermit
from native_account import NativeAccountUnavailable
from native_http_api import DispatchReceiptUnavailable, safe_status_message
from native_webview_api import SubmissionUncertain
from pc_executor import NeedsReview

BUILD = "trigger-worker-20261015-v5-emulator-autostart"
HEARTBEAT_SECONDS = 30
HEALTH_PROBE_SECONDS = 60
HEALTH_COMMAND_TIMEOUT = 3
LEASE_SECONDS = 90
STALL_SECONDS = 600
OPERATION_SUFFIX = re.compile(r"\s*(?:[-—–·•|\uff5c/,_:：，。]\s*)?(秒杀|开团)\s*$")
BUSINESS_PACKAGE = "com.bytedance.ls.merchant"
NATIVE_HELPER = "kaituan-frida-server"


class GatewayUnavailable(RuntimeError):
    def __init__(self, message, http_status=None, error_code=None):
        super().__init__(message)
        self.http_status, self.error_code = http_status, error_code


class FenceDenied(NativeDispatchDenied):
    pass


class InputNeeded(RuntimeError):
    def __init__(self, reason, candidates=None):
        super().__init__(reason)
        self.candidates = candidates or []


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def positive_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(label + " must be a finite positive number")
    return value


def stable_target_ids(target):
    """Return catalog-backed identifiers used to join aliases to one entity."""
    if not isinstance(target, dict):
        return frozenset()
    values=[]
    for key in ("entity_id", "root_id", "root_life_account_id", "merchant_id"):
        value=target.get(key)
        if value is not None and not isinstance(value,bool) and str(value):
            values.append(str(value))
    return frozenset(values)


def account_scope(accounts):
    if not isinstance(accounts,list) or any(not isinstance(value,str) or not value for value in accounts):
        raise ValueError("Exact authorization accounts required")
    return frozenset(accounts)


def safe_native_diagnostic(exc, cfg):
    """Match observed failures to fixed text; never report raw transport errors."""
    if not isinstance(exc, NativeAccountUnavailable):
        return {}
    message = str(exc)
    known = [
        ("正在处理其他任务", "native_lock_busy", "App 原生执行端正被其他任务占用。",
         "保留当前任务，等待现有原生执行端释放锁后重试。"),
        ("BlueStacks 暂未连接", "emulator_not_connected", "BlueStacks 尚未连上本机调试端口。",
         "已按配置尝试启动模拟器；启动完成前保持只读，不会修改系统镜像。"),
        ("BlueStacks root 尚未就绪", "root_not_ready", "BlueStacks 的既有 root 环境尚未就绪。",
         "等待模拟器启动并核验既有 root；不会自动修改镜像。"),
        ("已安装原生服务版本不一致", "runtime_version_mismatch", "已安装原生连接服务与 Python Frida 版本不一致。",
         "需要核验已安装版本；不会自动替换二进制。"),
        ("原生连接服务未启动；不终止其他监听进程", "runtime_start_failed", "尝试恢复既有原生连接服务未成功。",
         "需只读核对既有服务和回环端口；不会终止其它监听程序。"),
        ("原生连接服务启动后未读到进程", "runtime_start_unconfirmed", "启动既有原生连接服务后仍未确认进程。",
         "保留任务，待既有服务进程可读后再恢复。"),
        ("原生连接服务进程身份未唯一确认", "runtime_process_ambiguous", "原生连接服务进程身份未唯一确认。",
         "保留任务，先核验唯一既有连接服务；不会猜测或终止未知进程。"),
        ("原生连接服务未启动", "runtime_not_running", "原生连接服务尚未启动。",
         "开启运行环境自动恢复时，仅启动本机已安装的原生连接服务。"),
        ("来客 App 尚未启动", "app_not_running", "来客 App 尚未确认启动。",
         "开启运行环境自动恢复时正常启动来客，并重新读取进程身份。"),
        ("来客进程身份未唯一确认", "app_process_ambiguous", "来客进程身份未唯一确认。",
         "保留任务，先核验唯一 App 进程；不会猜测或终止未知进程。"),
        ("当前授权目录未唯一定位", "account_directory_ambiguous", "当前授权目录未唯一定位指定商家账号。",
         "先核验指定公司与门店目录，不用相似酒店代替。"),
        ("App 实际公司或门店身份尚未核验通过", "account_scope_unverified", "App 当前公司或门店身份尚未核验通过。",
         "重新读取指定商家身份，核验一致之前保持只读。"),
        ("App 门店与公司关系不符", "merchant_relation_mismatch", "App 返回的门店与指定公司关系不一致。",
         "需核验商家目录关系，身份一致之前阻断提交。"),
        ("App 内部门店切换未成功", "merchant_switch_unconfirmed", "App 内部门店切换未确认成功。",
         "等待正常账号切换恢复，再独立读取当前身份。"),
        ("App 切换后身份未稳定", "merchant_identity_unstable", "App 切换后身份还未稳定。",
         "继续只读回查身份；不把切换延迟判为业务提交失败。"),
    ]
    detail = None
    for marker, code, reason, hint in known:
        if marker in message:
            detail = {"diagnostic_code": code, "diagnostic": reason, "recovery_hint": hint}
            break
    if detail is None:
        low = message.lower()
        if "timed out" in low or "timeout" in low or "超时" in message:
            detail = {"diagnostic_code": "native_timeout", "diagnostic": "原生账号服务读取超时。",
                      "recovery_hint": "保留任务等待连接恢复，恢复后先只读核验。"}
        else:
            detail = {"diagnostic_code": "native_account_unavailable", "diagnostic": "原生账号服务暂不可连接，具体原因尚未分类。",
                      "recovery_hint": "保留任务并只读核验原生服务、App 进程和连接；不重发已提交请求。"}
    detail["runtime_autostart"] = (cfg.get("android_device") or {}).get("autostart") is True
    return detail


def load_config(path):
    # Only business settings. No credential, listener or notification fields.
    source = json.loads(Path(path).read_text())
    age = positive_number(source.get("execution_max_age_seconds", 86400), "execution lifetime")
    device = source.get("android_device") or {}
    endpoint = device.get("adb_endpoint") or source.get("serial") or "127.0.0.1:5555"
    if not re.fullmatch(r"127\.0\.0\.1:\d{1,5}", endpoint) or not 1024 <= int(endpoint.rsplit(":", 1)[1]) <= 65535:
        raise ValueError("Explicit BlueStacks loopback endpoint required")
    return {"serial": endpoint, "max_task_age_seconds": age, "execution_max_age_seconds": age,
            "auto_submit": False,
            "android_device": {"backend": "bluestacks", "execution_backend": "native_api",
                               "adb_endpoint": endpoint, "instance": device.get("instance", "Tiramisu64"),
                               "autostart": device.get("autostart") is True},
            "pc_activity": {"allow_authorization_write": False,
                            "allow_authorization_copy": (source.get("pc_activity") or {}).get("allow_authorization_copy") is True}}


class GatewayClient:
    def __init__(self, server, token, timeout=15, ca_file=None):
        parsed = urlsplit(server)
        local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
        if (parsed.scheme != "https" and not local) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("HTTPS server or loopback test server required")
        if not token or "\n" in token or "\r" in token:
            raise ValueError("GATEWAY_WORKER_TOKEN required")
        self.server, self.token, self.timeout = server.rstrip("/"), token, timeout
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                raise GatewayUnavailable("Gateway redirects are blocked")
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=context))

    def post(self, path, payload):
        request = Request(self.server + path, data=encode(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise GatewayUnavailable("Gateway response too large")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise GatewayUnavailable("Gateway response shape invalid")
            return data
        except HTTPError as exc:
            code = None
            try:
                code = json.loads(exc.read(65536)).get("error")
                if not isinstance(code, str) or not re.fullmatch(r"[a-z_]{1,80}", code):
                    code = None
            except (ValueError, OSError):
                pass
            raise GatewayUnavailable("Gateway HTTP " + str(exc.code), exc.code, code) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise GatewayUnavailable("Gateway request unavailable") from None


class WorkerStore(Store):
    def __init__(self, path):
        super().__init__(path)
        self.active_fence = None
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS gateway_tasks(
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, local_id TEXT NOT NULL,
              created REAL NOT NULL, received REAL NOT NULL, payload TEXT NOT NULL,
              revision INTEGER NOT NULL, lease_token TEXT NOT NULL, read_only INTEGER NOT NULL,
              cancel_requested INTEGER NOT NULL DEFAULT 0, blocked INTEGER NOT NULL DEFAULT 0,
              gate_attempt_at REAL, gateway_committed INTEGER NOT NULL DEFAULT 0,
              pending_report TEXT, report_sent INTEGER NOT NULL DEFAULT 0,
              last_status TEXT, last_heartbeat REAL NOT NULL DEFAULT 0,
              authorization_peer_review TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS gateway_local_identity ON gateway_tasks(kind,local_id);
            CREATE TABLE IF NOT EXISTS gateway_reports(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              body TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS dispatch_receipts(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              observed_at REAL NOT NULL, phase TEXT NOT NULL, http INTEGER,
              status_code INTEGER, status_msg TEXT NOT NULL,
              request_body_sha TEXT, response_sha TEXT, error_class TEXT);
            """)
            columns={row[1] for row in db.execute("PRAGMA table_info(gateway_tasks)")}
            if "authorization_peer_review" not in columns:
                db.execute("ALTER TABLE gateway_tasks ADD COLUMN authorization_peer_review TEXT")
        os.chmod(self.path, 0o600)

    def submission_gate(self, task, cfg, stage):
        if not self.active_fence:
            raise FenceDenied("Gateway final gate context missing")
        self.active_fence.preflight()
        return super().submission_gate(task, cfg, stage)

    def catalog_from(self, source):
        with self.connect() as db:
            seeded = db.execute("SELECT value FROM meta WHERE key='catalog_seeded'").fetchone()
            if seeded:
                return db.execute("SELECT COUNT(*) FROM merchant_catalog").fetchone()[0]
        source = Path(source).resolve()
        if source == Path(self.path).resolve():
            raise ValueError("Source and worker database must differ")
        if not source.is_file():
            return 0
        origin = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        try:
            rows = origin.execute("SELECT entity_id,name,data,updated FROM merchant_catalog").fetchall()
        finally:
            origin.close()
        with self.connect() as db:
            for row in rows:
                db.execute("INSERT OR REPLACE INTO merchant_catalog VALUES(?,?,?,?)", row)
            db.execute("INSERT OR REPLACE INTO meta VALUES('catalog_seeded',?)", (str(time.time()),))
        return len(rows)

    def remote(self, task_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM gateway_tasks WHERE id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def record_dispatch_receipt(self, task_id, summary):
        def digest(value):
            return value if isinstance(value,str) and re.fullmatch(r"[0-9a-f]{64}",value) else None
        phase=summary.get("phase")
        if phase not in {"response_received","transport_exception","scope_verified","business_rejected",
                         "http_rejected","post_response_scope_error","response_parse_error","dispatch_exception"}:
            raise ValueError("Unknown dispatch receipt phase")
        kind=summary.get("error_class")
        kind=kind if isinstance(kind,str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}",kind) else None
        with self.connect() as db:
            db.execute("INSERT INTO dispatch_receipts(task_id,observed_at,phase,http,status_code,status_msg,request_body_sha,response_sha,error_class) VALUES(?,?,?,?,?,?,?,?,?)",
                       (task_id,time.time(),phase,
                        summary.get("http") if type(summary.get("http")) is int else None,
                        summary.get("status_code") if type(summary.get("status_code")) is int else None,
                        safe_status_message(summary.get("status_msg","")),
                        digest(summary.get("request_body_sha")),digest(summary.get("response_sha")),kind))

    def receipt_brief(self, task_id):
        with self.connect() as db:
            row=db.execute("SELECT phase,http,status_code FROM dispatch_receipts WHERE task_id=? ORDER BY id DESC LIMIT 1",
                           (task_id,)).fetchone()
        if not row:return None
        phase,http,code=row
        if phase=="post_response_scope_error":
            reason,hint="native_scope_after_response_unverified","接口返回成功码后，身份读取尚未完成；继续独立只读核验。"
        elif http is not None and http!=200:
            reason,hint="native_http_rejected","平台接口没有返回可确认的 HTTP 成功响应；维持只读复核。"
        elif code is not None and code!=0:
            reason,hint="native_business_rejected","平台返回业务拒绝码，保留本次提交记录；不会自动重发。"
        elif phase=="scope_verified":
            reason,hint="native_response_received","接口响应和提交后身份读取已完成；仍以两轮业务结果复核为准。"
        elif phase=="transport_exception":
            reason,hint="native_transport_unconfirmed","没有取得完整接口响应，保留提交日志，只读复核。"
        else:
            reason,hint="native_response_unconfirmed","接口响应尚未完成核验，维持只读复核。"
        return {"receipt_phase":phase,"http_status":http,"platform_status_code":code,
                "response_diagnostic_code":reason,"response_hint":hint}

    def committed(self, remote):
        with self.connect() as db:
            if remote["kind"] == "plan":
                row = db.execute("SELECT dispatched_at FROM native_plan_journal WHERE task_id=?", (remote["local_id"],)).fetchone()
            elif remote["kind"] == "authorization":
                row = db.execute("SELECT commit_at FROM activity_journal WHERE job_id=?", (remote["local_id"],)).fetchone()
            else:
                row = None
        return bool(remote["gateway_committed"] or row and row[0] is not None)

    def fenced(self, remote):
        return remote["gate_attempt_at"] is not None or self.committed(remote)

    def authorization_peer_state(self, remote, target, accounts):
        """Find another same-entity job that may already have published.

        A gateway task ID is not a business idempotency key because the public
        hotel text may be an alias.  The resolved catalog target and overlapping
        creator accounts are the durable business scope on this Mac.
        """
        wanted_ids=stable_target_ids(target);wanted_accounts=account_scope(accounts)
        if not wanted_ids or not wanted_accounts:
            raise ValueError("Resolved authorization scope is incomplete")
        with self.connect() as db:
            rows=db.execute("""SELECT g.id,g.last_status,g.gate_attempt_at,g.gateway_committed,
                       a.target,a.accounts,a.stage,j.commit_at
                    FROM gateway_tasks g JOIN activity_jobs a ON a.id=g.local_id
                    LEFT JOIN activity_journal j ON j.job_id=a.id
                    WHERE g.kind='authorization' AND g.id<>?""",(remote["id"],)).fetchall()
        pending=[];succeeded=[]
        for row in rows:
            dispatched=(row["gate_attempt_at"] is not None or bool(row["gateway_committed"])
                or row["commit_at"] is not None or row["stage"] in pc_jobs.POST_COMMIT)
            if not dispatched:continue
            try:
                peer_target=json.loads(row["target"]);peer_accounts=account_scope(json.loads(row["accounts"]))
            except (TypeError,ValueError,json.JSONDecodeError):
                # A dispatched record with unreadable scope is not safe evidence
                # that a new overlapping write may proceed.
                pending.append(row["id"]);continue
            if not stable_target_ids(peer_target).intersection(wanted_ids) or not peer_accounts.intersection(wanted_accounts):
                continue
            if row["last_status"]=="succeeded":succeeded.append(row["id"])
            else:pending.append(row["id"])
        return {"pending":sorted(pending),"succeeded":sorted(succeeded),
            "dispatched":bool(pending or succeeded)}

    def authorization_peer_reviewed(self,remote,state):
        if not state["succeeded"]:return True
        try:review=json.loads(remote.get("authorization_peer_review") or "null")
        except (TypeError,ValueError,json.JSONDecodeError):return False
        return (isinstance(review,dict) and review.get("peers")==state["succeeded"]
            and type(review.get("revision")) is int and remote["revision"]>review["revision"])

    def record_authorization_peer_review(self,remote,state):
        if not state["succeeded"]:return
        value=encode({"peers":state["succeeded"],"revision":remote["revision"]})
        with self.connect() as db:
            db.execute("UPDATE gateway_tasks SET authorization_peer_review=? WHERE id=?",
                       (value,remote["id"]))

    def accept(self, task):
        tid, kind = task.get("id"), task.get("kind")
        if not isinstance(tid, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", tid) or kind not in ("plan", "authorization", "inspect"):
            raise ValueError("Invalid gateway task identity")
        payload = task.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Invalid gateway payload")
        revision, lease = task.get("revision"), task.get("lease_token")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("Invalid gateway revision")
        if not isinstance(lease, str) or not lease:
            raise ValueError("Missing lease token")
        created = positive_number(task.get("created"), "created")
        if created > time.time() + 60:
            raise ValueError("Task created in future")
        local = plan_id(payload) if kind in ("plan", "inspect") else "gateway:" + tid
        read_only = task.get("read_only") is not False or payload.get("allow_write") is not True
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM gateway_tasks WHERE id=?", (tid,)).fetchone()
            if old:
                if old["kind"] != kind or old["local_id"] != local:
                    raise ValueError("Remote task identity cannot change")
                previous = json.loads(old["payload"])
                changed = old["revision"] != revision or old["payload"] != encode(payload)
                same_identity = all(previous.get(k) == payload.get(k) for k in ("hotel", "accounts", "entity_id"))
                params = payload.get("params")
                never_committed = not self.fenced(dict(old))
                schedule_fields = {"template_id", "fingerprint", "start_time", "end_time", "confirmed"}
                active_fields = {"action", "activity_id", "fingerprint", "confirmed"}
                schedule_resume = (kind == "authorization" and same_identity and old["last_status"] == "needs_input"
                                   and never_committed
                                   and isinstance(params, dict) and params.get("confirmed") is True
                                   and set(params) == schedule_fields
                                   and task.get("read_only") is False and payload.get("allow_write") is True)
                active_resume = (kind == "authorization" and same_identity and old["last_status"] == "needs_input"
                                 and never_committed and isinstance(params, dict) and set(params) == active_fields
                                 and params.get("action") == "authorize_existing" and params.get("confirmed") is True
                                 and task.get("read_only") is False and payload.get("allow_write") is True)
                plan_resume = (kind == "plan" and same_identity and old["last_status"] == "needs_input"
                               and never_committed and isinstance(params, dict) and params.get("confirmed") is True
                               and params.get("action") == "approve_plan" and task.get("read_only") is False
                               and payload.get("allow_write") is True)
                authorized_resume = schedule_resume or active_resume or plan_resume
                if not same_identity:
                    raise ValueError("Immutable hotel/account identity changed")
                db.execute("UPDATE gateway_tasks SET payload=?,revision=?,lease_token=?,read_only=?,"
                           "blocked=CASE WHEN ? THEN 0 ELSE MAX(blocked,?) END,cancel_requested=MAX(cancel_requested,?),"
                           "gateway_committed=MAX(gateway_committed,?),last_heartbeat=?,report_sent=0 WHERE id=?",
                           (encode(payload) if authorized_resume else old["payload"], revision, lease,
                            int(read_only or changed and not authorized_resume), int(authorized_resume),
                            int(changed and not authorized_resume), int(task.get("cancel_requested") is True),
                            int(task.get("committed") is True), time.time(), tid))
            else:
                db.execute("INSERT INTO gateway_tasks(id,kind,local_id,created,received,payload,revision,lease_token,read_only,cancel_requested,gateway_committed,last_heartbeat) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (tid, kind, local, created, time.time(), encode(payload), revision, lease, int(read_only),
                            int(task.get("cancel_requested") is True), int(task.get("committed") is True), time.time()))
        return self.remote(tid)

    def pending(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT pending_report FROM gateway_tasks WHERE pending_report IS NOT NULL ORDER BY received")]

    def queue_report(self, report):
        with self.connect() as db:
            db.execute("UPDATE gateway_tasks SET pending_report=?,last_status=?,report_sent=0 WHERE id=?",
                       (encode(report), report["status"], report["task_id"]))
            db.execute("INSERT INTO gateway_reports(task_id,body,state,updated) VALUES(?,?,'pending',?)",
                       (report["task_id"], encode(report), time.time()))

    def report_ack(self, task_id):
        with self.connect() as db:
            db.execute("UPDATE gateway_tasks SET pending_report=NULL,report_sent=1 WHERE id=?", (task_id,))
            db.execute("UPDATE gateway_reports SET state='acknowledged',updated=? WHERE task_id=? AND state='pending'",
                       (time.time(), task_id))

    def archive_stale_report(self, task_id):
        with self.connect() as db:
            db.execute("UPDATE gateway_tasks SET pending_report=NULL,blocked=1 WHERE id=?", (task_id,))
            db.execute("UPDATE gateway_reports SET state='stale_lease_retained',updated=? WHERE task_id=? AND state='pending'",
                       (time.time(), task_id))


# Gateway clock may run slightly ahead of this Mac; a task claimed within the
# same second must not silently lose write permission.
CLOCK_SKEW_SECONDS = 120


def log_event(event, **fields):
    """Key lifecycle events to stdout (LaunchAgent stdout.log). No tokens."""
    fields.pop("lease_token", None)
    line = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event}
    line.update(fields)
    print(json.dumps(line, ensure_ascii=False, default=str), flush=True)


def plan_id(payload):
    value = payload.get("plan_id")
    if not isinstance(value, str) or not re.fullmatch(r"\d{10,25}", value):
        raise ValueError("Exact plan ID required")
    return value


class LeaseFence:
    def __init__(self, store, client, worker_id, remote, cfg):
        self.store, self.client, self.worker_id, self.cfg = store, client, worker_id, cfg
        self.id, self.revision, self.lease = remote["id"], remote["revision"], remote["lease_token"]
        self.lock = threading.RLock()
        self.receipt_failed = False
        self.authorization_target = None
        self.authorization_accounts = None

    def bind_authorization_scope(self,target,accounts):
        self.authorization_target=copy.deepcopy(target)
        self.authorization_accounts=sorted(account_scope(accounts))

    def check_authorization_peers(self):
        if self.authorization_target is None:return
        remote=self.store.remote(self.id)
        state=self.store.authorization_peer_state(remote,self.authorization_target,self.authorization_accounts)
        if state["pending"] or state["succeeded"] and not self.store.authorization_peer_reviewed(remote,state):
            raise FenceDenied("Another same-entity authorization task reached a durable dispatch boundary")

    def packet(self):
        return {"worker_id": self.worker_id, "task_id": self.id, "lease_token": self.lease, "revision": self.revision}

    def observe(self, response):
        data = response.get("task") if isinstance(response.get("task"), dict) else response
        with self.store.connect() as db:
            revision = data.get("revision", self.revision)
            cancelled = data.get("cancel_requested") is True
            blocked = (revision != self.revision or data.get("read_only") is True
                       or data.get("allowed") is False or data.get("fenced") is True)
            db.execute("UPDATE gateway_tasks SET blocked=MAX(blocked,?),cancel_requested=MAX(cancel_requested,?),last_heartbeat=? WHERE id=?",
                       (int(blocked), int(cancelled), time.time(), self.id))

    def check(self):
        remote, now = self.store.remote(self.id), time.time()
        if (remote["read_only"] or remote["blocked"] or remote["cancel_requested"] or remote["revision"] != self.revision
                or remote["lease_token"] != self.lease or remote["gate_attempt_at"] is not None
                or now - remote["last_heartbeat"] >= LEASE_SECONDS
                or not 0 <= now - remote["created"] <= self.cfg["execution_max_age_seconds"]):
            raise FenceDenied("Gateway lease, revision, write permission or lifetime changed; no send")

    def preflight(self):
        with self.lock:
            self.check()
            response = self.client.post("/api/worker/gate", dict(self.packet(), stage="preflight"))
            self.observe(response)
            if response.get("allowed") is not True:
                raise FenceDenied("Gateway preflight denied; no send")
            self.check()

    def commit(self):
        with self.lock:
            self.preflight()
            self.check()
            # BEFORE network: a lost success response must never permit another send.
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute(
                    "UPDATE gateway_tasks SET gate_attempt_at=? WHERE id=? AND gate_attempt_at IS NULL "
                    "AND blocked=0 AND cancel_requested=0 AND read_only=0 AND revision=? AND lease_token=?",
                    (time.time(), self.id, self.revision, self.lease)).rowcount
                if changed != 1:
                    raise FenceDenied("Durable gateway fence already consumed")
            response = self.client.post("/api/worker/gate", dict(self.packet(), stage="commit"))
            self.observe(response)
            if response.get("allowed") is not True or response.get("committed") is not True or response.get("revision", self.revision) != self.revision:
                raise FenceDenied("Gateway commit denied or uncertain; no send, audit-only")
            with self.store.connect() as db:
                db.execute("UPDATE gateway_tasks SET gateway_committed=1 WHERE id=?", (self.id,))


class FencedPlanPermit(PlanPermit):
    def __init__(self, original, fence, scope_guard=None):
        self.original, self.fence, self.scope_guard = original, fence, scope_guard

    def consume(self, root, body):
        self.fence.commit()
        if self.scope_guard:
            self.scope_guard()
        self.original.consume(root, body)


class FencedActivityPermit(ActivityPermit):
    def __init__(self, original, fence, scope_guard=None):
        self.original, self.fence, self.scope_guard = original, fence, scope_guard

    def consume(self, root, body):
        # Recheck immediately before consuming either the gateway or local
        # one-shot permit. This catches a peer that crossed its boundary after
        # the worker's initial scope check.
        self.fence.check_authorization_peers()
        self.fence.commit()
        if self.scope_guard:
            self.scope_guard()
        self.original.consume(root, body)


class FencedApi:
    def __init__(self, original, fence):
        self.original, self.fence = original, fence
        self.last_receipt = None
        self.original.dispatch_receipt_callback = self.record_receipt

    def record_receipt(self, summary):
        self.last_receipt = dict(summary)
        try:
            self.fence.store.record_dispatch_receipt(self.fence.id, summary)
        except Exception:
            self.fence.receipt_failed = True
            raise DispatchReceiptUnavailable("响应记录不可用；提交许可已消费，只允许复核。") from None

    def final_receipt(self, phase, error_class=None):
        if self.last_receipt is None:
            return
        summary=dict(self.last_receipt,phase=phase,error_class=error_class)
        self.record_receipt(summary)

    def submit_guarded(self, method, body, permit):
        try:
            result=method(body,permit)
            self.final_receipt("scope_verified")
            return result
        except SubmissionUncertain as exc:
            cause=exc.__cause__
            if isinstance(cause,DispatchReceiptUnavailable):
                self.fence.receipt_failed=True
                raise
            if self.last_receipt:
                summary=self.last_receipt
                if summary.get("phase")=="transport_exception":phase="transport_exception"
                elif summary.get("http") is not None and summary.get("http")!=200:phase="http_rejected"
                elif summary.get("http") is None:phase="response_parse_error"
                elif summary.get("status_code") not in (None,0):phase="business_rejected"
                elif summary.get("status_code")==0:phase="post_response_scope_error"
                else:phase="response_parse_error"
                try:self.final_receipt(phase,type(cause).__name__ if cause else type(exc).__name__)
                except DispatchReceiptUnavailable as failed:
                    raise SubmissionUncertain("响应记录不可用；仅进行只读结果复核。") from failed
            raise
        except DispatchReceiptUnavailable as exc:
            raise SubmissionUncertain("响应记录不可用；仅进行只读结果复核。") from exc

    def __getattr__(self, name):
        return getattr(self.original, name)

    def __enter__(self):
        self.original.__enter__()
        return self

    def __exit__(self, *args):
        return self.original.__exit__(*args)

    def submit_plan_once(self, body, permit):
        return self.submit_guarded(self.original.submit_plan_once,body,
                                   FencedPlanPermit(permit,self.fence,self.original.assert_scope))

    def submit_activity_once(self, body, permit):
        return self.submit_guarded(self.original.submit_activity_once,body,
                                   FencedActivityPermit(permit,self.fence,self.original.assert_scope))


@contextmanager
def fenced_backend(fence):
    # Process-local reference only; protected by the global worker lock.
    api_class, runtime_class = native_backend.NativeHttpApi, native_backend.NativeRuntime
    class GuardedRuntime(runtime_class):
        def __enter__(self):
            super().__enter__()
            self.api = FencedApi(self.api, fence)
            return self
    native_backend.NativeHttpApi = lambda *a, **kw: FencedApi(api_class(*a, **kw), fence)
    native_backend.NativeRuntime = GuardedRuntime
    try:
        yield
    finally:
        native_backend.NativeHttpApi, native_backend.NativeRuntime = api_class, runtime_class


def exact_target(store, payload):
    with store.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute("SELECT data FROM merchant_catalog ORDER BY name")]
    entity = payload.get("entity_id")
    hints = payload.get("hints") or ([payload.get("hotel")] if payload.get("hotel") else [])
    resolution = None
    if entity:
        matches = [r for r in rows if r.get("entity_id") == entity]
    elif isinstance(hints, list) and len(hints) == 1 and isinstance(hints[0], str):
        original = hints[0]
        key = name_key(original)
        matches = [r for r in rows if key and key in {name_key(n) for n in [r["name"]] + r.get("aliases", [])}]
        # An exact catalog name always wins, including a legitimate hotel name
        # that itself ends in these characters. Only when the raw input has no
        # exact match may one trailing operation word be removed.
        if not matches:
            found = OPERATION_SUFFIX.search(original)
            hotel = original[:found.start()].rstrip() if found else ""
            key = name_key(hotel)
            if key:
                matches = [r for r in rows if key in {name_key(n) for n in [r["name"]] + r.get("aliases", [])}]
                if len(matches) == 1:
                    resolution = {"input": original, "operation": found.group(1),
                                  "resolved_hotel": matches[0]["name"],
                                  "match_mode": "exact_name_key_after_operation_suffix"}
    else:
        matches = []
    candidates = [{"entity_id": r["entity_id"], "name": r["name"], "parent_name": r.get("parent_name", "")} for r in matches]
    if len(matches) != 1:
        raise InputNeeded("酒店目录没有唯一匹配到指定门店，请选择完整、精确的酒店名称；尚未提交。", candidates)
    if not matches[0].get("merchant_id"):
        raise InputNeeded("指定酒店的目录缺少商家身份，请先补齐身份信息；尚未提交。", candidates)
    target = copy.deepcopy(matches[0])
    if resolution:
        target["hotel_resolution"] = resolution
    return target


class Worker:
    def __init__(self, store, client, worker_id, cfg, adb=None):
        self.store, self.client, self.worker_id, self.cfg = store, client, worker_id, cfg
        self.adb = adb or adb_executable()
        self._health_lock = threading.Lock()
        self._runtime_health = None
        self._runtime_health_at = 0.0

    def _health_command(self, args):
        """Run one bounded, read-only ADB observation without connecting or starting anything."""
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=HEALTH_COMMAND_TIMEOUT)
            return result.returncode, result.stdout.strip(), "completed"
        except subprocess.TimeoutExpired:
            return None, "", "timeout"
        except OSError:
            return None, "", "unavailable"

    def _observe_runtime_health(self):
        checked = time.time()
        serial = self.cfg["serial"]
        base = [self.adb, "-s", serial]
        runtime = {
            "checked_at": checked,
            "probe_interval_seconds": HEALTH_PROBE_SECONDS,
            "android_device": {"status": "unknown", "reason": "not_checked"},
            "root": {"status": "unknown", "reason": "android_not_ready"},
            "business_app": {"status": "unknown", "reason": "android_not_ready", "package": BUSINESS_PACKAGE},
            "native_interface": {"status": "unknown", "reason": "android_not_ready"},
        }

        code, state, outcome = self._health_command(base + ["get-state"])
        if outcome == "timeout":
            runtime["android_device"] = {"status": "unavailable", "reason": "adb_timeout"}
            return runtime
        if outcome != "completed" or code != 0 or state != "device":
            runtime["android_device"] = {"status": "unavailable", "reason": "adb_not_device"}
            return runtime
        runtime["android_device"] = {"status": "available", "reason": "adb_device"}

        code, identity, outcome = self._health_command(base + ["shell", "su -c id"])
        if outcome == "timeout":
            runtime["root"] = {"status": "unknown", "reason": "root_probe_timeout"}
        elif outcome == "completed" and code == 0 and "uid=0(root)" in identity:
            runtime["root"] = {"status": "available", "reason": "uid_0"}
        else:
            runtime["root"] = {"status": "unavailable", "reason": "uid_0_not_confirmed"}

        code, app_pid, outcome = self._health_command(base + ["shell", "pidof " + BUSINESS_PACKAGE])
        app_pids = app_pid.split() if outcome == "completed" and code == 0 else []
        if outcome == "timeout":
            runtime["business_app"] = {"status": "unknown", "reason": "app_probe_timeout", "package": BUSINESS_PACKAGE}
        elif len(app_pids) == 1 and app_pids[0].isdigit():
            runtime["business_app"] = {"status": "running", "reason": "unique_process", "package": BUSINESS_PACKAGE}
        elif app_pids:
            runtime["business_app"] = {"status": "unknown", "reason": "process_not_unique", "package": BUSINESS_PACKAGE}
        else:
            runtime["business_app"] = {"status": "stopped", "reason": "process_absent", "package": BUSINESS_PACKAGE}

        if runtime["root"]["status"] != "available":
            runtime["native_interface"] = {"status": "unavailable", "reason": "root_required"}
            return runtime
        if runtime["business_app"]["status"] != "running":
            reason = "app_not_running" if runtime["business_app"]["status"] == "stopped" else "app_process_unconfirmed"
            runtime["native_interface"] = {"status": "unavailable", "reason": reason}
            return runtime

        code, helper_pid, outcome = self._health_command(base + ["shell", "su -c 'pidof " + NATIVE_HELPER + "'"])
        helper_pids = helper_pid.split() if outcome == "completed" and code == 0 else []
        if outcome == "timeout":
            runtime["native_interface"] = {"status": "unknown", "reason": "helper_probe_timeout"}
        elif len(helper_pids) != 1 or not helper_pids[0].isdigit():
            runtime["native_interface"] = {"status": "unavailable", "reason": "helper_process_absent_or_ambiguous"}
        else:
            # PID checks are intentionally weaker than a Frida attach. Heartbeats
            # must never attach to the App, switch an account, or issue a business read.
            runtime["native_interface"] = {
                "status": "unknown",
                "reason": "processes_present_attach_not_probed",
                "helper_process": "running",
            }
        return runtime

    def runtime_health(self, probe=True):
        now = time.monotonic()
        with self._health_lock:
            if not probe and self._runtime_health is None:
                return {"checked_at": None, "probe_interval_seconds": HEALTH_PROBE_SECONDS,
                        "android_device": {"status": "unknown", "reason": "metadata_probe_skipped"},
                        "root": {"status": "unknown", "reason": "metadata_probe_skipped"},
                        "business_app": {"status": "unknown", "reason": "metadata_probe_skipped", "package": BUSINESS_PACKAGE},
                        "native_interface": {"status": "unknown", "reason": "metadata_probe_skipped"}}
            if (self._runtime_health is None or
                    probe and now - self._runtime_health_at >= HEALTH_PROBE_SECONDS):
                self._runtime_health = self._observe_runtime_health()
                self._runtime_health_at = now
            return copy.deepcopy(self._runtime_health)

    def health(self, probe_runtime=True):
        with self.store.connect() as db:
            return {"build": BUILD, "backend": "native_api",
                    "catalog_count": db.execute("SELECT COUNT(*) FROM merchant_catalog").fetchone()[0],
                    "pending_reports": db.execute("SELECT COUNT(*) FROM gateway_tasks WHERE pending_report IS NOT NULL").fetchone()[0],
                    "runtime": self.runtime_health(probe_runtime)}

    def flush_reports(self):
        for report in self.store.pending():
            try:
                response = self.client.post("/api/worker/report", report)
            except GatewayUnavailable as exc:
                if exc.http_status == 409 and exc.error_code in {"stale_revision", "stale_lease", "lease_expired"}:
                    self.store.archive_stale_report(report["task_id"])
                    continue
                raise
            acknowledged = response.get("task")
            if response.get("ok") is not True and (not isinstance(acknowledged, dict) or acknowledged.get("id") != report["task_id"]):
                raise GatewayUnavailable("Gateway report not acknowledged")
            self.store.report_ack(report["task_id"])

    def heartbeat(self, fence=None, probe_runtime=True):
        payload = {"worker_id": self.worker_id, "health": self.health(probe_runtime)}
        if fence:
            payload.update(task_id=fence.id, lease_token=fence.lease)
        response = self.client.post("/api/worker/heartbeat", payload)
        if fence:
            fence.observe(response)
        return response

    @contextmanager
    def beating(self, fence):
        stop, started = threading.Event(), time.monotonic()
        def loop():
            while not stop.wait(HEARTBEAT_SECONDS):
                if time.monotonic() - started > STALL_SECONDS:
                    # Restart worker via launchd; never terminate or reset the App.
                    os._exit(75)
                try:
                    self.heartbeat(fence)
                except Exception:
                    with self.store.connect() as db:
                        db.execute("UPDATE gateway_tasks SET blocked=1 WHERE id=?", (fence.id,))
        self.heartbeat(fence)
        thread = threading.Thread(target=loop, name="gateway-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=20)

    def local_plan(self, remote):
        with self.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO tasks VALUES(?,?,?,'running','queued','','','',?,?)",
                       (remote["local_id"], "", build_plan_scheme(remote["local_id"]), remote["created"], time.time()))
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (remote["local_id"],)).fetchone()
            if row["created"] != remote["created"]:
                raise InputNeeded("该计划已有另一代任务绑定，本次仅允许核验；不会覆盖已有提交记录。")
            db.execute("UPDATE tasks SET status='running',updated=? WHERE task_id=?", (time.time(), remote["local_id"]))
            if self.store.fenced(remote):
                db.execute("UPDATE tasks SET stage='verifying' WHERE task_id=?", (remote["local_id"],))
            return dict(db.execute("SELECT * FROM tasks WHERE task_id=?", (remote["local_id"],)).fetchone())

    def activity_scope(self,remote,payload):
        with self.store.connect() as db:
            old=db.execute("SELECT target,accounts FROM activity_jobs WHERE id=?",(remote["local_id"],)).fetchone()
        if old:
            try:return json.loads(old["target"]),sorted(account_scope(json.loads(old["accounts"])))
            except (TypeError,ValueError,json.JSONDecodeError) as exc:
                raise InputNeeded("本机已有任务的商家或账号范围不完整；保持只读，未提交。") from exc
        target=exact_target(self.store,payload)
        accounts=payload.get("accounts")
        if (not isinstance(accounts,list) or not accounts
                or any(not isinstance(a,str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}",a) for a in accounts)):
            raise InputNeeded("请提供本次要授权的精确抖音账号；尚未提交。")
        return target,list(dict.fromkeys(accounts))

    def local_activity(self, remote, payload, target=None, accounts=None):
        with self.store.connect() as db:
            old = db.execute("SELECT * FROM activity_jobs WHERE id=?", (remote["local_id"],)).fetchone()
        if old:
            with self.store.connect() as db:
                db.execute("UPDATE activity_jobs SET status='running',updated=? WHERE id=?", (time.time(), remote["local_id"]))
                if self.store.fenced(remote):
                    db.execute("UPDATE activity_jobs SET stage='verifying' WHERE id=?", (remote["local_id"],))
                return dict(db.execute("SELECT * FROM activity_jobs WHERE id=?", (remote["local_id"],)).fetchone())
        if target is None or accounts is None:target,accounts=self.activity_scope(remote,payload)
        with self.store.connect() as db:
            db.execute("INSERT INTO activity_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (remote["local_id"], "authorization", "", "", "", encode(payload.get("hints", [])),
                        encode(accounts), encode(target), "running", "created", "", remote["created"], time.time()))
            return dict(db.execute("SELECT * FROM activity_jobs WHERE id=?", (remote["local_id"],)).fetchone())

    def prepare_android(self, cfg):
        """Reconnect the configured emulator before any business call.

        Heartbeats stay read-only. This runs only when a task is about to use
        the native account and autostart is explicitly enabled.
        """
        try:
            result = android_runtime.probe(cfg, self.adb, allow_launch=True)
        except (subprocess.TimeoutExpired, OSError):
            raise NativeAccountUnavailable(
                "BlueStacks 暂未连接，等待模拟器启动或 ADB 恢复（" + cfg["serial"] + "）")
        if getattr(result, "returncode", 1) or (getattr(result, "stdout", "") or "").strip() != "device":
            raise NativeAccountUnavailable(android_runtime.unavailable_message(cfg, result))

    def execute(self, remote, fence):
        payload, cfg = json.loads(remote["payload"]), copy.deepcopy(self.cfg)
        can_write = (payload.get("allow_write") is True and not remote["read_only"] and not remote["blocked"]
                     and not remote["cancel_requested"] and not self.store.fenced(remote)
                     and -CLOCK_SKEW_SECONDS <= time.time() - remote["created"] <= cfg["execution_max_age_seconds"])
        activity_target=activity_accounts=peer_state=None;peer_review_required=False
        parameters=payload.get("params")
        if remote["kind"]=="authorization":
            activity_target,activity_accounts=self.activity_scope(remote,payload)
            peer_state=self.store.authorization_peer_state(remote,activity_target,activity_accounts)
            fence.bind_authorization_scope(activity_target,activity_accounts)
            if peer_state["pending"]:
                status="waiting_review" if self.store.fenced(remote) else "needs_review"
                result={"status":status,
                    "text":"同一商家实体、重叠抖音号的另一任务已进入提交边界，结果尚未确认；本任务保持只读，未调用平台预检查或提交。",
                    "details":{"reason":"overlapping_authorization_pending","blocked":True}}
                resolution=activity_target.get("hotel_resolution")
                if isinstance(resolution,dict):
                    result.update(hotel=resolution["resolved_hotel"],
                        evidence={"hotel_resolution":copy.deepcopy(resolution)})
                return result
            if peer_state["succeeded"] and not self.store.authorization_peer_reviewed(remote,peer_state):
                # A completed peer is evidence to re-read the business source,
                # never permission to reuse this task's stale confirmation.
                can_write=False;parameters=None;peer_review_required=True
        cfg["auto_submit"] = can_write
        cfg["pc_activity"]["allow_authorization_write"] = can_write
        if (android_runtime.emulator(cfg) and remote["kind"] != "inspect"
                and (cfg.get("android_device") or {}).get("autostart") is True):
            self.prepare_android(cfg)
        if remote["kind"] == "inspect":
            found = native_backend.inspect_link(remote["local_id"], cfg, self.store, self.adb)
            return {"status": "succeeded", "text": "已完成原生接口只读检查，没有执行业务写入。", "hotel": found.get("hotel"),
                    "state": found["observation"]["state"], "evidence": found.get("evidence")}
        self.store.active_fence = fence
        try:
            with fenced_backend(fence):
                if remote["kind"] == "plan":
                    task = self.local_plan(remote)
                    result = native_backend.plan(task, cfg, self.store, self.adb, review_only=self.store.fenced(remote))
                    result["hotel"] = task.get("resolved_hotel") or task.get("hotel")
                    return result
                import web_activity
                job = self.local_activity(remote,payload,activity_target,activity_accounts)
                result = web_activity.run(job,cfg,self.store,self.adb,parameters=parameters)
                if peer_review_required:
                    self.store.record_authorization_peer_review(remote,peer_state)
                target = json.loads(job["target"])
                resolution = target.get("hotel_resolution")
                if isinstance(resolution, dict):
                    evidence = result.get("evidence")
                    evidence = copy.deepcopy(evidence) if isinstance(evidence, dict) else {}
                    evidence["hotel_resolution"] = copy.deepcopy(resolution)
                    result["hotel"] = resolution["resolved_hotel"]
                    result["evidence"] = evidence
                return result
        finally:
            self.store.active_fence = None

    def run_once(self):
        # Failed reports replay before claims. Never re-execute to rebuild a report.
        self.flush_reports()
        claimed = self.client.post("/api/worker/claim", {"worker_id": self.worker_id})
        if not claimed.get("task"):
            self.heartbeat()
            return False
        remote = self.store.accept(claimed["task"])
        log_event("claimed", task_id=remote["id"], kind=remote["kind"], local_id=remote["local_id"],
                  read_only=bool(remote["read_only"]), revision=remote["revision"])
        fence = LeaseFence(self.store, self.client, self.worker_id, remote, self.cfg)
        details = {}
        try:
            with self.beating(fence):
                result = self.execute(self.store.remote(remote["id"]), fence)
            status = {"queued": "waiting_device", "needs_review": "needs_input"}.get(result.get("status"), result.get("status"))
            if status not in ("succeeded", "waiting_review", "waiting_device", "needs_input", "failed"):
                status = "needs_input"
            details = result.get("details") or {}
            if result.get("reviews"):
                details["independent_reviews"] = len(result["reviews"])
            public_result = {k: result[k] for k in ("text", "hotel", "state", "evidence") if k in result}
            if status == "needs_input":
                details["reason"] = result.get("text", "还需要确认业务参数。")
                details["parameters_applied"] = False
        except (InputNeeded, NeedsReview) as exc:
            status, public_result = "needs_input", {"text": str(exc)}
            details = {"reason": str(exc), "candidates": getattr(exc, "candidates", []), "parameters_applied": False}
        except (FenceDenied, GatewayUnavailable):
            current = self.store.remote(remote["id"])
            status = "waiting_review" if self.store.fenced(current) else "needs_input"
            public_result = {"text": "任务租约、版本或最终提交许可已变化，已阻断写入；保留任务进行只读复核。"}
            details = {"reason": "gateway_fence", "dispatch_confirmed": False}
        except Exception as exc:
            current = self.store.remote(remote["id"])
            status = "waiting_review" if self.store.fenced(current) else "waiting_device"
            public_result = {"text": "原生接口暂未读到可核验的结果，保留任务等待恢复；没有把读取中断判为业务失败。"}
            details = {"reason": type(exc).__name__, "dispatch_confirmed": False}
            diagnostic = safe_native_diagnostic(exc, self.cfg)
            details.update(diagnostic)
            if diagnostic:
                public_result["text"] = diagnostic["diagnostic"] + " " + diagnostic["recovery_hint"]
        current = self.store.remote(remote["id"])
        if fence.receipt_failed:
            details.update(response_diagnostic_code="response_record_unavailable",
                           response_hint="响应记录不可用；安全提交日志已经消费，只允许只读复核。")
        elif self.store.fenced(current):
            try:
                brief=self.store.receipt_brief(remote["id"])
                if brief:details.update(brief)
                else:details.update(response_diagnostic_code="response_record_unavailable",
                                    response_hint="这次提交没有可用的持久响应记录；保留原提交日志，仅继续只读复核。")
            except Exception:
                details.update(response_diagnostic_code="response_record_unavailable",
                               response_hint="响应记录暂不可读；保留原提交日志，仅继续只读复核。")
        report = {"worker_id": self.worker_id, "task_id": remote["id"], "lease_token": remote["lease_token"],
                  "revision": remote["revision"], "status": status, "result": public_result, "details": details,
                  "committed": self.store.committed(current)}
        log_event("result", task_id=remote["id"], kind=remote["kind"], status=status,
                  committed=report["committed"], text=str((public_result or {}).get("text", ""))[:200],
                  reason=str(details.get("reason", ""))[:120] if isinstance(details, dict) else "")
        self.store.queue_report(report)
        self.flush_reports()
        return True


@contextmanager
def global_worker_lock():
    path = Path(tempfile.gettempdir()) / ("kaituan-trigger-worker-" + str(os.getuid()) + ".lock")
    handle = os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR, 0o600), "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("Another Mac worker owns the global lock") from None
    try:
        yield
    finally:
        handle.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "outputs/trigger-worker.json")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "work/trigger-worker")
    parser.add_argument("--worker-id", default="mac-native-1")
    parser.add_argument("--ca-file", type=Path, help="Optional trusted gateway CA; hostname verification remains enabled")
    parser.add_argument("--catalog-db", type=Path, default=ROOT / "work/trigger-worker/catalog.sqlite3",
                        help="One-time read-only directory seed; no legacy work imported")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--once", action="store_true")
    action.add_argument("--probe", action="store_true", help="Metadata heartbeat only; no Android access or claim")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", args.worker_id):
        parser.error("Invalid worker ID")
    cfg = load_config(args.config)
    client = GatewayClient(args.server, os.environ.get("GATEWAY_WORKER_TOKEN", ""), ca_file=args.ca_file)
    with global_worker_lock():
        args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(args.state_dir, 0o700)
        store = WorkerStore(args.state_dir / "worker.sqlite3")
        store.catalog_from(args.catalog_db)
        worker = Worker(store, client, args.worker_id, cfg)
        if args.probe:
            worker.heartbeat(probe_runtime=False)
            print(encode(dict(worker.health(False), gateway="reachable")))
            return 0
        while True:
            try:
                worker.run_once()
            except GatewayUnavailable:
                if args.once:
                    print(encode({"gateway": "unavailable", "pending_reports_retained": True}))
                    return 2
            if args.once:
                return 0
            time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
