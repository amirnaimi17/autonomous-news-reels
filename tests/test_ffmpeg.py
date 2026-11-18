"""FFmpeg encoder selection."""

import shutil

import pytest

from app.core.exceptions import ConfigurationError
from app.services.video.ffmpeg import (
    capabilities_from_output,
    probe_ffmpeg,
    select_encoder,
)

_SAMPLE = """
Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder
 A....D aac                  AAC
"""


def test_encoder_parser_and_preference() -> None:
    capabilities = capabilities_from_output("ffmpeg version 8.0.1\n", _SAMPLE)
    assert capabilities.h264_nvenc
    assert capabilities.libx264
    assert select_encoder(capabilities, "auto") == "h264_nvenc"
    assert select_encoder(capabilities, "libx264") == "libx264"
    cpu_only = capabilities_from_output(
        "ffmpeg version 5\n",
        " V....D libx264              libx264 H.264\n",
    )
    assert select_encoder(cpu_only, "auto") == "libx264"
    with pytest.raises(ConfigurationError):
        select_encoder(cpu_only, "h264_nvenc")


def test_local_ffmpeg_matches_this_machine() -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    capabilities = probe_ffmpeg("ffmpeg")
    assert capabilities.available
    assert capabilities.libx264
    if shutil.which("nvidia-smi") is not None:
        assert capabilities.h264_nvenc
        assert select_encoder(capabilities, "auto") == "h264_nvenc"
