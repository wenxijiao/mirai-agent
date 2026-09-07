"""Shared path boundary for image prompts and authenticated image downloads."""

from pathlib import Path

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".ico"})


def resolve_owned_image(path: str, owner_user_id: str, *, root: Path) -> Path:
    root = root.resolve()
    scoped_root = root if owner_user_id == "_local" else root / owner_user_id
    candidate = Path(path).resolve()
    if (
        not scoped_root.resolve().is_relative_to(root)
        or not candidate.is_relative_to(scoped_root)
        or candidate.suffix.lower() not in IMAGE_EXTENSIONS
        or not candidate.is_file()
    ):
        raise FileNotFoundError("Image not found.")
    return candidate
