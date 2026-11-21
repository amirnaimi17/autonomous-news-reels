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

`score = 0.40 * audience tier + 0.25 * recency + 0.20 * sources + 0.15 * source class`

- A clear household or government-and-everyday match is tier A (1.0) or B (0.8) and can be ranked. A Germany place-name, or a world story that also names a transfer or an account, is tier C (0.6). Tier C stays unselected until an editor approves it with a source URL already on the story. No match is unselected. The keyword list is only this filter. The existing `story_class` check is unchanged, so this gate is stored in `importance_breakdown_json` as `audience_filter`.
- Recency uses the client timezone’s calendar date: today 1.0, yesterday 0.8, older 0.5.
- Sources, counted by distinct source name: 1 → 0.45, 2 → 0.75, 3 or more → 1.0.
- Source class uses the best URL on the event. Government and regulatory hosts, including `bund.de`, are primary (1.0). Independent newsrooms such as Tagesschau and Deutschlandfunk are reputable (0.7) and are not treated as government. Every other host is secondary (0.35).
- The old impact vocabulary still marks a `breaking` label. It no longer adds score and it cannot admit a story by itself.

Opinion packaging is a URL path containing `/opinion`, `/comment`, `/editorial`, or `/kommentar`, or a title prefix `Opinion:`, `Editorial:`, `Kommentar:`, or `Meinung:`. Those events score 0 and are not selected.

Today and yesterday must reach `MIN_IMPORTANCE_SCORE` (0.55). An older story inside the 72-hour window must reach `OLDER_WINDOW_MIN_IMPORTANCE` (0.75). Stored selection rows are not rewritten by this formula.

Eligible events are ordered by audience tier, then band (today, yesterday, older), then score, then source count, then event id. A row saved before this formula has no tier and keeps the band order against other untagged rows.

## What stays unfinished

- No live translation provider.
- No embedding comparison.
- The audience list is a filter. A useful story written without those words stays out until an editor approves the borderline case with a source.
- Alias coverage is only what the operator puts in the alias file.
- `discover` does not render video, reserve slots, or notify the owner.
