---
name: build-reel-storyboard
description: Turn an approved Reel script into a 9:16 visual plan. Choose a graphic or a photograph per scene, and write a full English image prompt only when a photograph is actually needed.
---
# Visual art direction

`reel-producer` owns this. Do not add a second visual agent.

1. Read the approved script and the news-director brief. The scene count follows the narration. Do not force three images.
2. For each scene, choose one format: a licensed photograph, licensed video, a Remotion graphic, or an AI illustration. Prefer a photograph or video of the real setting when the license is clear and the crop works at 9:16. A graphic carries the numbers, dates, and provider exceptions. An AI illustration is the last option. A decorative frame is not a scene. Do not repeat a composition, and do not label a generic or older photograph as footage of the event itself.
3. Keep one visual anchor when a document, object, or place can connect the scenes. Change the angle. Do not force a person into every scene. A reference image is only for a later photograph of that same object, and only after the cost gate.
4. Write `image_prompt` only for an `editorial-photograph`. The prompt is standalone English and names the subject, environment, action, composition, camera, lighting, mood, foreground, background, depth, and negative space. Keep the palette dark navy, bright yellow, and white. Leave the safe area empty for type. Put no Persian words in the prompt.
5. Set Persian headlines, numbers, captions, and subtitles in Remotion, right to left, inside about 250px from the top, 450px from the bottom, and 160px from the right.
6. Record purpose, narration segment, format, why this format was chosen, anchor, motion, transition, duration, and expected cost. A graphic costs nothing. An empty `asset_path` means the file does not exist yet.
7. Save `visual_plan.json` beside the script. Do not generate media or spend credits without approval.

Show the plan and ask before any paid image call.
