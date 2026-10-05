"""One import of the fictional designed CV for the whole run: a derivation draws two 300 dpi layers."""

from __future__ import annotations

import pytest

from tests.profil.cv.fixtures import ReaderModel, Shared, designed_cv, imported


@pytest.fixture(scope="session")
def designed() -> bytes:
    return designed_cv()


@pytest.fixture(scope="session")
def shared(designed: bytes, tmp_path_factory: pytest.TempPathFactory) -> Shared:
    root = tmp_path_factory.mktemp("import")
    model = ReaderModel()
    return Shared(root, imported(designed, root, model), model)
