---
name: direct-news-reel
description: Decide the angle, verified facts, narrative shape, and visual job of a news Reel before any script, image, or voice is produced. Used by news-editor. Not a separate agent.
---

# News director

`news-editor` owns this. Do not add a second editorial agent. The selection database stays read-only.

The story decides the length. An existing audio file does not. A short sample must not be reused as the narration of a new report.

## Before the script

1. Read the fact pack. Name the event in one sentence.
2. Keep only verified facts. Separate outlet reports from official records.
3. Choose one factual angle. Write five candidate hooks, then keep one that is true. A hook may use curiosity, money, a familiar problem, a challenged assumption, or a real deadline. It may not hide the subject or invent a consequence.
4. For Iranians living in Germany, record an audience assessment: who in Germany is affected, the practical consequence, the source URL that supports that consequence, and why the story is worth publishing. A keyword hit is only a filter. A borderline story needs this assessment. Do not invent a Germany connection, and do not say that a provider-specific rule applies to everyone.
5. Structure a complete report: hook, who/what/where/when, the key development, why it matters, and a conclusion. End with a practical step only when a source supports one. Separate the day a rule was announced from the day it takes effect.
6. Plan a visual for each beat. Every visual must add a fact. A decorative picture is not a scene. Name one visual anchor when an object, document, or place can connect the scenes, and do not force a person into every scene.
7. Write the brief into `editorial_review.json` beside the decision, including `audience_relevance` with `affected_audience`, `practical_relevance`, `evidence_urls`, and `publication_reason`. The parent saves it. This agent does not write the database.

## Before audio

Review the script. Approve synthesis only when a new listener can follow it, every material claim has a source, the ending is a conclusion, and nothing was cut only to reuse an old recording. Return `APPROVE`, `REVISE`, or `REJECT`.

## After the Reel

Review the finished picture and the audio that was actually generated. Subtitle times must come from that audio. A technical pass is not this review.
