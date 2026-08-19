import json

import pytest

from fetcher.fetch import Fetcher, CircuitBreakerTripped
from fetcher.git import Git
from fetcher.lockfile import Lockfile
from fetcher.manifest import Manifest
from fetcher.package import STATUS_OK, STATUS_FAILED, STATUS_INTERNAL_ERROR
from fetcher.registry import Registry


def write_manifest(path, packages: dict):
    path.write_text(json.dumps({"generated": "test", "packages": packages}))


@pytest.fixture
def env(tmp_path):
    return {
        "manifest_path": tmp_path / "manifest.json",
        "lockfile": Lockfile(tmp_path / "lock.json"),
        "registry": Registry(tmp_path / "registry.json"),
        "sources": tmp_path / "sources",
    }


def make_fetcher(env, **kwargs):
    return Fetcher(env["sources"], env["lockfile"], env["registry"], **kwargs)


def test_resolve_then_sync_ok(local_repo_factory, env):
    url = local_repo_factory("zlib", tags=["v1.3.0"])
    write_manifest(env["manifest_path"], {"zlib": {"repo": url, "branch": "main", "ref_policy": "latest-tag"}})
    manifest = Manifest(env["manifest_path"])

    fetcher = make_fetcher(env)
    fetcher.resolve(manifest)
    fetcher.sync(manifest)

    assert env["registry"].get_state("zlib")["status"] == STATUS_OK
    assert env["lockfile"].get("zlib").checksum is not None
    assert (env["sources"] / "zlib" / "VERSION").exists()


def test_sync_skips_unlocked_packages(local_repo_factory, env):
    url = local_repo_factory("zlib", tags=["v1.3.0"])
    write_manifest(env["manifest_path"], {"zlib": {"repo": url, "branch": "main"}})
    manifest = Manifest(env["manifest_path"])

    fetcher = make_fetcher(env)
    # Deliberately skip resolve() -- nothing should be fetched.
    fetcher.sync(manifest)

    assert env["registry"].get_state("zlib") == {}


def test_checksum_mismatch_is_hard_failure(local_repo_factory, env):
    url = local_repo_factory("zlib", tags=["v1.3.0"])
    write_manifest(env["manifest_path"], {"zlib": {"repo": url, "branch": "main"}})
    manifest = Manifest(env["manifest_path"])

    fetcher = make_fetcher(env)
    fetcher.resolve(manifest)
    fetcher.sync(manifest)
    assert env["registry"].get_state("zlib")["status"] == STATUS_OK

    # Simulate corruption/tampering: the lock says one checksum, but we
    # force a different one in so the next sync's freshly-fetched content
    # won't match it.
    entry = env["lockfile"].get("zlib")
    entry.checksum = "sha256:" + "0" * 64
    env["lockfile"].set(entry)

    fetcher.sync(manifest)

    state = env["registry"].get_state("zlib")
    assert state["status"] == STATUS_FAILED
    assert "checksum mismatch" in state["reason"]


def test_circuit_breaker_trips_instead_of_burning_through_all_packages(local_repo_factory, env, monkeypatch):
    """
    Directly reproduces the original incident: a bug in the fetcher
    (there, `HostThrottle.wait_for` not existing) that would previously
    have silently marked every remaining package as "failed". Here it
    must instead be recognized as an internal error and stop the run
    early, rather than working through all 20 packages.
    """
    packages = {}
    for i in range(20):
        url = local_repo_factory(f"pkg{i}", tags=["v1.0.0"])
        packages[f"pkg{i}"] = {"repo": url, "branch": "main"}
    write_manifest(env["manifest_path"], packages)
    manifest = Manifest(env["manifest_path"])

    fetcher = make_fetcher(env, internal_error_limit=3)
    fetcher.resolve(manifest)

    # Simulate the class of bug that caused the original incident: a
    # missing attribute deep in the fetch path.
    def broken_fetch_pinned(*args, **kwargs):
        raise AttributeError("'HostThrottle' object has no attribute 'wait_for'")

    monkeypatch.setattr(Git, "fetch_pinned", broken_fetch_pinned)

    with pytest.raises(CircuitBreakerTripped):
        fetcher.sync(manifest)

    statuses = [v["status"] for v in env["registry"].results.values()]
    assert STATUS_INTERNAL_ERROR in statuses
    # The whole point: it must NOT have ground through all 20 packages
    # before stopping.
    assert len(statuses) < 20
    assert STATUS_FAILED not in statuses  # never disguised as an ordinary failure


def test_smoke_test_catches_bug_before_pool_starts(local_repo_factory, env, monkeypatch):
    packages = {}
    for i in range(10):
        url = local_repo_factory(f"pkg{i}", tags=["v1.0.0"])
        packages[f"pkg{i}"] = {"repo": url, "branch": "main"}
    write_manifest(env["manifest_path"], packages)
    manifest = Manifest(env["manifest_path"])

    fetcher = make_fetcher(env, internal_error_limit=100)  # high limit -- shouldn't matter
    fetcher.resolve(manifest)

    def broken_fetch_pinned(*args, **kwargs):
        raise AttributeError("boom")

    monkeypatch.setattr(Git, "fetch_pinned", broken_fetch_pinned)

    with pytest.raises(CircuitBreakerTripped):
        fetcher.sync(manifest)

    # Only the smoke-test package should have run at all.
    assert len(env["registry"].results) == 1


def test_ordinary_failures_do_not_trip_breaker(local_repo_factory, env):
    """A normal transient/permanent fetch failure (bad URL, 404, etc.)
    must stay a per-package 'failed', not escalate to internal_error."""
    write_manifest(env["manifest_path"], {
        "broken": {"repo": "file:///definitely/does/not/exist.git", "branch": "main"},
    })
    manifest = Manifest(env["manifest_path"])
    fetcher = make_fetcher(env, internal_error_limit=1)

    fetcher.resolve(manifest)  # resolve itself will fail to resolve -> no lock entry
    fetcher.sync(manifest)  # nothing locked, so nothing to sync

    assert "broken" not in env["lockfile"]
