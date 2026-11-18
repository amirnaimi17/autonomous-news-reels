"""Offline slide images.

A solid frame is enough to prove the provider boundary and to give FFmpeg a
real input later. It does not invent a photograph of the news event.
"""

from pathlib import Path

from app.schemas.content import GeneratedImage
from app.schemas.workflow import SlideVisualRequest


class SolidColorImageProvider:
    """Write a vertical PPM frame of one flat color."""

    name = "solid"

    def __init__(self, rgb: tuple[int, int, int] = (18, 32, 48)) -> None:
        if any(channel < 0 or channel > 255 for channel in rgb):
            raise ValueError("rgb channels must be 0 to 255")
        self._rgb = rgb

    def generate(self, request: SlideVisualRequest, *, width: int, height: int) -> GeneratedImage:
        if width < 2 or height < 2 or width % 2 or height % 2:
            raise ValueError("image dimensions must be positive even numbers")
        path = Path(request.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = f"P6\n{width} {height}\n255\n".encode("ascii")
        pixel = bytes(self._rgb)
        path.write_bytes(header + pixel * (width * height))
        return GeneratedImage(
            slide_index=request.slide_index,
            path=str(path),
            width=width,
            height=height,
            provider=self.name,
        )
