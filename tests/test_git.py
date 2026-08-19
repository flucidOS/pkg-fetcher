import pytest

from fetcher.git import Git, GitRemoteError


def test_ls_remote_tags(local_repo_factory):
    url = local_repo_factory("pkg", tags=["v1.0.0", "v1.1.0"])
    tags = Git.ls_remote_tags(url)

    assert set(tags) == {"v1.0.0", "v1.1.0"}
    assert all(len(sha) == 40 for sha in tags.values())


def test_ls_remote_tags_empty_repo(local_repo_factory):
    url = local_repo_factory("pkg", tags=[])
    assert Git.ls_remote_tags(url) == {}


def test_ls_remote_branch(local_repo_factory):
    url = local_repo_factory("pkg", branch="develop", extra_commits=1)
    sha = Git.ls_remote_branch(url, "develop")

    assert sha is not None
    assert len(sha) == 40


def test_ls_remote_branch_missing_branch(local_repo_factory):
    url = local_repo_factory("pkg", branch="main")
    assert Git.ls_remote_branch(url, "nonexistent-branch") is None


def test_ls_remote_raises_on_unreachable_host():
    with pytest.raises(GitRemoteError):
        Git.ls_remote_tags("file:///definitely/does/not/exist.git")


def test_fetch_pinned_tag(local_repo_factory, tmp_path):
    url = local_repo_factory("pkg", tags=["v1.0.0", "v2.0.0"])
    dest = tmp_path / "checkout"

    Git.fetch_pinned(url, "v1.0.0", "tag", dest)

    assert (dest / "VERSION").read_text().strip() == "v1.0.0"


def test_fetch_pinned_commit(local_repo_factory, tmp_path):
    url = local_repo_factory("pkg", branch="main", extra_commits=2)
    sha = Git.ls_remote_branch(url, "main")
    dest = tmp_path / "checkout"

    Git.fetch_pinned(url, sha, "commit", dest)

    checked_out = Git(dest).head()
    assert checked_out == sha


def test_fetch_pinned_is_reproducible(local_repo_factory, tmp_path):
    url = local_repo_factory("pkg", tags=["v1.0.0"])

    dest_a = tmp_path / "a"
    dest_b = tmp_path / "b"
    Git.fetch_pinned(url, "v1.0.0", "tag", dest_a)
    Git.fetch_pinned(url, "v1.0.0", "tag", dest_b)

    assert (dest_a / "VERSION").read_text() == (dest_b / "VERSION").read_text()
    assert Git(dest_a).head() == Git(dest_b).head()
