"""
Per-host rate limiting for concurrent git operations. Some upstream hosts
(sourceware.org, gcc.gnu.org) rate-limit aggressively; this makes sure we
never hit a given host faster than its configured cooldown, regardless of
how many worker threads are running concurrently.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse


class HostThrottle:

    def __init__(self, delay_seconds: float = 3.0):
        self.default_delay = delay_seconds
        # Strict cooldowns for infrastructure known to aggressively rate-limit.
        self.domain_delays = {
            "sourceware.org": 15.0,
            "gcc.gnu.org": 15.0,
            "git.kernel.org": 10.0,
            "git.savannah.gnu.org": 5.0,
        }
        self.last_access: dict[str, float] = {}
        self.domain_locks: dict[str, threading.Lock] = {}
        self.global_lock = threading.Lock()

    @contextmanager
    def acquire(self, url: str):
        domain = urlparse(url).netloc
        if not domain:
            yield
            return

        delay = self.domain_delays.get(domain, self.default_delay)

        with self.global_lock:
            domain_lock = self.domain_locks.setdefault(domain, threading.Lock())

        with domain_lock:
            sleep_time = 0.0
            with self.global_lock:
                now = time.time()
                if domain in self.last_access:
                    elapsed = now - self.last_access[domain]
                    if elapsed < delay:
                        sleep_time = delay - elapsed

            if sleep_time > 0:
                time.sleep(sleep_time)

            try:
                yield
            finally:
                with self.global_lock:
                    self.last_access[domain] = time.time()
