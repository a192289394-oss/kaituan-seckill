"""Consume an existing durable PC submission gate once, before native dispatch."""
import json
import math
import time
import pc_jobs


class NativeDispatchDenied(RuntimeError):pass


class ActivityPermit:
    def __init__(self,database,job,expected,max_age=1800):
        if isinstance(max_age,bool) or not isinstance(max_age,(int,float)) or not math.isfinite(max_age) or max_age<=0:
            raise ValueError('Valid submission lifetime required')
        self.database=database;self.job=dict(job)
        self.max_age=max_age
        # Frozen JSON snapshot: caller mutation cannot widen a committed packet.
        self.expected=json.loads(json.dumps(expected));self.consumed=False

    def consume(self,root,body):
        if self.consumed:raise NativeDispatchDenied('原生提交凭据已消费，只允许复核')
        preview=self.expected.get('preview') or {}
        if root!=self.expected.get('root') or body!=preview.get('body'):
            raise NativeDispatchDenied('原生提交商家或参数与已持久化预览不符')
        with pc_jobs.connection(self.database) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM activity_jobs WHERE id=?',(self.job['id'],)).fetchone()
            journal=db.execute('SELECT * FROM activity_journal WHERE job_id=?',(self.job['id'],)).fetchone()
            if (not row or not journal or row['status']!='running' or row['stage']!='submitting'
                    or row['created']!=self.job['created'] or journal['generation']!=self.job['created']
                    or journal['commit_at'] is None or json.loads(journal['data'])!=self.expected
                    or sorted(json.loads(row['accounts']))!=sorted(self.expected['accounts'])):
                raise NativeDispatchDenied('原生提交闸门已变化或尚未通过')
            target=json.loads(row['target']);expected_root=str(target.get('root_id') or target.get('root_life_account_id') or target.get('merchant_id'))
            if expected_root!=root:raise NativeDispatchDenied('原生提交商家与任务不符')
            now=time.time()
            if not 0<=now-row['created']<=self.max_age:
                raise NativeDispatchDenied('原生提交指令已超时，尚未发送')
            end=(body.get('activity')or{}).get('end_time')
            if isinstance(end,bool) or not isinstance(end,(int,float)) or now>=end:
                raise NativeDispatchDenied('原生提交活动时段已结束，尚未发送')
            changed=db.execute("UPDATE activity_jobs SET stage='publishing',updated=? WHERE id=? AND status='running' AND stage='submitting' AND created=?",
                (now,self.job['id'],self.job['created'])).rowcount
            if changed!=1:raise NativeDispatchDenied('原生提交已被另一个执行端接管')
        self.consumed=True
