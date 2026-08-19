"""
lock.json is the machine-generated, reproducible source of truth for
*exactly* what was fetched: a pinned ref, the exact commit it resolved to,
and a content checksum of the tree that was fetched at that commit.

This is deliberately separate from registry.json (operational run status)
so that "what to build" (this file) doesn't get mixed up with "how did the
last sync run go" (registry.json). It's the same separation Cargo makes
between Cargo.toml/Cargo.lock and a CI log, or Nix makes between a flake
input and a build log.

Re-resolving (`Resolver`) only touches entries you explicitly ask to
refresh; fetching (`Fetcher`) verifies the checksum on every run once one
exists, and treats a mismatch as fatal rather than just another retryable
failure.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class LockEntry:
    name: str
    repo: str
    ref: str              # tag name ("v2.42") or commit sha
    ref_type: str          # "tag" | "commit"
    resolved_commit: str   # full commit sha, always -- even when ref is a tag
    checksum: Optional[str] = None      # None until first successful fetch
    resolved_at: Optional[str] = None
    source_url: Optional[str] = None    # which of repo/mirrors actually resolved


class Lockfile:

    def __init__(self, path):
        self.path = Path(path)
        self._entries: dict[str, LockEntry] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        with self.path.open() as f:
            data = json.load(f)
        for name, meta in data.get("packages", {}).items():
            self._entries[name] = LockEntry(name=name, **meta)

    def get(self, name: str) -> Optional[LockEntry]:
        with self._lock:
            return self._entries.get(name)

    def set(self, entry: LockEntry):
        with self._lock:
            self._entries[entry.name] = entry

    def save(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            packages = {
                name: {k: v for k, v in asdict(entry).items() if k != "name"}
                for name, entry in sorted(self._entries.items())
            }
            temp_path = self.path.with_suffix(".tmp")
            with temp_path.open("w") as f:
                json.dump({"packages": packages}, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(temp_path, self.path)

    def __len__(self):
        return len(self._entries)

    def __contains__(self, name):
        return name in self._entries
