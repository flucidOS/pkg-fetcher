"""
Orchestrates the two-phase pipeline:

    resolve(manifest)  -- cheap, network-light. Turns each manifest entry's
                            ref policy into a pinned tag/commit and writes
                            it to lock.json. Skips already-locked entries
                            unless refresh=True.

    sync(manifest)     -- fetches every locked package concurrently,
                            verifies its content checksum, and records the
                            outcome in registry.json.

Two safety mechanisms that the old fetcher didn't have, both aimed
directly at how it lost 464/507 packages to a single `AttributeError`
without anyone noticing until the run was long over:

  1. A smoke test: the first package is synced alone, outside the thread
     pool, before the rest are scheduled. A bug that would break every
     package breaks on package #1, not #507.

  2. A circuit breaker: `AttributeError`/`TypeError`/`NameError`/`KeyError`
     are treated as bugs in the fetcher itself, not per-package fetch
     failures. They get a distinct `internal_error` status, and if enough
     of them happen in one run the remaining work is cancelled rather than
     silently marking hundreds of healthy packages as "failed".
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
    """
    Raised when too many packages in one run hit an internal_error status.
    This means the fetcher itself is broken, not that a batch of upstream
    hosts happened to be down -- re-running won't help until it's fixed.
    """


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

    # ---- phase 1: resolve --------------------------------------------

    def resolve(self, manifest: Manifest, refresh: bool = False):
        resolver = Resolver()
        entries = manifest.entries()
        targets = [e for e in entries if refresh or e.name not in self.lockfile]

        logger.info(f"Resolving {len(targets)}/{len(entries)} packages "
                     f"({'refresh' if refresh else 'new only'})...\n")

        for entry in targets:
            try:
                resolved = resolver.resolve(entry)
            except UnresolvableError as e:
                logger.error(f"[{entry.name}] RESOLVE FAILED - {e}")
                continue

            existing = self.lockfile.get(entry.name)
            # Preserve a previously-verified checksum only if we're still
            # pinned to the exact same commit; otherwise it's stale.
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
            logger.info(
                f"[{entry.name}] resolved -> {resolved.ref_type}:{resolved.ref} "
                f"({resolved.commit[:12]})"
            )

        self.lockfile.save()
        logger.info("\nResolve complete.")

    # ---- phase 2: sync + verify ----------------------------------------

    def sync(self, manifest: Manifest):
        self.sources.mkdir(parents=True, exist_ok=True)

        # 1. Safely extract categories directly from the raw JSON
        # This bypasses the need to update your Manifest parsing class
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
            preview = ", ".join(unlocked[:5]) + ("..." if len(unlocked) > 5 else "")
            logger.warning(
                f"{len(unlocked)} package(s) have no lock entry -- run resolve() "
                f"first. Skipping: {preview}"
            )

        if not locked:
            logger.info("Nothing to sync.")
            return

        logger.info(f"Starting concurrent sync of {len(locked)} packages "
                     f"with {self.max_workers} workers...\n")

        # Smoke test: run the first package alone, outside the pool, so a
        # systemic bug fails loudly on package #1 instead of quietly
        # consuming the whole run.
        smoke_name, remaining = locked[0], locked[1:]
        
        # 2. Pass the category into the smoke test
        self._sync_one(smoke_name, categories.get(smoke_name))
        
        if self.registry.get_state(smoke_name).get("status") == STATUS_INTERNAL_ERROR:
            reason = self.registry.get_state(smoke_name).get("reason")
            raise CircuitBreakerTripped(
                f"Smoke test package '{smoke_name}' hit an internal error before "
                f"the full run started: {reason}. Fix the fetcher before retrying."
            )

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers)
        
        # 3. Pass the specific category down into all futures
        futures = [executor.submit(self._sync_one, name, categories.get(name)) for name in remaining]

        try:
            while not all(f.done() for f in futures):
                if self._breaker_tripped.is_set():
                    logger.error(
                        f"[!] Circuit breaker: {self._internal_error_count} internal "
                        f"errors (limit {self.internal_error_limit}). Cancelling "
                        f"remaining packages..."
                    )
                    for f in futures:
                        f.cancel()
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("\n[!] Ctrl+C detected. Cancelling pending packages...")
            for f in futures:
                f.cancel()
            logger.info("[!] Waiting for active fetches to finish... "
                         "(Ctrl+C again to force quit)")
            try:
                executor.shutdown(wait=True)
            except KeyboardInterrupt:
                logger.info("\n[!] Emergency kill triggered. Orphaned git "
                             "directories may be left behind.")
                os._exit(1)
        else:
            executor.shutdown(wait=True)

        if self._breaker_tripped.is_set():
            raise CircuitBreakerTripped(
                f"{self._internal_error_count} packages hit internal errors "
                f"(limit: {self.internal_error_limit}). This means a bug in the "
                f"fetcher itself, not a batch of unrelated network failures -- "
                f"check the log before re-running."
            )

        logger.info(f"\nSync complete: {self.registry.summary()}")

    # 4. Add 'category: str = None' to the function signature
    def _sync_one(self, name: str, category: str = None) -> SyncResult:
        lock_entry = self.lockfile.get(name)
        result = SyncResult(name=name)
        prev = self.registry.get_state(name)
        result.attempts = prev.get("attempts", 0) + 1
        result.last_try = _now()
        log_prefix = f"[{name}]"

        # 5. Build the dynamic directory path
        if category:
            repo_dir = self.sources / category / name
        else:
            # Fallback to flat directory if no category exists
            repo_dir = self.sources / name

        # 6. Ensure the target subdirectories (e.g., networking/networking-libs) exist
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            source_url = lock_entry.source_url or lock_entry.repo

            with self.throttle.acquire(source_url):
                Git.fetch_pinned(
                    source_url,
                    lock_entry.ref,
                    lock_entry.ref_type,
                    repo_dir,
                )

            checksum = Checksum.hash_tree(repo_dir)

            if lock_entry.checksum and checksum != lock_entry.checksum:
                # Pinned ref, so the content should be byte-identical every
                # time. A mismatch means corruption in transit, a tag that
                # got force-moved upstream, or tampering -- not something
                # to silently retry past.
                result.status = STATUS_FAILED
                result.reason = (
                    f"checksum mismatch: expected {lock_entry.checksum}, got "
                    f"{checksum} at pinned {lock_entry.ref_type}:{lock_entry.ref}"
                )
                logger.error(f"{log_prefix} {result.reason}")
            else:
                if not lock_entry.checksum:
                    lock_entry.checksum = checksum
                    self.lockfile.set(lock_entry)
                    self.lockfile.save()
                result.status = STATUS_OK
                result.reason = None
                result.last_sync = result.last_try
                logger.info(
                    f"{log_prefix} OK - {lock_entry.ref_type}:{lock_entry.ref} "
                    f"({lock_entry.resolved_commit[:12]})"
                )

        except subprocess.CalledProcessError as e:
            result.status = STATUS_FAILED
            result.reason = Git._last_error_line(e)
            logger.info(f"{log_prefix} FAILED - {result.reason}")

        except (AttributeError, TypeError, NameError, KeyError) as e:
            # A bug in the fetcher, not a fetch failure. Surfaced distinctly
            # so it can never disguise itself as 464 ordinary failures again.
            result.status = STATUS_INTERNAL_ERROR
            result.reason = f"{type(e).__name__}: {e}"
            logger.error(f"{log_prefix} INTERNAL ERROR - {result.reason}", exc_info=True)
            with self._internal_error_lock:
                self._internal_error_count += 1
                if self._internal_error_count >= self.internal_error_limit:
                    self._breaker_tripped.set()

        except Exception as e:
            result.status = STATUS_FAILED
            result.reason = repr(e)[:200]
            logger.info(f"{log_prefix} FAILED - {result.reason}")

        self.registry.update(result)
        self.registry.save()
        return result
