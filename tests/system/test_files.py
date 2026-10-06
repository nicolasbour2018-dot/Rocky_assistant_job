"""Account files: content-addressed, immutable bundles, hashes checked on read (decision D2, Q7, Q24)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from rocky.system.files import MANIFEST, FileError, FileStore, bundle_hash, sha256


def test_a_file_is_stored_under_its_hash_relative_to_the_root(tmp_path: Path) -> None:
    store = FileStore(tmp_path)

    stored = store.put_file(7, "photos", b"jpeg bytes", ".JPG")

    assert stored.path == f"comptes/7/photos/{sha256(b'jpeg bytes')}.jpg"
    assert not Path(stored.path).is_absolute()
    assert store.read_file(stored.path, stored.sha256) == b"jpeg bytes"


def test_storing_the_same_file_twice_gives_the_same_path(tmp_path: Path) -> None:
    store = FileStore(tmp_path)

    assert store.put_file(7, "photos", b"a", "png") == store.put_file(
        7, "photos", b"a", "png"
    )


def test_an_altered_file_is_refused_on_read(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    stored = store.put_file(7, "photos", b"original", "png")
    (tmp_path / stored.path).write_bytes(b"altered")

    with pytest.raises(FileError, match="modifié"):
        store.read_file(stored.path, stored.sha256)


def test_a_bundle_is_named_by_its_content_whatever_the_order(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    files = {"template.json": b"{}", "layer.svg": b"<svg/>"}

    stored = store.put_bundle(3, "gabarits", files)
    again = store.put_bundle(3, "gabarits", dict(reversed(files.items())))

    assert stored == again
    assert stored.sha256 == bundle_hash(files)
    assert stored.path == f"comptes/3/gabarits/{stored.sha256}"
    assert stored.names == ("layer.svg", "template.json")
    assert store.read_bundle(stored.path, stored.sha256) == files


def test_a_bundle_leaves_no_staging_directory(tmp_path: Path) -> None:
    store = FileStore(tmp_path)

    store.put_bundle(3, "gabarits", {"a.txt": b"a"})

    leftovers = [p.name for p in (tmp_path / "comptes/3/gabarits").iterdir()]
    assert len(leftovers) == 1
    assert not leftovers[0].startswith(".staging")


def test_an_altered_bundle_is_refused(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    stored = store.put_bundle(3, "gabarits", {"a.txt": b"a", "b.txt": b"b"})
    (tmp_path / stored.path / "b.txt").write_bytes(b"changed")

    with pytest.raises(FileError, match="modifié"):
        store.read_bundle(stored.path, stored.sha256)
    with pytest.raises(FileError, match="modifié"):
        store.put_bundle(3, "gabarits", {"a.txt": b"a", "b.txt": b"b"})


def test_a_bundle_with_an_added_file_is_refused(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    stored = store.put_bundle(3, "gabarits", {"a.txt": b"a"})
    (tmp_path / stored.path / "extra.txt").write_bytes(b"x")

    with pytest.raises(FileError, match="modifié"):
        store.read_bundle(stored.path, stored.sha256)


@pytest.mark.parametrize("path", ["/etc/passwd", "comptes/1/../../secret"])
def test_paths_outside_the_root_are_refused(tmp_path: Path, path: str) -> None:
    with pytest.raises(FileError, match="Chemin refusé"):
        FileStore(tmp_path).read_file(path, "0" * 64)


@pytest.mark.parametrize("name", ["", "..", "a/b", MANIFEST])
def test_invalid_names_in_a_bundle_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="invalid file name"):
        FileStore(tmp_path).put_bundle(3, "gabarits", {name: b"x"})


def test_a_corrupted_bundle_skipped_by_the_search_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """H3: a bundle found altered is passed over, never silently (AGENTS §4)."""
    store = FileStore(tmp_path)
    kept = store.put_bundle(
        1, "imports", {"texte.sha256": b"abc", "reponse.json": b"{}"}
    )
    (tmp_path / kept.path / "reponse.json").write_bytes(b"altered")

    with caplog.at_level(logging.WARNING, logger="rocky.system.files"):
        assert store.find_bundle(1, "imports", "texte.sha256", b"abc") is None

    (record,) = caplog.records
    assert kept.path in record.getMessage()


def test_a_missing_file_says_so(tmp_path: Path) -> None:
    with pytest.raises(FileError, match="introuvable"):
        FileStore(tmp_path).read_file("comptes/1/photos/none.png", "0" * 64)


def test_a_bundle_is_found_by_one_of_its_files_and_only_when_intact(
    tmp_path: Path,
) -> None:
    store = FileStore(tmp_path)
    kept = store.put_bundle(
        1, "imports", {"texte.sha256": b"abc", "reponse.json": b"{}"}
    )
    store.put_bundle(1, "imports", {"texte.sha256": b"other", "reponse.json": b"[]"})

    assert store.find_bundle(1, "imports", "texte.sha256", b"abc") == {
        "texte.sha256": b"abc",
        "reponse.json": b"{}",
    }
    assert store.find_bundle(1, "imports", "texte.sha256", b"none") is None
    assert store.find_bundle(2, "imports", "texte.sha256", b"abc") is None

    (tmp_path / kept.path / "reponse.json").write_bytes(b"altered")
    assert store.find_bundle(1, "imports", "texte.sha256", b"abc") is None
