---
name: build-reel-storyboard
description: Convert an approved four-scene Reel script into a precise 9:16 visual plan with motion, captions, safe zones, and explicit generated-asset status.
---
# Four-scene storyboard

1. Read `story_package.json`; stop if not exactly four scenes.
2. Produce a matched `visual_plan.json` with one scene for each script scene. Use 1080x1920, 30fps, readable high-contrast headline text and conservative title/safe areas (avoid lower UI overlays).
3. For each scene specify subject, image-generation prompt, typography, caption placement, transitions, camera motion, duration and desired asset filename.
4. Never claim to possess a generated image when only a prompt exists. Set `asset_path` to empty string until a real file has been produced.
5. For factual news, illustrations must be recognizable as *illustrative*, not a fabricated photograph of an actual event. When needed include a visible generated-visuals disclaimer.
6. For Persian, require testing of RTL line breaks and glyph shaping in a **real preview** rather than trusting generic FFmpeg text rendering.
7. Save draft to the same `storage/generated/pilot/<run-id>/` as the script. Do not generate media or spend tokens/credits on third-party assets without consent.

Show all four visual ideas to the user and ask for approval before production.
