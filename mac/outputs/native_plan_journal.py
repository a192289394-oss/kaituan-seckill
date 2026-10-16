"""Durable plan packet, using the existing phone cancellation/final gates."""
import json
import math
import time
import pc_jobs
from native_commit import NativeDispatchDenied


def init_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS native_plan_journal(task_id TEXT PRIMARY KEY,generation REAL NOT NULL,data TEXT NOT NULL,dispatched_at REAL)')


def load(database,task):
    with pc_jobs.connection(database) as db:
        row=db.execute('SELECT * FROM native_plan_journal WHERE task_id=? AND generation=?',(task['task_id'],task['created'])).fetchone()
        return dict(row) if row else None


def prepare(database,task,expected):
    with pc_jobs.connection(database) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM tasks WHERE task_id=?',(task['task_id'],)).fetchone()
        old=db.execute('SELECT * FROM native_plan_journal WHERE task_id=?',(task['task_id'],)).fetchone()
        if (not row or row['status']!='running' or row['created']!=task['created']
                or row['stage'] in ('confirming','submitting','verifying')
                or old and old['dispatched_at'] is not None):
            raise NativeDispatchDenied('开团任务已变化或已提交，只允许复核')
        binding=db.execute('SELECT data FROM task_targets WHERE task_id=? AND generation=?',(task['task_id'],task['created'])).fetchone()
        target=json.loads(binding[0]) if binding else {}
        root=str(target.get('root_id') or target.get('merchant_id') or '')
        if expected.get('root')!=root or expected.get('body',{}).get('task_id')!=task['task_id']:
            raise NativeDispatchDenied('开团预览与已核验商家或计划不符')
        db.execute('INSERT OR REPLACE INTO native_plan_journal VALUES(?,?,?,NULL)',
            (task['task_id'],task['created'],json.dumps(expected,ensure_ascii=False)))


class PlanPermit:
    def __init__(self,database,task,expected,max_age):
        if isinstance(max_age,bool) or not isinstance(max_age,(int,float)) or not math.isfinite(max_age) or max_age<=0:
            raise ValueError('Valid submission lifetime required')
        self.database=database;self.task=dict(task);self.expected=json.loads(json.dumps(expected));self.max_age=max_age;self.consumed=False
    def consume(self,root,body):
        if self.consumed or root!=self.expected.get('root') or body!=self.expected.get('body'):
            raise NativeDispatchDenied('开团提交凭据已消费或参数变化')
        with pc_jobs.connection(self.database) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM tasks WHERE task_id=?',(self.task['task_id'],)).fetchone()
            journal=db.execute('SELECT * FROM native_plan_journal WHERE task_id=?',(self.task['task_id'],)).fetchone()
            control=db.execute('SELECT cancelled_at FROM task_controls WHERE task_id=?',(self.task['task_id'],)).fetchone()
            bound=db.execute('SELECT data FROM task_targets WHERE task_id=? AND generation=?',(self.task['task_id'],self.task['created'])).fetchone()
            target=json.loads(bound[0]) if bound else {}
            if (not row or not journal or row['status']!='running' or row['stage']!='confirming'
                    or row['created']!=self.task['created'] or journal['generation']!=self.task['created']
                    or journal['dispatched_at'] is not None or json.loads(journal['data'])!=self.expected
                    or control and control[0]>=self.task['created']
                    or str(target.get('root_id') or target.get('merchant_id') or '')!=root):
                raise NativeDispatchDenied('开团最终闸门已变化、取消或重复发送')
            now=time.time();deadline=self.expected['snapshot']['confirm_deadline']
            if (isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or not math.isfinite(deadline)
                    or not 0<=now-row['created']<=self.max_age or now>=deadline):
                raise NativeDispatchDenied('开团指令或计划确认时限已结束')
            db.execute('UPDATE native_plan_journal SET dispatched_at=? WHERE task_id=?',(now,self.task['task_id']))
            db.execute("UPDATE tasks SET stage='verifying',updated=? WHERE task_id=?",(now,self.task['task_id']))
        self.consumed=True
