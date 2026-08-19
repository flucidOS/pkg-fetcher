import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def local_repo_factory(tmp_path):
    """
    Builds a local bare git repo (so it can be addressed by a plain
    file:// path via `git ls-remote`/`git clone`, exactly like a real
    remote) with a given set of commits and tags.
    """

    def make(name: str, *, tags=(), branch="main", extra_commits=0):
        work = tmp_path / f"{name}-work"
        bare = tmp_path / f"{name}.git"
        work.mkdir()

        _git("init", "--quiet", f"--initial-branch={branch}", cwd=work)
        _git("config", "user.email", "test@example.invalid", cwd=work)
        _git("config", "user.name", "Test", cwd=work)

        (work / "VERSION").write_text("0.0.0\n")
        _git("add", ".", cwd=work)
        _git("commit", "--quiet", "-m", "initial", cwd=work)

        for tag in tags:
            (work / "VERSION").write_text(f"{tag}\n")
            _git("add", ".", cwd=work)
            _git("commit", "--quiet", "-m", f"release {tag}", cwd=work)
            _git("tag", tag, cwd=work)

        for i in range(extra_commits):
            (work / f"file_{i}.txt").write_text(f"commit {i}\n")
            _git("add", ".", cwd=work)
            _git("commit", "--quiet", "-m", f"extra commit {i}", cwd=work)

        _git("clone", "--quiet", "--bare", str(work), str(bare), cwd=tmp_path)
        return f"file://{bare}"

    return make
