# Deduplication and selection

Discovery groups articles into events, scores the open events, and fills the remaining ranks for the local day. It does not reserve a production slot.

## Same language

Stopwords come from `STOPWORDS_DIR/<language>.json`. A missing file for a language uses an empty list, so English stopwords are not applied to German. The default English list inside the fingerprint helpers is used only when the caller does not pass a list. Phase 1 tests use that default.

Two texts match when any of these is true:

- Their canonical URLs are equal.
- Their title fingerprints are equal. The fingerprint hashes the sorted significant tokens, so word order alone does not create a new event.
- Title Jaccard is at least 0.72.
- Proper-name Jaccard is at least 0.50 and summary Jaccard is at least 0.40.
- SimHash Hamming distance is at most 8, title Jaccard is at least 0.45, and the proper names do not conflict.

A title Jaccard from 0.55 up to the duplicate threshold, with no conflicting proper names, is a gray zone. The shipped judge returns `uncertain`. `FAIL_CLOSED_DEDUPLICATION=true` treats that gray zone as the same event. Conflicting names such as France and Germany are not a gray zone, so fail-closed does not merge them.

## More than one language

`TRANSLATION_PROVIDER` accepts only `none`. `NoneTranslator.translate` returns nothing.

Without a translation, a cross-language pair matches only when all of this is true:

- Both texts contain the same canonical entity from `ENTITY_ALIASES_FILE`.
- They share a normalized number, or they share an identical proper token.
- If both sides contain numbers and those sets do not overlap, they do not match. `4,5` and `4.5` are the same number.

A missing alias file means there are no aliases, so this hint never fires. A paraphrase that does not share a number or the same proper token stays two events. The English sentence “The European Central Bank left policy unchanged” and the German sentence “Die Europäische Zentralbank lässt die Zinsen unverändert” stay separate even when the alias catalog maps both bank names to `ecb`.

“ECB holds rates at 4.5 percent” and “EZB belässt Leitzins bei 4,5 Prozent” match only because the alias catalog and the shared rate are both present. That is an entity-and-number hint. It is not reliable multilingual deduplication.

`Translator` is the port for a later provider:

```text
translate(text, source_language, pivot_language) -> str | None
```

The pivot language is English. When both sides produce pivot text, the same-language rules above run on that text, including fail-closed for a gray zone. `DictionaryTranslator` is a test double. It is not a network client and it is not selected by configuration.

## Scoring

`score = 0.50 * recency + 0.30 * sources + 0.20 * impact`

- Recency uses the client timezone’s calendar date: today 1.0, yesterday 0.8, older 0.5.
- Sources, counted by distinct source name: 1 → 0.45, 2 → 0.75, 3 or more → 1.0.
- Impact is 1 only when the text contains a term from a small fixed vocabulary, including election, court, central bank, sanctions, parliament, and earthquake. Feed URLs are not impact.

Opinion packaging is a URL path containing `/opinion`, `/comment`, `/editorial`, or `/kommentar`, or a title prefix `Opinion:`, `Editorial:`, `Kommentar:`, or `Meinung:`. Those events score 0 and are not selected.

Today and yesterday must reach `MIN_IMPORTANCE_SCORE` (0.55). An older story inside the 72-hour window must reach `OLDER_WINDOW_MIN_IMPORTANCE` (0.75). An older story with three sources and an impact term scores 0.75. An older story with one source and an impact term scores 0.585 and is not selected.

Eligible events are ordered by band (today, yesterday, older), then score, then source count, then event id.

## What stays unfinished

- No live translation provider.
- No embedding comparison.
- The impact vocabulary is small and will miss important stories that do not use those words.
- Alias coverage is only what the operator puts in the alias file.
- `discover` does not render video, reserve slots, or notify the owner.
