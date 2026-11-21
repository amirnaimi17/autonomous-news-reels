---
name: render-reel-pilot
description: Attempt a local draft vertical MP4 from approved four-slide assets and REAL narration audio, checking capabilities and avoiding mock success claims or publication.
disable-model-invocation: true
---
# Local Reel draft render

Do not invoke unless the user explicitly requests a render and approves the required tools/assets.

1. Require approved `story_package.json`, four existing illustration files, and a `voice_manifest.json` from `persian-tts`. For fa-IR that voice is `fa-IR-FaridNeural`. Refuse espeak audio.
2. Render with `python3 .cursor/skills/reel-video-design/scripts/render_reel.py` as that skill describes. It tests NVENC with a one-frame encode and falls back to `libx264` only if that test fails. Illustrations come from `reel-image-generation` and must already exist. The manifest rate must be `+0%`.
3. The script builds 1080×1920, 30 fps, H.264, AAC, four scenes, 0.4s transitions, and libass Persian subtitles timed to Edge word boundaries. Do not use `drawtext` for Persian.
4. Write `storage/generated/pilot/<run-id>/reel.mp4`. Do not overwrite another run. Do not publish.
5. Run ffprobe and inspect one frame from each scene. Return the real duration, codec, voice name from the manifest, and defects. A manifest entry is not a human listening test.

If actual audio/images are absent, STOP with `BLOCKED`, show missing prerequisites, and do not report a Reel as created.
