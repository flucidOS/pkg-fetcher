"""
SyncResult is deliberately small: it carries only the outcome of one sync
attempt for one package. It does NOT duplicate `repo`/`branch` (that's
ManifestEntry's job) or `commit`/`checksum` (that's LockEntry's job) --
the old Package class held all of these at once, which is how a stale
value in one place (e.g. an old commit) could quietly disagree with the
current value somewhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_INTERNAL_ERROR = "internal_error"  # bug in the fetcher itself, not
                                            # a transient network/source issue


@dataclass
class SyncResult:
    name: str
    status: str = "pending"
    reason: Optional[str] = None
    attempts: int = 0
    last_try: Optional[str] = None
    last_sync: Optional[str] = None
