"""Durable PC authorization jobs. Standard library only; shared with browser worker."""
import json
import sqlite3
import time
from contextlib import contextmanager

POST_COMMIT = ('submitting', 'publishing', 'verifying')


@contextmanager
def connection(path):
    db = sqlite3.connect(str(path), timeout=5)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def init_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS activity_journal(
          job_id TEXT PRIMARY KEY, generation REAL NOT NULL, data TEXT NOT NULL,
          commit_at REAL, reviewed_at REAL);
        CREATE TABLE IF NOT EXISTS activity_retry(
          job_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL, next_at REAL NOT NULL);
    ''')


def prepare(path, job, data):
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM activity_jobs WHERE id=?', (job['id'],)).fetchone()
        if not row or row['created'] != job['created'] or row['status'] != 'running' or row['stage'] in POST_COMMIT:
            raise RuntimeError('PC 作业已变更，不能准备提交。')
        old = db.execute('SELECT commit_at FROM activity_journal WHERE job_id=?', (job['id'],)).fetchone()
        if old and old['commit_at'] is not None:
            raise RuntimeError('PC 作业已进入提交，只允许复核。')
        db.execute('INSERT OR REPLACE INTO activity_journal VALUES(?,?,?,NULL,NULL)',
                   (job['id'], job['created'], json.dumps(data, ensure_ascii=False)))
        db.execute("UPDATE activity_jobs SET stage='prepared',updated=? WHERE id=?", (time.time(), job['id']))


def submission_gate(path, job, max_age, expected):
    """Commit BEFORE the sole publishing click. No retry, including across restart."""
    now = time.time()
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM activity_jobs WHERE id=?', (job['id'],)).fetchone()
        journal = db.execute('SELECT * FROM activity_journal WHERE job_id=?', (job['id'],)).fetchone()
        if (not row or row['status'] != 'running' or row['created'] != job['created']
                or row['stage'] != 'prepared' or not journal or journal['commit_at'] is not None
                or journal['generation'] != job['created']):
            raise RuntimeError('提交闸门拒绝：任务状态已变化或已经提交。')
        if not 0 <= now - row['created'] <= max_age:
            raise RuntimeError('秒杀指令已过有效期，未提交。')
        data = json.loads(journal['data'])
        if data != expected:
            raise RuntimeError('提交预览已变化，未提交。')
        if data['root'] != str(json.loads(row['target']).get('root_id') or json.loads(row['target']).get('root_life_account_id') or json.loads(row['target']).get('merchant_id')):
            raise RuntimeError('提交商家与作业不一致。')
        if sorted(data['accounts']) != sorted(json.loads(row['accounts'])):
            raise RuntimeError('提交账号与作业不一致。')
        db.execute('UPDATE activity_journal SET commit_at=? WHERE job_id=?', (now, job['id']))
        db.execute("UPDATE activity_jobs SET stage='submitting',updated=? WHERE id=?", (now, job['id']))


def recover(db, now):
    """Call ONLY while owning the PC worker lock; phone recovery must not call this."""
    for row in db.execute("SELECT * FROM activity_jobs WHERE status='running'").fetchall():
        journal = db.execute('SELECT commit_at FROM activity_journal WHERE job_id=?', (row['id'],)).fetchone()
        review = row['stage'] in POST_COMMIT or (journal and journal['commit_at'] is not None)
        db.execute('UPDATE activity_jobs SET status=?,stage=?,updated=? WHERE id=?',
                   ('checking' if review else 'queued', 'verifying' if review else 'created', now, row['id']))


def load_journal(path, job):
    with connection(path) as db:
        row = db.execute('SELECT * FROM activity_journal WHERE job_id=?', (job['id'],)).fetchone()
    if row and row['generation'] == job['created']:
        return dict(row)
    return None
