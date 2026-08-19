"""
manifest.json is the human-maintained input: which packages exist, where
their source lives, and the *policy* for pinning them. It never contains
a resolved commit or a checksum -- that's lock.json's job (see lockfile.py).

Schema:

    {
      "generated": "<iso8601, informational only>",
      "packages": {
        "<name>": {
          "repo": "<primary git url>",
          "mirrors": ["<fallback git url>", ...],       # optional
          "ref_policy": "latest-tag" | "branch",          # default: latest-tag
          "branch": "<branch name>",                      # used when
                                                            # ref_policy=="branch",
                                                            # or as fallback when
                                                            # ref_policy=="latest-tag"
                                                            # but the repo has no tags
          "tag_pattern": "<regex, optional>"              # restrict which tags
                                                            # count as releases,
                                                            # e.g. exclude "-rc"/"-beta"
        }
      }
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ManifestEntry:
    name: str
    repo: str
    ref_policy: str = "latest-tag"
    branch: str = "main"
    tag_pattern: Optional[str] = None
    mirrors: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.ref_policy not in ("latest-tag", "branch"):
            raise ValueError(
                f"{self.name}: ref_policy must be 'latest-tag' or 'branch', "
                f"got {self.ref_policy!r}"
            )

    @property
    def source_urls(self) -> list[str]:
        """Primary repo first, then mirrors, in fallback order."""
        return [self.repo, *self.mirrors]


class Manifest:

    def __init__(self, path):
        self.path = Path(path)

    def entries(self) -> list[ManifestEntry]:
        with self.path.open() as f:
            data = json.load(f)

        entries = []
        for name, meta in data["packages"].items():
            entries.append(
                ManifestEntry(
                    name=name,
                    repo=meta["repo"],
                    ref_policy=meta.get("ref_policy", "latest-tag"),
                    branch=meta.get("branch", "main"),
                    tag_pattern=meta.get("tag_pattern"),
                    mirrors=meta.get("mirrors", []),
                )
            )
        return entries
