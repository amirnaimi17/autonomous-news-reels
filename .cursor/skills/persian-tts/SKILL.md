---
name: persian-tts
description: Generate reusable Persian Reel narration. Aran on ElevenLabs eleven_v4 is the production voice. Edge TTS Farid is the fallback. Never use espeak-ng.
---

# Persian TTS

Use this for every fa-IR Reel narration. The voice generator is the existing `reel-producer`, not a second agent.

## Rules

- Production voice: ElevenLabs Aran, model `eleven_v4`, voice ID `PEdcOLzbXYhL8IKOswXB`, language `fa`, speed `1.0`. `config/voices.json` stores that choice. Arash, Connery, Farid, and Dilara remain available options.
- Fallback: Microsoft Edge TTS `fa-IR-FaridNeural` at `+0%` when `ELEVENLABS_API_KEY` is unset. `scripts/speak.py` is that fallback and does not call ElevenLabs.
- `scripts/elevenlabs.py` builds the documented Eleven v4 convert call (`model_id` `eleven_v4`, `language_code` `fa`, `apply_text_normalization` `off`, speed `1.0`, output `mp3_44100_128`). It reads `ELEVENLABS_API_KEY` and never writes that value. Listing account voices is `GET /v2/voices`. Listing shared voices is `GET /v1/shared-voices` with `language=fa`. Both stay unsent until `--approve-list`. Speech stays unsent until the voice-only cost gate allows it. An unpriced OpenAI image does not block that gate.
- ElevenLabs `eleven_v4` documents Persian and publishes $0.08 per 1,000 characters. `eleven_multilingual_v2` does not list Persian. Premade voices are documented as English, so a Persian news voice has to be chosen from the shared library after the list returns. A custom `fiat_rate` blocks the quote. OpenAI `tts-1` is not the voice candidate.
- Never use `espeak-ng`, a silent WAV, or another voice unless the user names one for a listening test.
- Write narration as spoken news copy: complete short sentences, one pause at each period, professional and conversational. Do not hand the engine a headline, a colon splice, or a sentence with the verb cut off.
- The display narration may keep digits and ordinary Persian spellings. `prepare_narration` converts dates and numbers, applies `config/pronunciation.json`, and keeps that display string unchanged. A dictionary entry may change only the spoken form of a name.
- Start at rate `+0%`. Do not raise the speaking rate to hide a long script. `--allow-rate` is only for an explicit listening test.
- Speak the approved script. Do not reuse an older recording, and do not cut the last sentence to fit 35–45 seconds. A package with `duration_policy` `completeness` is spoken as written.
- Subtitle times come from the audio that was just generated, or from alignment of that same file. Never stretch another voice's timestamps onto this recording.
- Save `voice_manifest.json` next to the scene mp3 files. It must record `engine`, `voice`, `rate`, and `espeak_used: false`.

## Setup

```bash
python3 -m venv .cursor/skills/persian-tts/.venv
.cursor/skills/persian-tts/.venv/bin/pip install -r .cursor/skills/persian-tts/requirements.txt
```

## Generate

```bash
.cursor/skills/persian-tts/.venv/bin/python .cursor/skills/persian-tts/scripts/speak.py \
  --story storage/generated/pilot/<run-id>/story_package.json \
  --out-dir storage/generated/pilot/<run-id>/audio \
  --voice fa-IR-FaridNeural --rate +0% --target 40 --min-seconds 38 --max-seconds 42 --transition 0.4
```

The script reads the narration scenes, speaks the preprocessed form at the requested rate, and writes one mp3 per scene, word timings, and `voice_manifest.json`. A package marked `completeness` is not rejected for length. Otherwise a result outside the requested window stops the script. Do not pad with espeak or time-stretch.

Compare one prepared passage, using the same spoken text for both voices:

```bash
.cursor/skills/persian-tts/.venv/bin/python .cursor/skills/persian-tts/scripts/speak_pair.py \
  --display storage/generated/pilot/<run-id>/narration-display.txt \
  --out-dir storage/generated/pilot/<run-id>
```

Human listening is required before calling either voice natural. ParsVoice-XTTS was not run: this machine has a 4 GB Quadro T2000 and about 2 GB free, which is below a safe local XTTS load.

Do not generate the MP4 from this skill. Hand `audio/voice_manifest.json` to `reel-video-design`.
