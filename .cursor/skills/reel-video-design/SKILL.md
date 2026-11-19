---
name: reel-video-design
description: Render a four-scene 1080x1920 Instagram Reel with timed Persian subtitles, scene transitions, and NVENC H.264. Use when /run-news-pilot or reel-producer builds the MP4 after persian-tts. Do not use this to invent narration.
---

# Reel video design

The existing `reel-producer` runs this after `persian-tts`. Do not add a second video agent. Remotion is not used: the repo already renders with FFmpeg, and a Node composition is extra machinery for this pilot.

## Picture

- 1080×1920, 30 fps, exactly four scenes, H.264 AAC.
- Final duration 38–42 seconds unless the user set another window.
- One shared look: darkened illustrations, the same Persian type, a persistent disclaimer that the images are drawings.
- Motion is a slow drift and scale that changes per scene, then `smoothleft`, `smoothright`, and `fade` transitions of 0.4s. Do not use a single static zoom with hard cuts.
- Headlines are the short `on_screen_text` lines. Subtitles are the narration, timed from Edge word boundaries, shaped with Noto Naskh Arabic through libass. Do not use `drawtext` for Persian.
- Prefer `h264_nvenc` when a one-frame encode succeeds. If it fails, use `libx264` and say so. Do not claim NVENC from the encoder list alone.
- Illustrations stay illustrations. Do not present them as photographs of the people or the event.

## Render

Requires `audio/voice_manifest.json` from `persian-tts` whose voice is `fa-IR-FaridNeural`.

```bash
python3 .cursor/skills/reel-video-design/scripts/render_reel.py \
  --story storage/generated/pilot/<run-id>/story_package.json \
  --manifest storage/generated/pilot/<run-id>/audio/voice_manifest.json \
  --images scene-01.jpg scene-02.jpg scene-03.jpg scene-04.jpg \
  --work storage/generated/pilot/<run-id>/work \
  --out storage/generated/pilot/<run-id>/reel.mp4
```

Then `ffprobe` the MP4 and read `render_report.json`. Update `story_package.json` scene durations so they sum to the measured duration within 0.25s. A file that does not decode is not a finished Reel.
