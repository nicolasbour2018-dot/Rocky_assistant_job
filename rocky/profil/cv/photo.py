"""The photo of the CV (decision D2, Q7): an image checked before it is stored, never trusted by its name."""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

from rocky.profil.rules import ProfileInputError

MAX_BYTES = 5 * 1024 * 1024
MIN_SIDE_PX = 150
# Pillow format → stored suffix.
FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def photo_suffix(content: bytes) -> str:
    """The suffix to store ``content`` under; refuses what is not a usable photo."""
    if not content:
        raise ProfileInputError("Choisis une photo.")
    if len(content) > MAX_BYTES:
        raise ProfileInputError("La photo dépasse 5 Mo.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            kind, (width, height) = image.format, image.size
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ProfileInputError(
            "Ce fichier n'est pas une image lisible (JPEG, PNG ou WebP)."
        ) from None
    if kind not in FORMATS:
        raise ProfileInputError("La photo doit être en JPEG, PNG ou WebP.")
    if min(width, height) < MIN_SIDE_PX:
        raise ProfileInputError(
            f"La photo est trop petite ({width} × {height} px) : au moins {MIN_SIDE_PX} px de côté."
        )
    return FORMATS[kind]
