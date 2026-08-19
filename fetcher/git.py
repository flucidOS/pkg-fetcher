"""
Thin wrapper around the `git` CLI.

Two categories of operation live here:

  * "remote" queries (`ls_remote_tags`, `ls_remote_branch`) -- cheap,
    network-only, no local clone. These back the resolver: figuring out
    *what* to pin without paying for a full clone.

  * "local" operations on an already-cloned working tree, plus the pinned
    fetch itself (`fetch_pinned`), which is the only thing allowed to
    actually populate `sources/<package>/` -- always against an exact tag
    or commit, never a floating branch tip.
"""

from __future__ import annotations

import subprocess
import shutil
import time
from pathlib import Path


class GitRemoteError(Exception):
    """Raised when a remote git operation (ls-remote, pinned fetch) fails."""


class Git:

    TRANSIENT_ERRORS = (
        "429",
        "500",
        "502",
        "503",
        "504",
        "connection reset",
        "connection timed out",
        "timed out",
        "remote end hung up unexpectedly",
        "unexpected disconnect",
        "internal server error",
        "early eof",
    )

    def __init__(self, path):
        self.path = Path(path)

    # ---- remote queries (no local clone required) -------------------

    @classmethod
    def ls_remote_tags(cls, url: str) -> dict[str, str]:
        """
        Returns {tag_name: commit_sha} for every annotated/lightweight tag
        on `url`, without cloning anything. Dereferences annotated tags
        (`^{}`) so the sha always points at the tagged commit, not the
        tag object.
        """
        try:
            output = cls._run_capture(["git", "ls-remote", "--tags", "--refs", url])
        except subprocess.CalledProcessError as e:
            raise GitRemoteError(cls._last_error_line(e)) from e

        tags: dict[str, str] = {}
        for line in output.splitlines():
            if not line.strip():
                continue
            sha, ref = line.split("\t", 1)
            name = ref.removeprefix("refs/tags/")
            tags[name] = sha
        return tags

    @classmethod
    def ls_remote_branch(cls, url: str, branch: str) -> str | None:
        """Returns the commit sha at the tip of `branch` on `url`, or None."""
        try:
            output = cls._run_capture(["git", "ls-remote", url, f"refs/heads/{branch}"])
        except subprocess.CalledProcessError as e:
            raise GitRemoteError(cls._last_error_line(e)) from e

        line = output.strip()
        if not line:
            return None
        sha, _ref = line.split("\t", 1)
        return sha

    # ---- pinned fetch: the only thing allowed to populate sources/ --

    @classmethod
    def fetch_pinned(cls, url: str, ref: str, ref_type: str, path, retries=5):
        """
        Clone/fetch `url` at exactly `ref` (a tag name if ref_type=="tag",
        a full commit sha if ref_type=="commit") into `path`.

        Never resolves a branch tip itself -- the caller (Resolver) already
        turned "branch" into a concrete sha before we get here. This is
        the boundary that makes fetches reproducible: given the same
        (url, ref, ref_type), this always ends up with the same tree.
        """
        path = Path(path)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

        if ref_type == "tag":
            cmd = [
                "git", "clone",
                "--depth", "1",
                "--branch", ref,
                url, str(path),
            ]
            cls._run(cmd, retries=retries)
            return cls(path)

        if ref_type == "commit":
            return cls._fetch_pinned_commit(url, ref, path, retries)

        raise ValueError(f"Unknown ref_type: {ref_type!r}")

    @classmethod
    def _fetch_pinned_commit(cls, url: str, commit: str, path: Path, retries: int):
        path.mkdir(parents=True, exist_ok=True)
        cls._run(["git", "init", "--quiet", str(path)], retries=1)
        cls._run(["git", "-C", str(path), "remote", "add", "origin", url], retries=1)

        # Fast path: most modern git hosts (GitHub, GitLab, sourcehut) allow
        # fetching an arbitrary commit sha directly when shallow-fetch of
        # reachable SHA1s is enabled server-side.
        try:
            cls._run(
                ["git", "-C", str(path), "fetch", "--depth", "1", "origin", commit],
                retries=2,
            )
            cls._run(["git", "-C", str(path), "checkout", "--quiet", "FETCH_HEAD"], retries=1)
            return cls(path)
        except subprocess.CalledProcessError:
            pass

        # Fallback: server doesn't support fetching bare SHAs shallowly.
        # Full fetch, then check out the exact commit locally.
        cls._run(["git", "-C", str(path), "fetch", "origin"], retries=retries)
        cls._run(["git", "-C", str(path), "checkout", "--quiet", commit], retries=1)
        return cls(path)

    # ---- local working-tree helpers ----------------------------------

    @staticmethod
    def exists(path):
        return Path(path).exists()

    def head(self):
        return subprocess.check_output(
            ["git", "-C", str(self.path), "rev-parse", "HEAD"],
            text=True,
        ).strip()

    def current_branch(self):
        return subprocess.check_output(
            ["git", "-C", str(self.path), "branch", "--show-current"],
            text=True,
        ).strip()

    def latest_tag(self):
        try:
            return subprocess.check_output(
                ["git", "-C", str(self.path), "describe", "--tags", "--abbrev=0"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            return None

    def has_changes(self):
        result = subprocess.run(
            ["git", "-C", str(self.path), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())

    # ---- shared retry machinery ---------------------------------------

    @classmethod
    def _run(cls, command, retries=5):
        for attempt in range(1, retries + 1):
            result = subprocess.run(command, text=True, capture_output=True)

            if result.returncode == 0:
                return

            error = (result.stderr or result.stdout or "").lower()
            transient = any(token in error for token in cls.TRANSIENT_ERRORS)

            if not transient or attempt == retries:
                raise subprocess.CalledProcessError(
                    result.returncode, command,
                    output=result.stdout, stderr=result.stderr,
                )

            wait = 5 * (2 ** (attempt - 1))
            target = command[-2] if len(command) > 2 else "unknown"
            print(f"  [{target}] retry {attempt}/{retries}, waiting {wait}s")
            time.sleep(wait)

    @classmethod
    def _run_capture(cls, command, retries=3) -> str:
        """Like _run, but returns stdout instead of discarding it."""
        last_exc = None
        for attempt in range(1, retries + 1):
            result = subprocess.run(command, text=True, capture_output=True)
            if result.returncode == 0:
                return result.stdout

            error = (result.stderr or result.stdout or "").lower()
            transient = any(token in error for token in cls.TRANSIENT_ERRORS)
            last_exc = subprocess.CalledProcessError(
                result.returncode, command,
                output=result.stdout, stderr=result.stderr,
            )
            if not transient or attempt == retries:
                raise last_exc

            time.sleep(2 ** attempt)
        raise last_exc

    @staticmethod
    def _last_error_line(e: subprocess.CalledProcessError) -> str:
        out = (e.stderr or e.stdout or "").strip()
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        return lines[-1][:200] if lines else "unknown git error"
