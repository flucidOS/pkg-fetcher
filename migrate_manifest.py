#!/usr/bin/env python3
"""
Migrates the old manifest schema (just {repo, branch} per package, no
pinning policy) into the new schema. Every package defaults to
ref_policy="latest-tag" with its old branch kept as the fallback for
repos that turn out to have no tags at resolve time.

Usage:
    python3 migrate_manifest.py old_manifest.json manifests/pkg-branch.json
"""

from __future__ import annotations

import datetime
import json
import sys


def migrate(old: dict) -> dict:
    packages = {}
    for name, meta in old["packages"].items():
        packages[name] = {
            "repo": meta["repo"],
            "branch": meta["branch"],
            "ref_policy": "latest-tag",
        }
    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "packages": packages,
    }


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <old_manifest.json> <new_manifest.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        old = json.load(f)

    new = migrate(old)

    with open(sys.argv[2], "w") as f:
        json.dump(new, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Migrated {len(new['packages'])} packages -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
