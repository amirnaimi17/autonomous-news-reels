#!/usr/bin/env python3
"""Render a four-scene 1080x1920 Reel from a story package and Farid narration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

FONTS = Path(__file__).resolve().parents[1] / "fonts"
WIDTH = 1080
HEIGHT = 1920
FPS = 30
TRANSITION = 0.4
TRANSITIONS = ("smoothleft", "smoothright", "fade")


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(command: list[str]) -> None:
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        fail("command failed: " + " ".join(command) + "\n" + (completed.stderr or "")[-2500:])


def probe(path: Path) -> dict:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height,pix_fmt,sample_rate,channels",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        fail(completed.stderr.strip() or f"ffprobe failed for {path}")
    return json.loads(completed.stdout)


def duration_of(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def nvenc_works() -> bool:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=320x320:r=30:d=0.2",
            "-c:v",
            "h264_nvenc",
            "-f",
            "null",
            "-",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    return completed.returncode == 0


def ass_time(seconds: float) -> str:
    total = max(0, int(round(seconds * 100)))
    centiseconds = total % 100
    whole = total // 100
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def group_words(words: list[dict], max_chars: int = 36) -> list[dict]:
    groups: list[dict] = []
    bucket: list[dict] = []
    for word in words:
        bucket.append(word)
        text = " ".join(item["text"] for item in bucket)
        sentence_end = text.rstrip().endswith((".", "؟", "!", ":", "؛"))
        if len(text) >= max_chars or sentence_end:
            groups.append(
                {"text": text, "start": bucket[0]["start"], "end": bucket[-1]["end"]}
            )
            bucket = []
    if bucket:
        groups.append({"text": " ".join(item["text"] for item in bucket), "start": bucket[0]["start"], "end": bucket[-1]["end"]})
    return groups


def write_ass(story: dict, manifest: dict, offsets: list[float], path: Path) -> None:
    events = []
    disclaimer = story.get("caption_disclaimer") or "تصویرها طرح توضیحی‌اند، نه فیلم و نه عکس رویداد."
    events.append(
        f"Dialogue: 0,{ass_time(0)},{ass_time(offsets[-1] + manifest['scenes'][-1]['duration'])},Disclaimer,,0,0,0,,{escape_ass(disclaimer)}"
    )
    for scene, spoken, offset in zip(story["scenes"], manifest["scenes"], offsets, strict=True):
        headline = escape_ass(scene["on_screen_text"])
        events.append(
            f"Dialogue: 1,{ass_time(offset)},{ass_time(offset + spoken['duration'])},Headline,,0,0,0,,{{\\fad(220,180)}}{headline}"
        )
        groups = spoken.get("captions") or group_words(spoken.get("words") or [])
        if not groups:
            groups = [{"text": spoken["narration"], "start": 0.0, "end": float(spoken["duration"])}]
        for line in groups:
            start = offset + float(line["start"])
            end = max(start + 0.35, offset + float(line["end"]))
            events.append(
                f"Dialogue: 2,{ass_time(start)},{ass_time(end)},Subtitle,,0,0,0,,{{\\fad(80,80)}}{escape_ass(line['text'])}"
            )
    body = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Disclaimer,Vazirmatn,28,&H00ECF4F7,&H000000FF,&HE612161C,&HE612161C,0,0,0,0,100,100,0,0,3,12,0,8,72,72,120,1
Style: Headline,Vazirmatn,46,&H00ECF4F7,&H000000FF,&HE612161C,&HE612161C,-1,0,0,0,100,100,0,0,3,16,0,8,90,90,280,1
Style: Subtitle,Vazirmatn,38,&H00F7F4EC,&H000000FF,&HE612161C,&HE612161C,0,0,0,0,100,100,0,0,3,14,0,2,96,96,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path.write_text(body + "\n".join(events) + "\n", encoding="utf-8")


def motion(index: int, frames: int) -> str:
    span = max(frames - 1, 1)
    motions = {
        1: f"z='1.00+0.08*on/{span}':x='(iw-iw/zoom)/2+36*on/{span}':y='(ih-ih/zoom)/2'",
        2: f"z='1.08-0.06*on/{span}':x='(iw-iw/zoom)/2-32*on/{span}':y='(ih-ih/zoom)/2+12*on/{span}'",
        3: f"z='1.02+0.07*on/{span}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2-40*on/{span}'",
        4: f"z='1.03+0.05*on/{span}':x='(iw-iw/zoom)/2-18*on/{span}':y='(ih-ih/zoom)/2-16*on/{span}'",
    }
    return motions[index]


def fit_audio(source: Path, seconds: float, destination: Path) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-af",
            f"apad=pad_dur=2,atrim=0:{seconds:.3f}",
            "-ar",
            "24000",
            "-ac",
            "1",
            str(destination),
        ]
    )


def _accepted_narration(manifest: dict) -> bool:
    """Aran is the production voice. Farid at natural speed remains the Edge fallback."""

    if manifest.get("espeak_used"):
        return False
    farid = manifest.get("voice") == "fa-IR-FaridNeural" and manifest.get("rate") == "+0%"
    aran = (
        manifest.get("provider") == "elevenlabs"
        and manifest.get("model") == "eleven_v4"
        and manifest.get("voice_id") == "PEdcOLzbXYhL8IKOswXB"
        and manifest.get("language_code") == "fa"
        and manifest.get("speed") == 1.0
    )
    return farid or aran


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the Persian Reel")
    parser.add_argument("--story", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--images", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--master-audio", type=Path)
    args = parser.parse_args()

    story = json.loads(args.story.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not _accepted_narration(manifest):
        fail(f"refusing to render a Reel whose manifest voice is {manifest.get('voice') or manifest.get('voice_id')}")
    if manifest.get("espeak_used"):
        fail("refusing espeak audio")
    count = len(args.images)
    if count not in (3, 4) or len(manifest.get("scenes") or []) != count or len(story.get("scenes") or []) != count:
        fail("story, voice manifest, and images must all contain three or four scenes")
    transitions = TRANSITIONS if count == 4 else ("smoothleft", "fade")

    args.work.mkdir(parents=True, exist_ok=True)
    encoder = "h264_nvenc" if nvenc_works() else "libx264"
    clip_durations = []
    video_clips = []
    audio_clips = []
    for scene in manifest["scenes"]:
        number = scene["number"]
        frames = max(1, int(round(float(scene["duration"]) * FPS)))
        seconds = frames / FPS
        clip_durations.append(seconds)
        video = args.work / f"scene-{number:02d}.mp4"
        audio = args.work / f"scene-{number:02d}.wav"
        run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(args.images[number - 1]),
                "-vf",
                (
                    "scale=1296:2304:force_original_aspect_ratio=increase,crop=1296:2304,"
                    f"zoompan={motion(number, frames)}:d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
                    "eq=contrast=1.04:saturation=0.92,vignette=PI/5,format=yuv420p"
                ),
                "-frames:v",
                str(frames),
                "-r",
                str(FPS),
                "-c:v",
                encoder,
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(video),
            ]
        )
        if args.master_audio is None:
            fit_audio(Path(scene["audio"]), seconds, audio)
            audio_clips.append(audio)
        video_clips.append(video)

    offsets = [0.0]
    for duration in clip_durations[:-1]:
        offsets.append(round(offsets[-1] + duration - TRANSITION, 3))
    xfade_offsets = []
    running = clip_durations[0]
    for duration in clip_durations[1:]:
        xfade_offsets.append(round(running - TRANSITION, 3))
        running = running + duration - TRANSITION

    video_chain = []
    current = "[0:v]"
    for index, (transition, offset) in enumerate(zip(transitions, xfade_offsets), start=1):
        nxt = f"[v{index}]" if index < count - 1 else "[vx]"
        video_chain.append(
            f"{current}[{index}:v]xfade=transition={transition}:duration={TRANSITION}:offset={offset:.3f}{nxt}"
        )
        current = nxt
    silent = args.work / "silent.mp4"
    mixed = args.work / "mixed.mp4"
    video_inputs = []
    for clip in video_clips:
        video_inputs.extend(["-i", str(clip)])
    run(
        [
            "ffmpeg",
            "-y",
            *video_inputs,
            "-filter_complex",
            ";".join(video_chain),
            "-map",
            "[vx]",
            "-c:v",
            encoder,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(FPS),
            str(silent),
        ]
    )
    narration = args.work / "narration.wav"
    if args.master_audio is not None:
        if not args.master_audio.is_file():
            fail(f"master audio is missing: {args.master_audio}")
        narration = args.master_audio
    else:
        audio_chain = []
        current_a = "[0:a]"
        for index in range(1, count):
            nxt = f"[a{index}]" if index < count - 1 else "[ax]"
            audio_chain.append(f"{current_a}[{index}:a]acrossfade=d={TRANSITION}:c1=tri:c2=tri{nxt}")
            current_a = nxt
        audio_inputs = []
        for clip in audio_clips:
            audio_inputs.extend(["-i", str(clip)])
        run(
            [
                "ffmpeg",
                "-y",
                *audio_inputs,
                "-filter_complex",
                ";".join(audio_chain),
                "-map",
                "[ax]",
                str(narration),
            ]
        )
    captions = args.work / "captions.ass"
    write_ass(story, manifest, offsets, captions)
    caption_arg = str(captions).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(silent),
            "-vf",
            f"subtitles={caption_arg}:fontsdir={str(FONTS).replace(':', '\\:')},format=yuv420p",
            "-c:v",
            encoder,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(FPS),
            "-an",
            str(args.work / "captioned.mp4"),
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(args.work / "captioned.mp4"),
            "-i",
            str(narration),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            str(args.out),
        ]
    )
    info = probe(args.out)
    report = {
        "encoder": encoder,
        "transition_seconds": TRANSITION,
        "transitions": list(transitions),
        "clip_durations": clip_durations,
        "scene_offsets": offsets,
        "xfade_offsets": xfade_offsets,
        "output": info,
        "voice": manifest.get("voice") or manifest.get("voice_id"),
        "rate": manifest.get("rate") or manifest.get("speed"),
        "font": "Vazirmatn",
        "skills": ["persian-tts", "reel-image-generation", "reel-video-design"],
    }
    (args.out.parent / "render_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "encoder": encoder, "duration": info["format"]["duration"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
