from fetcher.lockfile import Lockfile, LockEntry


def make_entry(**overrides):
    defaults = dict(
        name="pkg", repo="https://example.invalid/pkg.git",
        ref="v1.0.0", ref_type="tag", resolved_commit="a" * 40,
        checksum="sha256:" + "b" * 64, resolved_at="2026-01-01T00:00:00Z",
        source_url="https://example.invalid/pkg.git",
    )
    defaults.update(overrides)
    return LockEntry(**defaults)


def test_set_and_get(tmp_path):
    lock = Lockfile(tmp_path / "lock.json")
    entry = make_entry()

    lock.set(entry)

    assert lock.get("pkg") == entry
    assert "pkg" in lock
    assert len(lock) == 1


def test_missing_entry_returns_none(tmp_path):
    lock = Lockfile(tmp_path / "lock.json")
    assert lock.get("nonexistent") is None
    assert "nonexistent" not in lock


def test_save_and_reload_round_trip(tmp_path):
    path = tmp_path / "lock.json"
    lock = Lockfile(path)
    lock.set(make_entry())
    lock.save()

    reloaded = Lockfile(path)
    assert reloaded.get("pkg") == make_entry()


def test_save_is_atomic_no_partial_file(tmp_path):
    path = tmp_path / "lock.json"
    lock = Lockfile(path)
    lock.set(make_entry())
    lock.save()

    assert path.exists()
    assert not path.with_suffix(".tmp").exists()


def test_multiple_packages(tmp_path):
    lock = Lockfile(tmp_path / "lock.json")
    lock.set(make_entry(name="a"))
    lock.set(make_entry(name="b"))
    lock.save()

    reloaded = Lockfile(tmp_path / "lock.json")
    assert len(reloaded) == 2
    assert reloaded.get("a").name == "a"
    assert reloaded.get("b").name == "b"
