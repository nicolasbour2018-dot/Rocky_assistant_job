"""Account files under one storage root: content-addressed, immutable, read back with their hash checked.

Decision ``docs/decisions/D2-cv-rendu.md`` (Q7, Q24): paths are stored relative to the root, never absolute; a
bundle (a CV template) is a directory named by the hash of its content, written once and atomically. The same
content written twice gives the same path and writes nothing (idempotent).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

MANIFEST = "SHA256SUMS"


class FileError(Exception):
    """A stored file is missing, altered or outside the root; ``reason`` is shown as is (French)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class StoredFile:
    path: str  # relative to the storage root, POSIX separators
    sha256: str


@dataclass(frozen=True)
class StoredBundle:
    path: str  # relative directory
    sha256: str  # hash of the manifest: names and hashes of every file
    names: tuple[str, ...]


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def bundle_hash(files: Mapping[str, bytes]) -> str:
    """The identity of a set of files: independent of the order they are given in."""
    return sha256(_manifest(files).encode())


class FileStore:
    """Files of each account under ``<root>/comptes/<account_id>/``."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def put_file(
        self, account_id: int, kind: str, content: bytes, suffix: str
    ) -> StoredFile:
        """Store ``content`` under its hash (``comptes/<id>/<kind>/<sha>.<suffix>``); idempotent."""
        digest = sha256(content)
        relative = _relative(account_id, kind, f"{digest}.{_suffix(suffix)}")
        target = self._absolute(relative)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_atomically(target, content)
        return StoredFile(path=relative, sha256=digest)

    def put_bundle(
        self, account_id: int, kind: str, files: Mapping[str, bytes]
    ) -> StoredBundle:
        """Store ``files`` in ``comptes/<id>/<kind>/<hash>/``, all or nothing; idempotent."""
        if not files:
            raise ValueError("a bundle needs at least one file")
        for name in files:
            _check_name(name)
        digest = bundle_hash(files)
        relative = _relative(account_id, kind, digest)
        target = self._absolute(relative)
        names = tuple(sorted(files))
        if target.exists():
            self.read_bundle(relative, digest)  # an existing bundle must be intact
            return StoredBundle(path=relative, sha256=digest, names=names)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=target.parent))
        try:
            for name, content in files.items():
                (staging / name).write_bytes(content)
            (staging / MANIFEST).write_text(_manifest(files))
            staging.rename(target)
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)
            # A concurrent writer of the same content is not an error.
            if not target.exists():
                raise
        return StoredBundle(path=relative, sha256=digest, names=names)

    def find_bundle(
        self, account_id: int, kind: str, name: str, content: bytes
    ) -> dict[str, bytes] | None:
        """The files of an intact bundle of the account holding ``name`` with ``content`` (a bundle's directory is
        named by its hash: each one found is checked like any read); None when there is none."""
        _check_name(name)
        directory = self._absolute(_relative(account_id, kind, "x")).parent
        if not directory.is_dir():
            return None
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            candidate = entry / name
            if not candidate.is_file() or candidate.read_bytes() != content:
                continue
            path = _relative(account_id, kind, entry.name)
            try:
                return self.read_bundle(path, entry.name)
            except FileError as error:
                # Another copy may still be intact: the search goes on, the damaged one is made visible.
                logger.warning("bundle %s skipped: %s", path, error)
                continue
        return None

    def read_file(self, path: str, expected_sha256: str) -> bytes:
        content = self._read(path)
        if sha256(content) != expected_sha256:
            raise FileError(
                f"Le fichier {path} a été modifié depuis son enregistrement."
            )
        return content

    def read_bundle(self, path: str, expected_sha256: str) -> dict[str, bytes]:
        """Every file of a bundle, each checked against the manifest, the manifest against its hash."""
        directory = self._absolute(path)
        if not directory.is_dir():
            raise FileError(f"Le dossier {path} est introuvable.")
        names = sorted(
            entry.name for entry in directory.iterdir() if entry.name != MANIFEST
        )
        files = {name: (directory / name).read_bytes() for name in names}
        manifest = self._read(f"{path}/{MANIFEST}").decode()
        if manifest != _manifest(files) or bundle_hash(files) != expected_sha256:
            raise FileError(
                f"Le dossier {path} a été modifié depuis son enregistrement."
            )
        return files

    def _read(self, path: str) -> bytes:
        target = self._absolute(path)
        try:
            return target.read_bytes()
        except FileNotFoundError as error:
            raise FileError(f"Le fichier {path} est introuvable.") from error

    def _absolute(self, relative: str) -> Path:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise FileError(f"Chemin refusé : {relative}.")
        return self._root.joinpath(*pure.parts)


def _relative(account_id: int, kind: str, name: str) -> str:
    _check_name(kind)
    return f"comptes/{account_id}/{kind}/{name}"


def _check_name(name: str) -> None:
    if not name or name in (".", "..", MANIFEST) or "/" in name or "\\" in name:
        raise ValueError(f"invalid file name: {name!r}")


def _suffix(suffix: str) -> str:
    cleaned = suffix.lstrip(".").lower()
    if not cleaned.isalnum():
        raise ValueError(f"invalid suffix: {suffix!r}")
    return cleaned


def _manifest(files: Mapping[str, bytes]) -> str:
    return "".join(f"{sha256(files[name])}  {name}\n" for name in sorted(files))


def _write_atomically(target: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".staging-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        Path(temporary).replace(target)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise
