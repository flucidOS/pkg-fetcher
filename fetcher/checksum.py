"""
Content-hashing for fetched source trees.

This is the piece the old fetcher shipped a file for (`checksum.py`) but
never actually called -- `Package.checksum` was hardcoded to `None`
everywhere. Every other distro's build system treats a hash mismatch as a
hard failure (makepkg's sha256sums, Gentoo's Manifest DIST entries, Nix's
fetchurl/fetchFromGitHub `sha256`). This module is what makes that possible
here.

We hash the *working tree contents*, not the git object database, so the
result only depends on what ended up on disk -- not on how it got there
(shallow vs full clone, packfile layout, etc).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ALGORITHM = "sha256"

# Directories we never want to include in the content hash: VCS metadata
# carries timestamps/refs that have nothing to do with the actual source
# contents, and would make the hash non-reproducible across clone strategies.
_IGNORED_DIR_NAMES = frozenset({".git", ".svn", ".hg"})


class Checksum:
    """Computes and formats deterministic content hashes for a source tree."""

    @classmethod
    def hash_tree(cls, root: str | Path) -> str:
        """
        Deterministically hash every regular file under `root`.

        Deterministic means: same file contents + same relative paths ->
        same hash, regardless of filesystem walk order, clone method, or
        which machine computed it. We achieve that by explicitly sorting
        the file list before hashing, and feeding the hasher
        (relative_path, file_hash) pairs in that sorted order.

        Returns a string of the form "sha256:<hex digest>".
        """
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"Not a directory: {root}")

        files = sorted(cls._iter_files(root))

        tree_hasher = hashlib.new(ALGORITHM)
        for rel_path in files:
            file_hash = cls._hash_file(root / rel_path)
            # NUL-delimited to avoid path-concatenation ambiguity
            # (e.g. "ab" + "c" vs "a" + "bc").
            tree_hasher.update(rel_path.encode("utf-8"))
            tree_hasher.update(b"\0")
            tree_hasher.update(file_hash)
            tree_hasher.update(b"\0")

        return f"{ALGORITHM}:{tree_hasher.hexdigest()}"

    @classmethod
    def verify(cls, root: str | Path, expected: str) -> bool:
        """Returns True if the tree's current hash matches `expected`."""
        return cls.hash_tree(root) == expected

    @staticmethod
    def _iter_files(root: Path):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _IGNORED_DIR_NAMES for part in path.relative_to(root).parts):
                continue
            yield path.relative_to(root).as_posix()

    @staticmethod
    def _hash_file(path: Path) -> bytes:
        h = hashlib.new(ALGORITHM)
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.digest()
