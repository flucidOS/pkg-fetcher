"""
registry.json: operational status of the *last sync run* only -- status,
reason, attempt count, timestamps. It answers "did the last sync work?",
not "what should we build?" (that's lock.json's job).

Kept deliberately dumb and separate from lock.json so a failed sync run
can never corrupt or shadow a previously-good pin.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path

from .package import SyncResult


class Registry:

    def __init__(self, path):
        self.path = Path(path)
        self.results: dict[str, dict] = {}
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with self.path.open("r") as f:
                    data = json.load(f)
                    self.results = data.get("packages", {})
            except json.JSONDecodeError:
                self.results = {}

    def get_state(self, package_name: str) -> dict:
        return self.results.get(package_name, {})

    def update(self, result: SyncResult):
        with self.lock:
            self.results[result.name] = {
                k: v for k, v in asdict(result).items() if k != "name"
            }

    def save(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_suffix(".tmp")
            with temp_path.open("w") as f:
                json.dump({"packages": self.results}, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(temp_path, self.path)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for entry in self.results.values():
            counts[entry.get("status", "unknown")] = counts.get(entry.get("status", "unknown"), 0) + 1
        return counts
