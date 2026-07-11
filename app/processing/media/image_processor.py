from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from PIL import Image, ImageOps

from app.core.config import settings

MAX_IMAGE_DIMENSION = 1600
JPEG_QUALITY = 82
HASH_CHUNK_SIZE = 1024 * 1024


def save_optimized_image(source_path: Path) -> tuple[dict[str, Any], Path]:
    """Validate, strip metadata, resize and persist a safe JPEG copy by its SHA-256."""
    media_root = settings.media_storage_path.resolve()
    media_root.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as check:
        check.verify()
    with NamedTemporaryFile(
        mode="wb", suffix=".jpg", prefix=".processing-", dir=media_root, delete=False
    ) as temporary_file:
        temporary_output = Path(temporary_file.name)
    try:
        with Image.open(source_path) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
            image.save(temporary_output, "JPEG", quality=JPEG_QUALITY, optimize=True)
        digest = hashlib.sha256()
        with temporary_output.open("rb") as output:
            for chunk in iter(lambda: output.read(HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        destination = media_root / f"{sha256}.jpg"
        if destination.exists():
            temporary_output.unlink(missing_ok=True)
        else:
            temporary_output.replace(destination)
        return (
            {
                "relative_path": f"media/{destination.name}",
                "mime_type": "image/jpeg",
                "size_bytes": destination.stat().st_size,
                "sha256": sha256,
            },
            destination,
        )
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise
