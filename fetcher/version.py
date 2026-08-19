"""
Best-effort human-readable version string for a fetched source tree.

For tag-pinned packages the resolved tag *is* the version, so this is
mostly exercised for branch/commit-pinned packages (rolling projects with
no tagged releases) where we still want something nicer than a raw sha
to show in the registry.
"""

from __future__ import annotations

import re
from pathlib import Path

from .git import Git


class Version:

    @classmethod
    def detect(cls, repo_path) -> str:
        repo_path = Path(repo_path)

        tag = Git(repo_path).latest_tag()
        if tag:
            return tag.lstrip("v")

        for filename in ("VERSION", "version.txt", "VERSION.txt"):
            ver_file = repo_path / filename
            if ver_file.exists():
                return ver_file.read_text(encoding="utf-8").strip()

        meson_file = repo_path / "meson.build"
        if meson_file.exists():
            content = meson_file.read_text(encoding="utf-8")
            match = re.search(r"version\s*:\s*['\"]([^'\"]+)['\"]", content)
            if match:
                return match.group(1)

        cmake_file = repo_path / "CMakeLists.txt"
        if cmake_file.exists():
            content = cmake_file.read_text(encoding="utf-8")
            match = re.search(r"project\s*\([^)]+VERSION\s+([0-9.]+)", content, re.IGNORECASE)
            if match:
                return match.group(1)

        return "unknown"
