"""Unattended policy: accepted work survives outages; commits are never replayed."""
import threading
import time


def execution_age(cfg):
    return cfg.get('execution_max_age_seconds', cfg['max_task_age_seconds'])


def retry_delay(attempt):
    return min(300, 15 * 2 ** min(max(0, attempt - 1), 5))


class LoopWatchdog:
    """Monotonic liveness, independent of wall-clock changes and SQLite locks."""
    def __init__(self, limits, clock=time.monotonic):
        self.clock = clock
        self.limits = dict(limits)
        self.lock = threading.Lock()
        self.seen = {name: clock() for name in limits}

    def beat(self, name):
        with self.lock:
            self.seen[name] = self.clock()

    def stalled(self):
        now = self.clock()
        with self.lock:
            return sorted(name for name, limit in self.limits.items()
                          if now - self.seen[name] > limit)
