"""
pkg-fetcher: source resolution, pinning, fetching and integrity verification
for FlucidOS's ~500-package LFS/BLFS-style build set.

Architecture (mirrors how Arch/makepkg, Gentoo/Manifest, and Nix's
fetchurl/fetchFromGitHub handle sources):

    manifest.json   -- human-maintained: WHAT to track (repo, ref policy)
    lock.json        -- machine-generated: WHAT WAS RESOLVED (exact pinned
                         ref + commit + content checksum). Reproducible,
                         meant to be committed to VCS.
    registry.json     -- machine-generated: operational run log (status,
                         attempts, timestamps for the last sync). NOT a
                         source of truth for what to build -- lock.json is.

Two-phase pipeline:

    resolve  (Resolver)   manifest entry  -> pinned ref (tag or commit)
    fetch    (Fetcher)    pinned ref      -> working tree + verified checksum
"""

from .manifest import Manifest, ManifestEntry
from .lockfile import Lockfile, LockEntry
from .resolver import Resolver, ResolvedRef, UnresolvableError
from .checksum import Checksum
from .registry import Registry
from .throttle import HostThrottle
from .git import Git, GitRemoteError
from .version import Version
from .fetch import Fetcher, CircuitBreakerTripped

__all__ = [
    "Manifest", "ManifestEntry",
    "Lockfile", "LockEntry",
    "Resolver", "ResolvedRef", "UnresolvableError",
    "Checksum",
    "Registry",
    "HostThrottle",
    "Git", "GitRemoteError",
    "Version",
    "Fetcher", "CircuitBreakerTripped",
]
