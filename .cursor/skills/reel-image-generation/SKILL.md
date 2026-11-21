---
name: reel-image-generation
description: Choose a Reel illustration provider from measured hardware, keep prompts free of baked-in text, and record model settings. Use before reel-producer generates scene art. Do not replace Cursor GenerateImage until a local model actually renders a better image.
---

# Reel image generation

`reel-producer` uses this skill when it needs the four scene illustrations. There is no separate image agent.

Look for a real licensed photograph or video before any generated image. Wikimedia Commons is the default search. Pexels is allowed only when `PEXELS_API_KEY` is set and the file carries the Pexels license. Do not scrape Google Images or save a news photograph whose reuse terms are missing. `scripts/commons_assets.py` accepts CC0, CC BY, CC BY-SA, and public domain, and rejects non-commercial licenses, no-derivatives licenses, and any extra restriction on the file page.

For every kept file record the Commons page, the download URL, the creator, the license URL, the required attribution, and the narration beat it serves. A file that shows a private ticket code, a person's name, or an outdated price is rejected even when the license is open.

Use OpenAI only when no suitable real asset exists or a diagram is the clearer explanation. Do not generate four illustrations by default. `scripts/layout.py` chooses type, a chart, or one optional hero. Run `reel-cost-tracking` before a paid image call. `scripts/openai_images.py` builds `POST /v1/images/generations` for `gpt-image-2.5-sunburst` at `1024x1536`, quality `high`, PNG, `n` 1. It reads `OPENAI_API_KEY` and never writes that value. The published rates are $30, $5, and $8 per 1M image-output, text-input, and image-input tokens. The output-token count is not published, so the cost gate blocks the call until a usage object supplies it. Cursor GenerateImage has no price in the catalog. Google `gemini-nano-banana-2.1` remains the priced alternative at $0.0336 per 1K output image; `GOOGLE_API_KEY` is unset. Imagen 4 is not a current endpoint. SDXL and FLUX still do not fit the 4 GB GPU.

Measured on 19 Nov 2026: NVIDIA Quadro T2000 Max-Q, 4096 MiB VRAM, about 2019 MiB free, compute capability 7.5. Python 3.14. ComfyUI is not installed. A local Node.js 22 binary was added later for the Remotion proof and is not on the system path.

| Candidate | Decision |
| --- | --- |
| Cursor GenerateImage | Usable, but unpriced. A new call does not pass `reel-cost-tracking`. |
| ComfyUI | Not selected. Nothing is listening on `127.0.0.1:8188`. A client that cannot reach ComfyUI must fail closed. |
| SDXL | Rejected. A usable SDXL load is about 8 GiB, above 4096 MiB. It was not downloaded. |
| FLUX schnell / FLUX dev | Rejected. Both need more VRAM than this card. They were not downloaded. |

Do not claim a local model is better until it has rendered on this machine and a person has compared the frames.

```bash
python3 .cursor/skills/reel-image-generation/scripts/select_provider.py
python3 .cursor/skills/reel-image-generation/tests/test_providers.py
```

## Prompt rules

Read `config/style.json`. Every scene uses the same style id.

- No letters, numbers, logos, or captions inside the illustration.
- No faces, hands, or likenesses of the people in the story.
- Not a photograph of the event. The video disclaimer says the images are drawings.
- Save `image_manifest.json` with the prompt, provider, model id, seed, and file path for each scene.
