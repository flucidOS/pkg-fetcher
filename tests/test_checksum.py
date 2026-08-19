from fetcher.checksum import Checksum


def test_hash_is_deterministic(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")
    (tree / "b.txt").write_text("world")

    h1 = Checksum.hash_tree(tree)
    h2 = Checksum.hash_tree(tree)

    assert h1 == h2
    assert h1.startswith("sha256:")


def test_hash_ignores_walk_order(tmp_path):
    tree_a = tmp_path / "a"
    tree_b = tmp_path / "b"
    tree_a.mkdir()
    tree_b.mkdir()

    (tree_a / "1.txt").write_text("one")
    (tree_a / "2.txt").write_text("two")

    # Create in reverse order on disk -- hash must not depend on that.
    (tree_b / "2.txt").write_text("two")
    (tree_b / "1.txt").write_text("one")

    assert Checksum.hash_tree(tree_a) == Checksum.hash_tree(tree_b)


def test_hash_changes_with_content(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")
    before = Checksum.hash_tree(tree)

    (tree / "a.txt").write_text("hello!")
    after = Checksum.hash_tree(tree)

    assert before != after


def test_hash_changes_with_filename(tmp_path):
    tree_a = tmp_path / "a"
    tree_b = tmp_path / "b"
    tree_a.mkdir()
    tree_b.mkdir()

    (tree_a / "x.txt").write_text("same content")
    (tree_b / "y.txt").write_text("same content")

    assert Checksum.hash_tree(tree_a) != Checksum.hash_tree(tree_b)


def test_git_metadata_ignored(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")
    before = Checksum.hash_tree(tree)

    git_dir = tree / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")

    after = Checksum.hash_tree(tree)
    assert before == after


def test_verify(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")

    expected = Checksum.hash_tree(tree)
    assert Checksum.verify(tree, expected) is True
    assert Checksum.verify(tree, "sha256:deadbeef") is False
