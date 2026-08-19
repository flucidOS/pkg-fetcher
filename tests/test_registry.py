import json

from fetcher.registry import Registry
from fetcher.package import SyncResult, STATUS_OK, STATUS_FAILED


def test_registry_initially_empty(tmp_path):
    registry = Registry(tmp_path / "registry.json")
    assert registry.results == {}


def test_registry_update(tmp_path):
    registry = Registry(tmp_path / "registry.json")

    result = SyncResult(name="glibc", status=STATUS_OK, attempts=1, last_try="2026-08-05T09:00:00Z")
    registry.update(result)

    assert "glibc" in registry.results
    assert registry.results["glibc"]["status"] == STATUS_OK
    assert registry.results["glibc"]["attempts"] == 1


def test_registry_save_creates_file(tmp_path):
    path = tmp_path / "registry.json"
    registry = Registry(path)
    registry.update(SyncResult(name="bash", status=STATUS_OK))
    registry.save()

    assert path.exists()


def test_registry_save_contents(tmp_path):
    path = tmp_path / "registry.json"
    registry = Registry(path)
    registry.update(SyncResult(name="bash", status=STATUS_OK, attempts=1))
    registry.save()

    with path.open() as f:
        data = json.load(f)

    assert "packages" in data
    assert data["packages"]["bash"]["status"] == STATUS_OK


def test_registry_updates_existing_package(tmp_path):
    registry = Registry(tmp_path / "registry.json")

    registry.update(SyncResult(name="glibc", status=STATUS_FAILED, reason="429"))
    registry.update(SyncResult(name="glibc", status=STATUS_OK, reason=None))

    assert registry.results["glibc"]["status"] == STATUS_OK
    assert registry.results["glibc"]["reason"] is None


def test_registry_multiple_packages(tmp_path):
    registry = Registry(tmp_path / "registry.json")

    for name in ("glibc", "gcc", "bash"):
        registry.update(SyncResult(name=name, status=STATUS_OK))

    assert len(registry.results) == 3
    for name in ("glibc", "gcc", "bash"):
        assert name in registry.results


def test_registry_survives_corrupt_file(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text("{ not valid json")

    registry = Registry(path)

    assert registry.results == {}


def test_summary_counts_by_status(tmp_path):
    registry = Registry(tmp_path / "registry.json")
    registry.update(SyncResult(name="a", status=STATUS_OK))
    registry.update(SyncResult(name="b", status=STATUS_OK))
    registry.update(SyncResult(name="c", status=STATUS_FAILED))

    assert registry.summary() == {STATUS_OK: 2, STATUS_FAILED: 1}
