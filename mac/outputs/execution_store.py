"""Local business persistence for the web-triggered native executor.

No message listener, notification queue, credentials, or legacy event history.
"""
import json
import re
import shutil
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

import web_catalog as merchant_catalog
import native_plan_journal
import pc_jobs
from service_runtime import execution_age

ROOT = Path(__file__).resolve().parents[1]


class TaskCancelled(RuntimeError):
    pass


class TaskExpired(RuntimeError):
    pass


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def adb_executable():
    bundled = ROOT / "work/android-sdk/platform-tools/adb"
    return str(bundled) if bundled.exists() else (shutil.which("adb") or "adb")


def build_plan_scheme(task_id):
    if not isinstance(task_id, str) or not re.fullmatch(r"\d{10,25}", task_id):
        raise ValueError("Exact plan ID required")
    target = "https://life.douyin.com/h5/alliance/merchant/plan/oriented/info?" + urlencode(
        {"enter_from": "institution_platform", "task_id": task_id, "mode": "broker_entrance"})
    return "snssdk299467://webview?" + urlencode(
        {"trans_status_bar": "1", "hide_nav_bar": "1", "disable_bounces": "1",
         "should_full_screen": "1", "show_loading": "0", "hybrid_sdk_version": "bullet",
         "use_bdx": "1", "disable_swipe": "0", "url": target})


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS tasks(
              task_id TEXT PRIMARY KEY, hotel TEXT NOT NULL, scheme TEXT NOT NULL,
              status TEXT NOT NULL, stage TEXT NOT NULL, result TEXT NOT NULL DEFAULT '',
              chat_id TEXT NOT NULL, sender TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS result_reviews(
              run_id TEXT NOT NULL, attempt INTEGER NOT NULL, task_id TEXT NOT NULL,
              hotel TEXT NOT NULL, observed_at REAL NOT NULL, state TEXT NOT NULL,
              reason TEXT NOT NULL, PRIMARY KEY(run_id,attempt));
            CREATE TABLE IF NOT EXISTS task_controls(
              task_id TEXT PRIMARY KEY, cancelled_at REAL NOT NULL, message_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task_identity(
              task_id TEXT PRIMARY KEY, hotel TEXT NOT NULL, source_hint TEXT NOT NULL,
              verified_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS activity_jobs(
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, chat_id TEXT NOT NULL, sender TEXT NOT NULL,
              raw TEXT NOT NULL, hints TEXT NOT NULL, accounts TEXT NOT NULL, target TEXT,
              status TEXT NOT NULL, stage TEXT NOT NULL, result TEXT NOT NULL,
              created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS activity_params(
              job_id TEXT PRIMARY KEY, data TEXT NOT NULL, confirmed_at REAL,
              configured_at REAL, reviewed_at REAL);
            """)
            merchant_catalog.init_schema(db)
            pc_jobs.init_schema(db)
            native_plan_journal.init_schema(db)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        return db

    def stage(self, task_id, stage, expected_created=None):
        with self.connect() as db:
            changed = db.execute(
                "UPDATE tasks SET stage=?,updated=? WHERE task_id=? AND status!='cancelled' "
                "AND (? IS NULL OR created=?)",
                (stage, time.time(), task_id, expected_created, expected_created)).rowcount
            if not changed:
                raise TaskCancelled("Task cancelled or generation changed")

    def meta(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, str(value)))

    def load_risk_state(self):
        """Return persisted writer risk counters, or None when unset."""
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key='risk_counters'").fetchone()
        if not row or not row[0]:
            return None
        try:
            data = json.loads(row[0])
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def save_risk_state(self, state):
        """Persist fail-streak, write-rate, and heal counters across restarts."""
        if not isinstance(state, dict):
            raise ValueError("risk state must be an object")
        blob = json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES('risk_counters',?)", (blob,))

    def record_review(self, run_id, attempt, task, hotel, observation):
        with self.connect() as db:
            db.execute("INSERT INTO result_reviews VALUES(?,?,?,?,?,?,?)",
                       (run_id, attempt, task["task_id"], hotel, time.time(),
                        observation["state"], observation["reason"]))

    def record_active_identity(self, task, target, account):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES('active_business_identity',?)", (json.dumps({'task_id':task['task_id'],'entity_id':target.get('entity_id'),'account':account,'verified_at':time.time()},ensure_ascii=False),))

    def bind_discovered_hotel(self, task, hotel):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE tasks SET hotel=?,updated=? WHERE task_id=? AND status!='cancelled' "
                "AND (? IS NULL OR created=?)",
                (hotel, time.time(), task["task_id"], task.get("created"), task.get("created"))).rowcount
            if not changed:
                raise TaskCancelled("Task cancelled or generation changed")
            db.execute("INSERT OR REPLACE INTO task_identity VALUES(?,?,?,?)",
                       (task["task_id"], hotel, task["hotel"], time.time()))
        task["hotel"] = hotel

    def submission_gate(self, task, cfg, stage):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task["task_id"],)).fetchone()
            control = db.execute("SELECT cancelled_at FROM task_controls WHERE task_id=?",
                                 (task["task_id"],)).fetchone()
            if (not row or row["status"] != "running" or row["created"] != task["created"]
                    or control and control[0] >= row["created"]):
                raise TaskCancelled("Task cancelled or generation changed")
            if not 0 <= time.time() - row["created"] <= execution_age(cfg):
                raise TaskExpired("Task expired before native submit")
            db.execute("UPDATE tasks SET stage=?,updated=? WHERE task_id=?",
                       (stage, time.time(), task["task_id"]))

    def record_activity_params(self, job_id, params, confirmed_at=None):
        with self.connect() as db:
            db.execute("INSERT INTO activity_params(job_id,data,confirmed_at) VALUES(?,?,?) "
                       "ON CONFLICT(job_id) DO UPDATE SET data=excluded.data,confirmed_at=excluded.confirmed_at",
                       (job_id, json.dumps(params, ensure_ascii=False), confirmed_at))

    def activity_params(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM activity_params WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None
