"""
Resolves a ManifestEntry's *policy* ("latest-tag" or "branch") into a
concrete, pinned ref -- the step every other distro's tooling has and this
project's predecessor didn't.

This only does `git ls-remote` calls (no clone), so it's cheap enough to
run against all ~500 packages before touching disk at all. The result is
a ResolvedRef that Fetcher then hands to Git.fetch_pinned unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .git import Git, GitRemoteError
from .manifest import ManifestEntry

try:
    from packaging.version import Version as PkgVersion, InvalidVersion
except ImportError:  # pragma: no cover - packaging is a listed dependency
    PkgVersion = None
    InvalidVersion = Exception


class UnresolvableError(Exception):
    """Raised when a package's ref could not be resolved against any source URL."""


@dataclass
class ResolvedRef:
    source_url: str
    ref: str
    ref_type: str   # "tag" | "commit"
    commit: str


class Resolver:

    def resolve(self, entry: ManifestEntry) -> ResolvedRef:
        errors = []
        for url in entry.source_urls:
            try:
                resolved = self._resolve_against(url, entry)
                if resolved is not None:
                    return resolved
            except GitRemoteError as e:
                errors.append(f"{url}: {e}")

        detail = "; ".join(errors) if errors else "no source URLs configured"
        raise UnresolvableError(f"{entry.name}: could not resolve a ref ({detail})")

    def _resolve_against(self, url: str, entry: ManifestEntry) -> ResolvedRef | None:
        if entry.ref_policy == "latest-tag":
            tags = Git.ls_remote_tags(url)
            candidate = self._pick_latest_tag(tags, entry.tag_pattern)
            if candidate is not None:
                tag, sha = candidate
                return ResolvedRef(source_url=url, ref=tag, ref_type="tag", commit=sha)
            # No usable tags on this URL -- fall through to branch pinning
            # below rather than immediately trying the next mirror, so a
            # repo that legitimately has no releases still resolves.

        sha = Git.ls_remote_branch(url, entry.branch)
        if sha:
            return ResolvedRef(source_url=url, ref=entry.branch, ref_type="commit", commit=sha)

        return None

    def _pick_latest_tag(self, tags: dict[str, str], pattern: str | None):
        if pattern:
            regex = re.compile(pattern)
            tags = {name: sha for name, sha in tags.items() if regex.match(name)}

        if not tags:
            return None

        if PkgVersion is not None:
            parsed = []
            for name, sha in tags.items():
                try:
                    v = PkgVersion(name.lstrip("v"))
                    # Natively filter out standard pre-releases and dev builds
                    if not v.is_prerelease and not v.is_devrelease:
                        parsed.append((v, name, sha))
                except InvalidVersion:
                    continue
            if parsed:
                parsed.sort(key=lambda t: t[0])
                _, name, sha = parsed[-1]
                return name, sha

        # Fallback if nothing parsed as a PEP 440-ish version (e.g., odd
        # tagging schemes). Filter out common unstable keywords manually, 
        # then sort lexicographically.
        unstable_keywords = ["rc", "alpha", "beta", "pre", "test", "dev", "wip", "snapshot"]
        stable_tags = [name for name in tags if not any(kw in name.lower() for kw in unstable_keywords)]
        
        if stable_tags:
            name = sorted(stable_tags)[-1]
            return name, tags[name]
            
        # Absolute fallback: if ONLY unstable tags exist on the repo, 
        # pick the highest lexicographical one to avoid crashing.
        name = sorted(tags)[-1]
        return name, tags[name]
