"""Output directories.

Every media path is built here so a later per-client layout has one change.
"""

from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings


@dataclass(frozen=True)
class MediaDirs:
    """Directories for one deployment's generated files."""

    root: Path
    images: Path
    audio: Path
    videos: Path
    generated: Path


def media_dirs(settings: Settings) -> MediaDirs:
    root = settings.output_dir
    return MediaDirs(
        root=root,
        images=root / "images",
        audio=root / "audio",
        videos=root / "videos",
        generated=root / "generated",
    )


def ensure_media_dirs(settings: Settings) -> MediaDirs:
    """Create the media directories if they are missing."""

    dirs = media_dirs(settings)
    for path in (dirs.images, dirs.audio, dirs.videos, dirs.generated):
        path.mkdir(parents=True, exist_ok=True)
    return dirs
