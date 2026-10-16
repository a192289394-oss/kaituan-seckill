#!/usr/bin/env python3
"""Outbound-only Mac trigger gateway. No Android, chat transport or historical import.

The server records intent; it cannot execute native business writes. Workers must
call /api/worker/gate twice (preflight, commit) and persist their native journal
before sending. A committed task can only be recovered for read-only review.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote

BUILD = "trigger-gateway-20261015-v5-platform-rejected"
MAX_REVIEW_ATTEMPTS = 24
LEASE_SECONDS = 90
TASK_SECONDS = 86400
SESSION_SECONDS = 12 * 3600
MAX_BODY = 65536
TERMINAL = {"succeeded", "failed", "cancelled", "expired"}
REPORT_STATES = {"succeeded", "waiting_review", "waiting_device", "needs_input", "failed"}
SENSITIVE_KEYS = re.compile(r"(?:token|cookie|password|secret|credential|authorization_header|headers|storage_state|raw_response|_raw)", re.I)
PLAN_ID = re.compile(r"^[0-9]{18,20}$")
WORKER_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")


class APIError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def token_equal(a, b):
    return isinstance(a, str) and isinstance(b, str) and hmac.compare_digest(a.encode(), b.encode())


def safe_json(value, secrets_to_remove=(), depth=0):
    """Store evidence summaries, never transport credentials or unbounded logs."""
    if depth > 12:
        return "[too deeply nested]"
    if isinstance(value, dict):
        return {str(k)[:120]: "[redacted]" if SENSITIVE_KEYS.search(str(k)) else safe_json(v, secrets_to_remove, depth + 1)
                for k, v in list(value.items())[:120]}
    if isinstance(value, list):
        return [safe_json(v, secrets_to_remove, depth + 1) for v in value[:200]]
    if isinstance(value, str):
        value = value[:8000]
        for secret in secrets_to_remove:
            if secret:
                value = value.replace(secret, "[redacted]")
        value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]{12,}", r"\1[redacted]", value)
        value = re.sub(r"(?i)((?:token|password|cookie|secret)\s*[=:]\s*)[^\s,;]+", r"\1[redacted]", value)
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def validate_payload(body):
    if not isinstance(body, dict):
        raise APIError(400, "invalid_body", "JSON object required")
    allowed = {"request_id", "kind", "plan_id", "hotel", "accounts", "allow_write", "read_only"}
    if set(body) - allowed:
        raise APIError(400, "unknown_fields", "Task contains unsupported fields")
    request_id = body.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id):
        raise APIError(400, "request_id", "request_id must be a stable string of 1-128 characters")
    kind = body.get("kind")
    if kind not in {"plan", "authorization", "inspect"}:
        raise APIError(400, "kind", "kind must be plan, authorization or inspect")
    for flag in ("allow_write", "read_only"):
        if flag in body and type(body[flag]) is not bool:
            raise APIError(400, flag, flag + " must be boolean")
    allow_write = body.get("allow_write", False)
    read_only = body.get("read_only", not allow_write)
    if allow_write and read_only:
        raise APIError(400, "write_conflict", "allow_write and read_only conflict")
    if not allow_write:
        read_only = True
    # Plan submit means execute: ignore client allow_write=false / confirm UX.
    if kind == "plan":
        allow_write = True
        read_only = False
    if kind == "inspect":
        if allow_write:
            raise APIError(400, "inspect_read_only", "inspect cannot authorize writes")
        read_only = True
    payload = {"kind": kind, "allow_write": allow_write, "read_only": read_only}
    if kind in {"plan", "inspect"}:
        plan_id = body.get("plan_id")
        if not isinstance(plan_id, str) or not PLAN_ID.fullmatch(plan_id):
            raise APIError(400, "plan_id", "plan_id must be an exact 18-20 digit string")
        if body.get("accounts"):
            raise APIError(400, "plan_accounts", "Plan identity is resolved from plan_id, not accounts")
        payload["plan_id"] = plan_id
        # Hotel text is advisory only. It never selects the plan's company or POI.
        if body.get("hotel") is not None:
            if not isinstance(body["hotel"], str) or len(body["hotel"]) > 200:
                raise APIError(400, "hotel", "hotel must be a string of at most 200 characters")
            payload["hotel"] = body["hotel"].strip()
        key = kind + ":" + plan_id
    else:
        hotel, accounts = body.get("hotel"), body.get("accounts")
        if not isinstance(hotel, str) or not hotel.strip() or len(hotel) > 200:
            raise APIError(400, "hotel", "Authorization requires one exact hotel")
        if not isinstance(accounts, list) or not 1 <= len(accounts) <= 40:
            raise APIError(400, "accounts", "Authorization requires 1-40 explicit accounts")
        if any(not isinstance(a, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", a) for a in accounts):
            raise APIError(400, "accounts", "Accounts must be exact platform identifiers")
        if len(set(accounts)) != len(accounts):
            raise APIError(400, "accounts", "Accounts contain duplicates")
        if body.get("plan_id") is not None:
            raise APIError(400, "authorization_plan", "Authorization does not bind a plan_id")
        payload.update(hotel=hotel.strip(), accounts=accounts)
        key = "authorization:" + hashlib.sha256(canonical([hotel.strip(), sorted(accounts)]).encode()).hexdigest()
    return request_id, payload, key


class GatewayStore:
    def __init__(self, db, *, worker_id=None, clock=time.time, secret_values=()):
        self.db = str(db)
        self.clock = clock
        self.secrets = tuple(secret_values)
        self.lock = threading.RLock()
        Path(self.db).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    fingerprint TEXT NOT NULL, business_key TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                    deadline REAL NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    worker_id TEXT, lease_token TEXT, lease_until REAL, lease_revision INTEGER,
                    read_only INTEGER NOT NULL, committed INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt REAL NOT NULL DEFAULT 0, result TEXT, details TEXT);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, at REAL NOT NULL,
                    event TEXT NOT NULL, details TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, task_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS report_receipts(task_id TEXT NOT NULL, lease_hash TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(task_id,lease_hash));
                CREATE TABLE IF NOT EXISTS mutation_receipts(task_id TEXT NOT NULL, action TEXT NOT NULL,
                    revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(task_id,action,revision));
                CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, expires REAL NOT NULL);
            """)
            conn.execute("INSERT OR REPLACE INTO meta VALUES('build',?)", (BUILD,))
            conn.execute("INSERT OR IGNORE INTO requests SELECT request_id,fingerprint,id FROM tasks")
            if worker_id:
                self._worker(conn, worker_id)
        os.chmod(self.db, 0o600)

    @contextmanager
    def tx(self):
        with self.lock:
            conn = sqlite3.connect(self.db, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def event(self, conn, task_id, name, details=None):
        conn.execute("INSERT INTO events(task_id,at,event,details) VALUES(?,?,?,?)",
                     (task_id, self.clock(), name, canonical(safe_json(details or {}, self.secrets))))

    def _worker(self, conn, worker_id):
        if not isinstance(worker_id, str) or not WORKER_ID.fullmatch(worker_id):
            raise APIError(400, "worker_id", "Invalid worker_id")
        current = conn.execute("SELECT value FROM meta WHERE key='worker_id'").fetchone()
        if current and current[0] != worker_id:
            raise APIError(409, "worker_pinned", "Gateway is bound to a different worker")
        if not current:
            conn.execute("INSERT INTO meta VALUES('worker_id',?)", (worker_id,))
            self.event(conn, None, "worker_bound", {"worker_id": worker_id})

    def _task(self, conn, task_id):
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise APIError(404, "not_found", "Task not found")
        return row

    def public_task(self, row, *, claim=False):
        task = {k: row[k] for k in ("id", "request_id", "kind", "status", "created", "updated", "deadline", "revision", "worker_id", "attempts", "next_attempt")}
        task.update(payload=json.loads(row["payload"]), read_only=bool(row["read_only"]),
                    committed=bool(row["committed"]), cancel_requested=bool(row["cancel_requested"]),
                    result=json.loads(row["result"]) if row["result"] else None,
                    details=json.loads(row["details"]) if row["details"] else None)
        if claim:
            task.update(lease_token=row["lease_token"], lease_until=row["lease_until"])
        return task

    def create(self, body):
        request_id, payload, business_key = validate_payload(body)
        fingerprint = hashlib.sha256(canonical(payload).encode()).hexdigest()
        with self.tx() as conn:
            # Expiration cannot depend on somebody opening the task list first.
            # Otherwise a stale needs_input task can reserve this intent forever.
            self._expire(conn)
            request = conn.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
            if request:
                if request["fingerprint"] != fingerprint:
                    raise APIError(409, "request_conflict", "request_id already identifies another payload")
                return {"task": self.public_task(self._task(conn, request["task_id"])), "duplicate": True}
            existing = conn.execute("SELECT * FROM tasks WHERE business_key=?", (business_key,)).fetchone()
            supersedes = None
            # A hotel/account authorization describes a time-varying business
            # relationship.  Once its prior task is terminal, a fresh request must
            # run a fresh source read and may start a new schedule.  Preserve the
            # old task and request-id receipt by archiving only its dedupe key.
            # Plan IDs remain permanently deduplicated because repeating an exact
            # plan can repeat an irreversible consent.
            if existing and payload["kind"] in {"authorization", "inspect"} and existing["status"] in TERMINAL:
                supersedes = existing["id"]
                archived_key = business_key + ":terminal:" + existing["id"]
                conn.execute("UPDATE tasks SET business_key=? WHERE id=?", (archived_key, existing["id"]))
                self.event(conn, existing["id"], "intent_released", {"status": existing["status"], "next_request_id": request_id})
                existing = None
            if existing:
                conn.execute("INSERT INTO requests VALUES(?,?,?)", (request_id, fingerprint, existing["id"]))
                self.event(conn, existing["id"], "duplicate_intent", {"request_id": request_id})
                return {"task": self.public_task(existing), "duplicate": True, "business_duplicate": True}
            now, task_id = self.clock(), secrets.token_hex(16)
            conn.execute("""INSERT INTO tasks(id,request_id,fingerprint,business_key,kind,payload,status,created,updated,deadline,read_only)
                            VALUES(?,?,?,?,?,?,'queued',?,?,?,?)""",
                         (task_id, request_id, fingerprint, business_key, payload["kind"], canonical(payload), now, now, now + TASK_SECONDS, int(payload["read_only"])))
            self.event(conn, task_id, "created", {"kind": payload["kind"], "read_only": payload["read_only"],
                                                   "supersedes_task_id": supersedes})
            conn.execute("INSERT INTO requests VALUES(?,?,?)", (request_id, fingerprint, task_id))
            return {"task": self.public_task(self._task(conn, task_id)), "duplicate": False}

    def list_tasks(self):
        with self.tx() as conn:
            self._expire(conn)
            return {"tasks": [self.public_task(r) for r in conn.execute("SELECT * FROM tasks ORDER BY created DESC LIMIT 200")]}

    def _expire(self, conn):
        now = self.clock()
        for row in conn.execute("SELECT * FROM tasks WHERE committed=0 AND deadline<=? AND status IN ('queued','waiting_device','needs_input')", (now,)).fetchall():
            conn.execute("UPDATE tasks SET status='expired',updated=?,revision=revision+1 WHERE id=?", (now, row["id"]))
            self.event(conn, row["id"], "expired")

    def status(self):
        with self.tx() as conn:
            self._expire(conn)
            meta = dict(conn.execute("SELECT key,value FROM meta"))
            counts = {r[0]: r[1] for r in conn.execute("SELECT status,count(*) FROM tasks GROUP BY status")}
            last = float(meta.get("worker_heartbeat", "0"))
            online = bool(last and self.clock() - last <= LEASE_SECONDS)
            return {"build": BUILD, "worker": {"id": meta.get("worker_id"), "last_heartbeat": last or None,
                    "online": online, "gateway_online": online,
                    "health": json.loads(meta.get("worker_health", "{}"))}, "queue": counts,
                    "execution": "mac_outbound_only", "lease_seconds": LEASE_SECONDS}

    def claim(self, worker_id):
        with self.tx() as conn:
            self._worker(conn, worker_id)
            self._expire(conn)
            now = self.clock()
            conn.execute("INSERT OR REPLACE INTO meta VALUES('worker_heartbeat',?)", (str(now),))
            running = conn.execute("SELECT * FROM tasks WHERE status IN ('running','cancel_requested') ORDER BY created LIMIT 1").fetchone()
            if running and running["lease_until"] and running["lease_until"] > now:
                return {"task": None, "busy": True}
            row = running or conn.execute("""SELECT * FROM tasks WHERE status IN ('queued','waiting_review','waiting_device')
                        AND next_attempt<=? AND (committed=1 OR deadline>?) ORDER BY created LIMIT 1""", (now, now)).fetchone()
            if not row:
                return {"task": None}
            if row["worker_id"] and row["worker_id"] != worker_id:
                raise APIError(409, "owner_conflict", "Claimed task cannot move to another worker")
            # Lost lease is never permission to repeat an uncertain write. Recovery
            # from running is always read-only, even if commit was not acknowledged.
            recovery = bool(running)
            readonly = bool(row["read_only"] or row["committed"] or row["cancel_requested"] or recovery)
            lease = secrets.token_urlsafe(32)
            state = "cancel_requested" if row["cancel_requested"] and not row["committed"] else "running"
            conn.execute("""UPDATE tasks SET status=?,worker_id=?,lease_token=?,lease_until=?,lease_revision=revision,
                         read_only=?,attempts=attempts+1,updated=? WHERE id=?""",
                         (state, worker_id, lease, now + LEASE_SECONDS, int(readonly), now, row["id"]))
            self.event(conn, row["id"], "reclaimed" if recovery else "claimed", {"worker_id": worker_id, "read_only": readonly})
            return {"task": self.public_task(self._task(conn, row["id"]), claim=True)}

    def _lease(self, conn, body, *, check_revision=True):
        self._worker(conn, body.get("worker_id"))
        row = self._task(conn, body.get("task_id"))
        token = body.get("lease_token")
        if (row["worker_id"] != body.get("worker_id") or not isinstance(token, str) or
                not row["lease_token"] or not hmac.compare_digest(row["lease_token"], token)):
            raise APIError(409, "stale_lease", "Lease does not own this task")
        if row["status"] not in {"running", "cancel_requested"} or not row["lease_until"] or row["lease_until"] <= self.clock():
            raise APIError(409, "lease_expired", "Lease is no longer active")
        if check_revision and (row["lease_revision"] != row["revision"] or
              ("revision" in body and (type(body["revision"]) is not int or body["revision"] != row["revision"]))):
            raise APIError(409, "stale_revision", "Task changed; stop writes and reclaim for read-only review")
        return row

    def heartbeat(self, body):
        with self.tx() as conn:
            self._worker(conn, body.get("worker_id"))
            now = self.clock()
            if body.get("task_id"):
                row = self._lease(conn, body, check_revision=False)
                # A cancelled, fenced worker must not keep an obsolete lease alive
                # indefinitely. Its journal remains intact and next claim recovers
                # the same task for read-only cancellation acknowledgment.
                if row["lease_revision"] == row["revision"]:
                    conn.execute("UPDATE tasks SET lease_until=? WHERE id=?", (now + LEASE_SECONDS, row["id"]))
                task = self.public_task(self._task(conn, row["id"]), claim=True)
                task["fenced"] = row["lease_revision"] != row["revision"]
            else:
                task = None
            health = safe_json(body.get("health", {}), self.secrets)
            if not isinstance(health, dict):
                health = {}
            conn.execute("INSERT OR REPLACE INTO meta VALUES('worker_heartbeat',?)", (str(now),))
            conn.execute("INSERT OR REPLACE INTO meta VALUES('worker_health',?)", (canonical(health),))
            return {"ok": True, "task": task, "lease_seconds": LEASE_SECONDS}

    def gate(self, body):
        stage = body.get("stage")
        if stage not in {"preflight", "commit"}:
            raise APIError(400, "stage", "gate stage must be preflight or commit")
        if type(body.get("revision")) is not int:
            raise APIError(400, "revision", "gate requires exact claim revision")
        with self.tx() as conn:
            row = self._lease(conn, body)
            if row["cancel_requested"] or row["read_only"] or row["committed"]:
                return {"allowed": False, "read_only": True, "committed": bool(row["committed"]), "reason": "read_only_or_cancelled"}
            if row["deadline"] <= self.clock():
                raise APIError(409, "task_expired", "Task is outside its execution window")
            if stage == "commit":
                prior = conn.execute("SELECT 1 FROM events WHERE task_id=? AND event='preflight_gate' AND details=?",
                                     (row["id"], canonical({"revision": row["revision"], "attempt": row["attempts"]}))).fetchone()
                if not prior:
                    raise APIError(409, "preflight_required", "Preflight gate must pass on this claim before commit")
                conn.execute("UPDATE tasks SET committed=1,read_only=1,updated=? WHERE id=?", (self.clock(), row["id"]))
            self.event(conn, row["id"], "commit_reserved" if stage == "commit" else "preflight_gate", {"revision": row["revision"], "attempt": row["attempts"]})
            return {"allowed": True, "committed": stage == "commit", "revision": row["revision"], "read_only": stage == "commit"}

    def report(self, body):
        status = body.get("status")
        if status not in REPORT_STATES:
            raise APIError(400, "status", "Unsupported report status")
        if "committed" in body and type(body["committed"]) is not bool:
            raise APIError(400, "committed", "committed must be boolean")
        with self.tx() as conn:
            self._worker(conn, body.get("worker_id"))
            lease_token = body.get("lease_token")
            if not isinstance(lease_token, str) or not lease_token:
                raise APIError(409, "stale_lease", "Lease does not own this task")
            lease_hash = hashlib.sha256(lease_token.encode()).hexdigest()
            report_fingerprint = hashlib.sha256(canonical(body).encode()).hexdigest()
            receipt = conn.execute("SELECT * FROM report_receipts WHERE task_id=? AND lease_hash=?",
                                   (body.get("task_id"), lease_hash)).fetchone()
            if receipt:
                if receipt["fingerprint"] != report_fingerprint:
                    raise APIError(409, "report_conflict", "Lease already accepted a different report")
                return json.loads(receipt["response"])
            row = self._lease(conn, body)
            now = self.clock()
            committed = bool(row["committed"] or body.get("committed"))
            result = safe_json(body.get("result"), self.secrets + (lease_token,))
            details = safe_json(body.get("details", {}), self.secrets + (lease_token,))
            platform_rejected = (status == "failed" and isinstance(body.get("details"), dict)
                                 and body["details"].get("platform_rejected") is True)
            if committed and status in {"failed", "waiting_device"} and not platform_rejected:
                status = "waiting_review"
            if row["cancel_requested"] and not committed:
                status = "cancelled"
            if status == "waiting_review" and (now > row["deadline"] or row["attempts"] >= MAX_REVIEW_ATTEMPTS):
                # Stop endless read-only polling; a human must look at it now.
                if not isinstance(details, dict):
                    details = {}
                details["review_exhausted"] = {"attempts": row["attempts"], "past_deadline": now > row["deadline"]}
                status = "needs_input"
                self.event(conn, row["id"], "review_exhausted", details["review_exhausted"])
            delay = min(300, 30 * (2 ** min(max(row["attempts"] - 1, 0), 4))) if status in {"waiting_review", "waiting_device"} else 0
            # Any task asking for human input loses write permission until a
            # new, preview-bound resume explicitly grants it again.
            readonly = bool(row["read_only"] or committed or status in {"waiting_review", "needs_input"})
            conn.execute("""UPDATE tasks SET status=?,result=?,details=?,committed=?,read_only=?,next_attempt=?,
                            updated=?,lease_token=NULL,lease_until=NULL,lease_revision=NULL WHERE id=?""",
                         (status, canonical(result), canonical(details), int(committed), int(readonly), now + delay, now, row["id"]))
            self.event(conn, row["id"], "reported", {"status": status, "committed": committed, "retry_in": delay})
            response = {"task": self.public_task(self._task(conn, row["id"])), "retry_in": delay}
            conn.execute("INSERT INTO report_receipts VALUES(?,?,?,?)", (row["id"], lease_hash, report_fingerprint, canonical(response)))
            return response

    def cancel(self, task_id, body):
        with self.tx() as conn:
            row = self._task(conn, task_id)
            expected = body.get("expected_revision")
            if type(expected) is not int or expected != row["revision"]:
                raise APIError(409, "stale_revision", "expected_revision does not match")
            if row["committed"]:
                # Commit reservation is deliberately conservative: once consumed,
                # cancellation may never restore write permission or clear journal.
                state = row["status"] if row["status"] == "running" else "waiting_review"
                conn.execute("UPDATE tasks SET cancel_requested=1,read_only=1,status=?,next_attempt=0,updated=? WHERE id=?",
                             (state, self.clock(), task_id))
                note = "Submission cannot be revoked; task will be reviewed read-only"
            elif row["status"] in TERMINAL:
                return {"task": self.public_task(row), "message": "Task is already terminal"}
            else:
                active = row["status"] in {"running", "cancel_requested"}
                state = "cancel_requested" if active else "cancelled"
                conn.execute("UPDATE tasks SET cancel_requested=1,read_only=1,status=?,revision=revision+1,updated=? WHERE id=?",
                             (state, self.clock(), task_id))
                note = "Writes fenced; claimed task remains bound until read-only acknowledgment" if active else "Cancelled before dispatch"
            self.event(conn, task_id, "cancel_requested", {"committed": bool(row["committed"]), "message": note})
            return {"task": self.public_task(self._task(conn, task_id)), "message": note}

    def resume(self, task_id, body):
        with self.tx() as conn:
            row = self._task(conn, task_id)
            expected = body.get("expected_revision")
            if type(expected) is not int:
                raise APIError(409, "stale_revision", "expected_revision does not match")
            try:
                resume_hash = hashlib.sha256(canonical(body).encode()).hexdigest()
            except ValueError:
                raise APIError(400, "schedule_time", "Input must contain finite JSON values")
            receipt = conn.execute("SELECT * FROM mutation_receipts WHERE task_id=? AND action='resume' AND revision=?", (task_id, expected)).fetchone()
            if receipt:
                if receipt["fingerprint"] != resume_hash:
                    raise APIError(409, "stale_revision", "This revision already accepted different input")
                return json.loads(receipt["response"])
            if expected != row["revision"]:
                raise APIError(409, "stale_revision", "expected_revision does not match")
            if row["status"] != "needs_input":
                raise APIError(409, "not_waiting_input", "Only needs_input tasks can be resumed")
            if row["cancel_requested"]:
                raise APIError(409, "cancelled", "Cancelled task cannot resume")
            params = body.get("params", {})
            if not isinstance(params, dict):
                raise APIError(400, "params", "params must be an object")
            forbidden = {"allow_write", "read_only", "plan_id", "hotel", "accounts", "kind", "committed", "lease_token", "price", "prices", "stock", "inventory", "products", "goods"}
            if set(params) & forbidden:
                raise APIError(400, "immutable_target", "Resume cannot alter task identity or authorize a write")
            now = self.clock()
            schedule_fields = {"template_id", "fingerprint", "start_time", "end_time", "confirmed"}
            approval = params.get("action") == "approve_plan"
            authorize_existing = params.get("action") == "authorize_existing"
            if "action" in params and not (approval or authorize_existing):
                raise APIError(400, "approval_action", "Unsupported confirmation action")
            schedule = bool(set(params) & schedule_fields) and not (approval or authorize_existing)
            if approval:
                if row["kind"] != "plan" or row["committed"] or not row["read_only"]:
                    raise APIError(409, "approval_unavailable", "Only uncommitted read-only plans awaiting input can be approved")
                details = json.loads(row["details"]) if row["details"] else {}
                preview = details.get("preview", {}) if isinstance(details, dict) else {}
                preview_fingerprint = preview.get("fingerprint") if isinstance(preview, dict) else None
                fields = {"confirmed", "action", "fingerprint"} if preview_fingerprint else {"confirmed", "action"}
                if set(params) != fields or type(params.get("confirmed")) is not bool or not params["confirmed"]:
                    raise APIError(400, "plan_confirmation", "Explicit confirmed:true and action:approve_plan required without target changes")
                if preview_fingerprint and params.get("fingerprint") != preview_fingerprint:
                    raise APIError(409, "preview_changed", "Plan preview fingerprint changed")
                if row["deadline"] <= now:
                    raise APIError(409, "task_expired", "Original execution window expired; plan cannot authorize a write")
            if authorize_existing:
                if row["kind"] != "authorization" or row["committed"] or not row["read_only"]:
                    raise APIError(409, "approval_unavailable", "Only an uncommitted read-only authorization preview can be approved")
                fields = {"confirmed", "action", "activity_id", "fingerprint"}
                if set(params) != fields or type(params.get("confirmed")) is not bool or not params["confirmed"]:
                    raise APIError(400, "authorization_confirmation", "Explicit confirmation of the frozen active-activity preview is required")
                if not isinstance(params.get("activity_id"), str) or not PLAN_ID.fullmatch(params["activity_id"]):
                    raise APIError(400, "activity_id", "activity_id must be an exact 18-20 digit string")
                if not isinstance(params.get("fingerprint"), str) or not re.fullmatch(r"[0-9a-f]{64}", params["fingerprint"]):
                    raise APIError(400, "fingerprint", "fingerprint must be a lowercase SHA256 digest")
                details = json.loads(row["details"]) if row["details"] else {}
                if not isinstance(details, dict) or details.get("blocked"):
                    raise APIError(409, "preview_changed", "Active-activity authorization preview changed or is blocked")
                preview = details.get("preview", {}) if isinstance(details.get("preview"), dict) else {}
                # Same as schedule confirm: accept frozen preview OR exactly one
                # matching candidate (multi-live needs_input ships candidates only).
                matched_preview = (
                    preview.get("mode") == "authorize_existing"
                    and not preview.get("blocked")
                    and preview.get("activity_id") == params["activity_id"]
                    and preview.get("fingerprint") == params["fingerprint"]
                )
                candidates = details.get("candidates", [])
                matches = [
                    candidate for candidate in candidates
                    if isinstance(candidate, dict)
                    and candidate.get("mode") == "authorize_existing"
                    and not candidate.get("blocked")
                    and candidate.get("activity_id") == params["activity_id"]
                    and candidate.get("fingerprint") == params["fingerprint"]
                ] if isinstance(candidates, list) else []
                if not matched_preview and len(matches) != 1:
                    raise APIError(409, "preview_changed", "Active-activity authorization preview changed or is blocked")
                if row["deadline"] <= now:
                    raise APIError(409, "task_expired", "Original execution window expired; authorization cannot be approved")
            if schedule:
                # Product 2026-10-16: refuse create-from-expired schedule confirm.
                # Frontend must not be able to submit "填时间新建秒杀".
                raise APIError(
                    409,
                    "schedule_unavailable",
                    "本店没有生效中的秒杀时不可按旧活动填时间新建；请先去抖音来客创建活动后再来加号",
                )
            payload = json.loads(row["payload"])
            write_resume = bool(schedule or approval or authorize_existing)
            payload.update(read_only=not write_resume, allow_write=write_resume, params=safe_json(params, self.secrets))
            conn.execute("""UPDATE tasks SET payload=?,read_only=1,status='queued',revision=revision+1,next_attempt=0,
                         deadline=?,updated=? WHERE id=?""", (canonical(payload), row["deadline"] if write_resume else now + TASK_SECONDS, now, task_id))
            if write_resume:
                conn.execute("UPDATE tasks SET read_only=0 WHERE id=?", (task_id,))
            note = "已收到确认，等待 Mac 重新核验并执行。" if write_resume else "补充说明已保存，等待 Mac 重新读取。"
            conn.execute("UPDATE tasks SET result=? WHERE id=?", (canonical({"text": note}), task_id))
            event_name = "plan_approved" if approval else "authorization_approved" if authorize_existing else "schedule_confirmed" if schedule else "resumed_read_only"
            self.event(conn, task_id, event_name, {"params": safe_json(params, self.secrets)})
            response = {"task": self.public_task(self._task(conn, task_id)), "message": "Confirmed authorization; executor will revalidate before any submission" if write_resume else "Resumed for read-only assessment"}
            conn.execute("INSERT INTO mutation_receipts VALUES(?,'resume',?,?,?)", (task_id, expected, resume_hash, canonical(response)))
            return response

    def retry(self, task_id, body):
        with self.tx() as conn:
            row = self._task(conn, task_id)
            if type(body.get("expected_revision")) is not int or body["expected_revision"] != row["revision"]:
                raise APIError(409, "stale_revision", "expected_revision does not match")
            if row["status"] not in {"waiting_device", "waiting_review"}:
                raise APIError(409, "not_retryable", "Task is not waiting for recovery")
            state = "waiting_review" if row["committed"] else "queued"
            conn.execute("UPDATE tasks SET status=?,next_attempt=0,updated=?,result=? WHERE id=?",
                         (state, self.clock(), canonical({"text":"已请求恢复核验，继续同一张任务。"}), task_id))
            self.event(conn, task_id, "recovery_requested", {"committed": bool(row["committed"])})
            return {"task": self.public_task(self._task(conn, task_id))}

    def audit(self, task_id):
        with self.tx() as conn:
            self._task(conn, task_id)
            return {"events": [{"at": r["at"], "event": r["event"], "details": json.loads(r["details"])}
                               for r in conn.execute("SELECT * FROM events WHERE task_id=? ORDER BY id LIMIT 500", (task_id,))]}

    def session_create(self):
        value = secrets.token_urlsafe(40)
        with self.tx() as conn:
            conn.execute("DELETE FROM sessions WHERE expires<=?", (self.clock(),))
            conn.execute("INSERT INTO sessions VALUES(?,?)", (hashlib.sha256(value.encode()).hexdigest(), self.clock() + SESSION_SECONDS))
        return value

    def session_valid(self, value):
        if not isinstance(value, str) or len(value) > 200:
            return False
        with self.tx() as conn:
            return bool(conn.execute("SELECT 1 FROM sessions WHERE hash=? AND expires>?",
                        (hashlib.sha256(value.encode()).hexdigest(), self.clock())).fetchone())

    def session_remove(self, value):
        with self.tx() as conn:
            conn.execute("DELETE FROM sessions WHERE hash=?", (hashlib.sha256(value.encode()).hexdigest(),))


def make_handler(store, user_token, worker_token, *, public_origin, allowed_hosts=None, static=None, cookie_path="/"):
    parsed = urlsplit(public_origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("GATEWAY_PUBLIC_ORIGIN must be an exact http(s) origin without path")
    origin = parsed.scheme + "://" + parsed.netloc
    hosts = set(allowed_hosts or [parsed.netloc])
    static_dir = Path(static).resolve() if static else None
    if not re.fullmatch(r"/[A-Za-z0-9_./-]*", cookie_path):
        raise ValueError("Invalid cookie path")
    login_attempts = {}
    attempts_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass  # Request paths and error text must not accidentally reveal secrets.

        def _json(self, status, value, extra=None):
            data = canonical(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            for key, val in (extra or {}).items():
                self.send_header(key, val)
            self.end_headers()
            self.wfile.write(data)

        def _host_origin(self, require_origin=False):
            if self.headers.get("Host") not in hosts:
                raise APIError(403, "host", "Host is not allowed")
            request_origin = self.headers.get("Origin")
            if request_origin and request_origin != origin:
                raise APIError(403, "origin", "Origin is not allowed")
            if require_origin and request_origin != origin:
                raise APIError(403, "origin_required", "Same-origin Origin header required")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise APIError(403, "cross_site", "Cross-site requests are blocked")

        def _body(self):
            if self.headers.get("Transfer-Encoding"):
                raise APIError(400, "transfer_encoding", "Chunked requests are unsupported")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise APIError(400, "content_length", "Invalid Content-Length")
            if not 0 < length <= MAX_BODY:
                raise APIError(413, "body_size", "JSON body must be 1-65536 bytes")
            if self.headers.get_content_type() != "application/json":
                raise APIError(415, "content_type", "application/json required")
            try:
                body = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeDecodeError):
                raise APIError(400, "json", "Invalid JSON")
            if not isinstance(body, dict):
                raise APIError(400, "body", "JSON object required")
            return body

        def _cookie(self):
            try:
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
                return cookie["gateway_session"].value if "gateway_session" in cookie else ""
            except Exception:
                return ""

        def _auth(self, *, worker=False, mutation=False):
            bearer = self.headers.get("Authorization", "")
            required = worker_token if worker else user_token
            if bearer.startswith("Bearer ") and token_equal(bearer[7:], required):
                return
            if not worker and store.session_valid(self._cookie()):
                if mutation:
                    self._host_origin(require_origin=True)
                return
            raise APIError(401, "unauthorized", "Authentication required")

        def _login(self, body):
            self._host_origin(require_origin=True)
            now = store.clock()
            ip = self.client_address[0]
            with attempts_lock:
                attempts = [at for at in login_attempts.get(ip, []) if now - at < 600]
                if len(attempts) >= 10:
                    raise APIError(429, "login_throttled", "Too many login attempts; retry later")
                attempts.append(now)
                login_attempts[ip] = attempts
            candidate = body.get("token")
            if not token_equal(candidate, user_token):
                raise APIError(401, "unauthorized", "Authentication required")
            session = store.session_create()
            flags = "; Secure" if parsed.scheme == "https" else ""
            self._json(200, {"ok": True}, {"Set-Cookie": f"gateway_session={session}; Path={cookie_path}; Max-Age={SESSION_SECONDS}; HttpOnly; SameSite=Strict{flags}"})

        def _dispatch(self, method):
            self._host_origin()
            target = urlsplit(self.path)
            path = target.path
            if target.query or target.fragment:
                raise APIError(400, "query", "Query parameters are unsupported")
            if method == "POST" and path == "/api/login":
                self._login(self._body())
                return
            if path.startswith("/api/"):
                is_worker = path.startswith("/api/worker/")
                self._auth(worker=is_worker, mutation=method == "POST")
                if method == "GET" and path == "/api/tasks":
                    result = store.list_tasks()
                elif method == "GET" and path == "/api/status":
                    result = store.status()
                elif method == "GET" and re.fullmatch(r"/api/tasks/[0-9a-f]{32}/audit", path):
                    result = store.audit(path.split("/")[3])
                elif method == "POST":
                    body = self._body()
                    if path == "/api/tasks":
                        result = store.create(body)
                    elif path == "/api/logout":
                        store.session_remove(self._cookie())
                        self._json(200, {"ok": True}, {"Set-Cookie": f"gateway_session=; Path={cookie_path}; Max-Age=0; HttpOnly; SameSite=Strict"})
                        return
                    elif path == "/api/worker/claim":
                        result = store.claim(body.get("worker_id"))
                    elif path == "/api/worker/heartbeat":
                        result = store.heartbeat(body)
                    elif path == "/api/worker/gate":
                        result = store.gate(body)
                    elif path == "/api/worker/report":
                        result = store.report(body)
                    elif re.fullmatch(r"/api/tasks/[0-9a-f]{32}/(cancel|resume|retry)", path):
                        result = getattr(store, path.rsplit("/", 1)[1])(path.split("/")[3], body)
                    else:
                        raise APIError(404, "not_found", "Endpoint not found")
                else:
                    raise APIError(404, "not_found", "Endpoint not found")
                self._json(200, result)
                return
            if method != "GET" or not static_dir:
                raise APIError(404, "not_found", "Endpoint not found")
            file_path = (static_dir / (unquote(path).lstrip("/") or "index.html")).resolve()
            if not file_path.is_relative_to(static_dir) or not file_path.is_file() or file_path.suffix not in {".html", ".css", ".js", ".svg", ".png", ".ico"}:
                raise APIError(404, "not_found", "File not found")
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _run(self, method):
            self.connection.settimeout(15)
            try:
                self._dispatch(method)
            except APIError as exc:
                self.close_connection = True
                self._json(exc.status, {"error": exc.code, "message": exc.message})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                self.close_connection = True
            except Exception:
                self.close_connection = True
                self._json(500, {"error": "internal", "message": "Gateway operation failed; no credential details logged"})

        def do_GET(self):
            self._run("GET")

        def do_POST(self):
            self._run("POST")

    return Handler


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8793)
    parser.add_argument("--db", required=True)
    parser.add_argument("--static")
    args = parser.parse_args()
    user_token, worker_token = os.environ.get("GATEWAY_USER_TOKEN"), os.environ.get("GATEWAY_WORKER_TOKEN")
    if not user_token or not worker_token or hmac.compare_digest(user_token, worker_token):
        parser.error("Distinct nonempty GATEWAY_USER_TOKEN and GATEWAY_WORKER_TOKEN are required")
    public_origin = os.environ.get("GATEWAY_PUBLIC_ORIGIN")
    if not public_origin:
        parser.error("GATEWAY_PUBLIC_ORIGIN is required")
    hosts = [h.strip() for h in os.environ.get("GATEWAY_ALLOWED_HOSTS", urlsplit(public_origin).netloc).split(",") if h.strip()]
    store = GatewayStore(args.db, worker_id=os.environ.get("GATEWAY_WORKER_ID"), secret_values=(user_token, worker_token))
    handler = make_handler(store, user_token, worker_token, public_origin=public_origin, allowed_hosts=hosts, static=args.static,
                           cookie_path=os.environ.get("GATEWAY_COOKIE_PATH", "/"))
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    server.daemon_threads = True
    print(f"{BUILD}: listening; native execution remains on the pinned Mac", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
