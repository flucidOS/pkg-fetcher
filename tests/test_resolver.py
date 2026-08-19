import pytest

from fetcher.manifest import ManifestEntry
from fetcher.resolver import Resolver, UnresolvableError


def test_prefers_latest_tag(local_repo_factory):
    url = local_repo_factory("pkg", tags=["v1.0.0", "v1.2.0", "v1.10.0"])
    entry = ManifestEntry(name="pkg", repo=url, ref_policy="latest-tag", branch="main")

    resolved = Resolver().resolve(entry)

    assert resolved.ref_type == "tag"
    # v1.10.0 > v1.2.0 numerically -- this is exactly the case naive string
    # sorting gets wrong ("v1.10.0" < "v1.2.0" lexicographically).
    assert resolved.ref == "v1.10.0"


def test_falls_back_to_branch_when_no_tags(local_repo_factory):
    url = local_repo_factory("pkg", tags=[], branch="main", extra_commits=2)
    entry = ManifestEntry(name="pkg", repo=url, ref_policy="latest-tag", branch="main")

    resolved = Resolver().resolve(entry)

    assert resolved.ref_type == "commit"
    assert resolved.ref == "main"
    assert len(resolved.commit) == 40


def test_branch_policy_ignores_tags(local_repo_factory):
    url = local_repo_factory("pkg", tags=["v9.9.9"], branch="main")
    entry = ManifestEntry(name="pkg", repo=url, ref_policy="branch", branch="main")

    resolved = Resolver().resolve(entry)

    assert resolved.ref_type == "commit"
    assert resolved.ref == "main"


def test_tag_pattern_filters_prereleases(local_repo_factory):
    url = local_repo_factory("pkg", tags=["v1.0.0", "v2.0.0-rc1"])
    entry = ManifestEntry(
        name="pkg", repo=url, ref_policy="latest-tag", branch="main",
        tag_pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$",
    )

    resolved = Resolver().resolve(entry)

    assert resolved.ref == "v1.0.0"


def test_falls_back_to_mirror(local_repo_factory):
    dead_url = "file:///nonexistent/path/that/does/not/exist.git"
    working_url = local_repo_factory("pkg", tags=["v1.0.0"])
    entry = ManifestEntry(
        name="pkg", repo=dead_url, ref_policy="latest-tag", branch="main",
        mirrors=[working_url],
    )

    resolved = Resolver().resolve(entry)

    assert resolved.source_url == working_url
    assert resolved.ref == "v1.0.0"


def test_unresolvable_raises(local_repo_factory):
    entry = ManifestEntry(
        name="pkg", repo="file:///nonexistent.git", ref_policy="latest-tag", branch="main",
    )

    with pytest.raises(UnresolvableError):
        Resolver().resolve(entry)
