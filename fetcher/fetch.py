"""
Orchestrates the two-phase pipeline with concurrent resolving and syncing.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import os
import json
import subprocess
import threading
import time
from pathlib import Path

from .checksum import Checksum
from .git import Git
from .lockfile import Lockfile, LockEntry
from .manifest import Manifest
from .package import SyncResult, STATUS_OK, STATUS_FAILED, STATUS_INTERNAL_ERROR
from .registry import Registry
from .resolver import Resolver, UnresolvableError
from .throttle import HostThrottle
from .utils import setup_logger

logger = setup_logger()

class CircuitBreakerTripped(Exception):
    """Raised when internal errors exceed the limit."""

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class Fetcher:
    def __init__(
        self,
        source_dir,
        lockfile: Lockfile,
        registry: Registry,
        max_workers: int = 8,
        internal_error_limit: int = 3,
    ):
        self.sources = Path(source_dir)
        self.lockfile = lockfile
        self.registry = registry
        self.throttle = HostThrottle(delay_seconds=3.0)
        self.max_workers = max_workers
        self.internal_error_limit = internal_error_limit

        self._internal_error_count = 0
        self._internal_error_lock = threading.Lock()
        self._breaker_tripped = threading.Event()

    # ---- phase 1: resolve (MULTI-THREADED + THROTTLED) -----------------------

    def resolve(self, manifest: Manifest, refresh: bool = False):
        resolver = Resolver()
        entries = manifest.entries()
        targets = [e for e in entries if refresh or e.name not in self.lockfile]

        logger.info(f"Resolving {len(targets)}/{len(entries)} packages concurrently "
                     f"({'refresh' if refresh else 'new only'}) with {self.max_workers} workers...\n")

        def _resolve_single(entry):
            try:
                # FIX: Apply anti-DDoS throttle to the resolver so strict hosts don't tarpit us
                with self.throttle.acquire(entry.repo):
                    return entry, resolver.resolve(entry), None
            except Exception as e:
                return entry, None, e

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(_resolve_single, entry) for entry in targets]
            for future in concurrent.futures.as_completed(futures):
                entry, resolved, err = future.result()
                
                if err:
                    logger.error(f"[{entry.name}] RESOLVE FAILED - {err}")
                    continue

                existing = self.lockfile.get(entry.name)
                checksum = None
                if existing and existing.resolved_commit == resolved.commit:
                    checksum = existing.checksum

                self.lockfile.set(LockEntry(
                    name=entry.name,
                    repo=entry.repo,
                    ref=resolved.ref,
                    ref_type=resolved.ref_type,
                    resolved_commit=resolved.commit,
                    checksum=checksum,
                    resolved_at=_now(),
                    source_url=resolved.source_url,
                ))

                logger.info(f"[{entry.name}] resolved -> {resolved.ref_type}:{resolved.ref} ({resolved.commit[:12]})")

        self.lockfile.save()
        logger.info("\nResolve complete.")

    # ---- phase 2: sync + verify ----------------------------------------

    def sync(self, manifest: Manifest):
        self.sources.mkdir(parents=True, exist_ok=True)

        categories = {}
        try:
            with open("manifests/pkg-branch.json", "r") as f:
                raw_manifest = json.load(f)
                for pkg_name, pkg_data in raw_manifest.get("packages", {}).items():
                    categories[pkg_name] = pkg_data.get("category")
        except Exception as e:
            logger.warning(f"Could not parse categories from JSON: {e}")

        all_names = [e.name for e in manifest.entries()]
        locked = [n for n in all_names if n in self.lockfile]
        unlocked = [n for n in all_names if n not in self.lockfile]

        if unlocked:
            logger.warning(f"{len(unlocked)} package(s) have no lock entry. Skipping.")

        if not locked:
            logger.info("Nothing to sync.")
            return

        logger.info(f"Starting concurrent sync of {len(locked)} packages with {self.max_workers} workers...\n")

        smoke_name, remaining = locked[0], locked[1:]
        self._sync_one(smoke_name, categories.get(smoke_name))
        
        if self.registry.get_state(smoke_name).get("status") == STATUS_INTERNAL_ERROR:
            raise CircuitBreakerTripped("Smoke test package hit an internal error.")

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        futures = [executor.submit(self._sync_one, name, categories.get(name)) for name in remaining]

        try:
            while not all(f.done() for f in futures):
                if self._breaker_tripped.is_set():
                    logger.error("Circuit breaker tripped. Cancelling...")
                    for f in futures: f.cancel()
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("\nCtrl+C detected. Cancelling pending packages...")
            for f in futures: f.cancel()
            os._exit(1)
        else:
            executor.shutdown(wait=True)

        logger.info(f"\nSync complete: {self.registry.summary()}")

    def _sync_one(self, name: str, category: str = None) -> SyncResult:
        lock_entry = self.lockfile.get(name)
        result = SyncResult(name=name)
        prev = self.registry.get_state(name)
        result.attempts = prev.get("attempts", 0) + 1
        result.last_try = _now()
        log_prefix = f"[{name}]"

        repo_dir = self.sources / category / name if category else self.sources / name
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            source_url = lock_entry.source_url or lock_entry.repo
            
            # --- THE CHEAP LOCAL CHECK ---
            needs_fetch = True
            if repo_dir.exists() and lock_entry.checksum:
                try:
                    # If the folder exists, check if its contents perfectly match our lockfile
                    current_checksum = Checksum.hash_tree(repo_dir)
                    if current_checksum == lock_entry.checksum:
                        needs_fetch = False
                except Exception:
                    pass  # If hashing fails for any reason, default to fetching
            
            # --- THE EXPENSIVE FETCH (Only runs if needed) ---
            if needs_fetch:
                with self.throttle.acquire(source_url):
                    Git.fetch_pinned(source_url, lock_entry.ref, lock_entry.ref_type, repo_dir)

                checksum = Checksum.hash_tree(repo_dir)

                if lock_entry.checksum and checksum != lock_entry.checksum:
                    result.status = STATUS_FAILED
                    result.reason = f"checksum mismatch: expected {lock_entry.checksum}, got {checksum}"
                    logger.error(f"{log_prefix} {result.reason}")
                    self.registry.update(result)
                    self.registry.save()
                    return result
                else:
                    if not lock_entry.checksum:
                        lock_entry.checksum = checksum
                        self.lockfile.set(lock_entry)
                        self.lockfile.save()

            # --- SUCCESS ---
            result.status = STATUS_OK
            result.reason = None
            result.last_sync = result.last_try
            
            action = "FETCHED" if needs_fetch else "CACHED"
            logger.info(f"{log_prefix} OK ({action}) - {lock_entry.ref_type}:{lock_entry.ref}")

        except subprocess.CalledProcessError as e:
            result.status = STATUS_FAILED
            result.reason = Git._last_error_line(e)
            logger.info(f"{log_prefix} FAILED - {result.reason}")

        except Exception as e:
            result.status = STATUS_FAILED
            result.reason = repr(e)[:200]
            logger.info(f"{log_prefix} FAILED - {result.reason}")

        self.registry.update(result)
        self.registry.save()
        return result
