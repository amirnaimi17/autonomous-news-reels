"""Group articles that describe one real-world event.

Same-language pairs use fingerprints and overlap. Cross-language pairs use a
translator when one is configured. Without a translator, only a shared alias
entity plus a shared number or proper token can join them. That rule misses
paraphrases and is not reliable multilingual deduplication.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.dedup.fingerprints import (
    hamming_distance,
    jaccard,
    significant_tokens,
    simhash64,
    title_fingerprint,
)
from app.services.dedup.judge import Judgement, SemanticDuplicateJudge, UncertainJudge
from app.services.dedup.language import canonical_entities, normalized_numbers, proper_tokens
from app.services.translation.base import NoneTranslator, Translator

PIVOT_LANGUAGE = "en"


@dataclass(frozen=True)
class MatchThresholds:
    """Overlap settings copied from configuration."""

    title_jaccard: float = 0.72
    summary_jaccard: float = 0.40
    entity_jaccard: float = 0.50
    simhash_hamming: int = 8
    fail_closed: bool = True


@dataclass(frozen=True)
class ClusterText:
    """Text compared during clustering."""

    title: str
    summary: str
    language: str
    canonical_url: str = ""

    @property
    def body(self) -> str:
        return f"{self.title} {self.summary}".strip()


@dataclass
class WorkingCluster:
    """One event under construction, plus the articles already attached."""

    key: str
    state: str
    persisted: bool
    texts: list[ClusterText] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterAssignment:
    """Where one incoming article belongs."""

    article_index: int
    cluster_key: str
    is_new: bool
    relation: str


def assign_articles(
    articles: list[ClusterText],
    known: list[WorkingCluster],
    *,
    thresholds: MatchThresholds,
    aliases: dict[str, str],
    stopwords: dict[str, frozenset[str]],
    translator: Translator | None = None,
    judge: SemanticDuplicateJudge | None = None,
) -> list[ClusterAssignment]:
    """Assign each article to an existing cluster or open a new one."""

    active_translator = translator if translator is not None else NoneTranslator()
    active_judge = judge if judge is not None else UncertainJudge()
    clusters = list(known)
    assignments: list[ClusterAssignment] = []
    for index, article in enumerate(articles):
        match = _find_cluster(
            article,
            clusters,
            thresholds=thresholds,
            aliases=aliases,
            stopwords=stopwords,
            translator=active_translator,
            judge=active_judge,
        )
        if match is None:
            key = f"new:{index}"
            clusters.append(
                WorkingCluster(key=key, state="DISCOVERED", persisted=False, texts=[article])
            )
            assignments.append(ClusterAssignment(index, key, True, "primary"))
            continue
        relation = "update" if match.state != "DISCOVERED" else "duplicate"
        if not match.texts:
            relation = "primary"
        match.texts.append(article)
        assignments.append(ClusterAssignment(index, match.key, False, relation))
    return assignments


def same_story(
    left: ClusterText,
    right: ClusterText,
    *,
    thresholds: MatchThresholds,
    aliases: dict[str, str],
    stopwords: dict[str, frozenset[str]],
    translator: Translator | None = None,
    judge: SemanticDuplicateJudge | None = None,
) -> bool:
    """Return whether two texts should share an event."""

    if left.canonical_url and left.canonical_url == right.canonical_url:
        return True
    active_translator = translator if translator is not None else NoneTranslator()
    active_judge = judge if judge is not None else UncertainJudge()
    if left.language == right.language:
        return _same_language(
            left,
            right,
            thresholds=thresholds,
            stopwords=stopwords.get(left.language, frozenset()),
            judge=active_judge,
            fail_closed=thresholds.fail_closed,
        )
    pivot_left = _pivot(left, active_translator)
    pivot_right = _pivot(right, active_translator)
    if pivot_left is not None and pivot_right is not None:
        return _same_language(
            pivot_left,
            pivot_right,
            thresholds=thresholds,
            stopwords=stopwords.get(PIVOT_LANGUAGE, frozenset()),
            judge=active_judge,
            fail_closed=thresholds.fail_closed,
        )
    return _entity_and_number_match(left, right, aliases)


def _find_cluster(
    article: ClusterText,
    clusters: list[WorkingCluster],
    *,
    thresholds: MatchThresholds,
    aliases: dict[str, str],
    stopwords: dict[str, frozenset[str]],
    translator: Translator,
    judge: SemanticDuplicateJudge,
) -> WorkingCluster | None:
    for cluster in clusters:
        for existing in cluster.texts:
            if same_story(
                article,
                existing,
                thresholds=thresholds,
                aliases=aliases,
                stopwords=stopwords,
                translator=translator,
                judge=judge,
            ):
                return cluster
    return None


def _same_language(
    left: ClusterText,
    right: ClusterText,
    *,
    thresholds: MatchThresholds,
    stopwords: frozenset[str],
    judge: SemanticDuplicateJudge,
    fail_closed: bool,
) -> bool:
    stops = stopwords or None
    try:
        if title_fingerprint(left.title, stops) == title_fingerprint(right.title, stops):
            return True
    except ValueError:
        pass
    left_title = significant_tokens(left.title, stops)
    right_title = significant_tokens(right.title, stops)
    title_overlap = jaccard(left_title, right_title)
    if title_overlap >= thresholds.title_jaccard:
        return True
    summary_overlap = jaccard(significant_tokens(left.summary, stops), significant_tokens(right.summary, stops))
    entity_overlap = jaccard(proper_tokens(left.title), proper_tokens(right.title))
    if entity_overlap >= thresholds.entity_jaccard and summary_overlap >= thresholds.summary_jaccard:
        return True
    if _simhash_match(left, right, stopwords, thresholds) and title_overlap >= 0.45 and not _proper_conflict(left, right):
        return True
    gray = 0.55 <= title_overlap < thresholds.title_jaccard and not _proper_conflict(left, right)
    if not gray:
        return False
    judgement: Judgement = judge.compare(left.body, right.body)
    if judgement in {"same_event", "update"}:
        return True
    if judgement == "distinct":
        return False
    return fail_closed


def _simhash_match(
    left: ClusterText,
    right: ClusterText,
    stopwords: frozenset[str],
    thresholds: MatchThresholds,
) -> bool:
    stops = stopwords or None
    try:
        distance = hamming_distance(simhash64(left.body, stops), simhash64(right.body, stops))
    except ValueError:
        return False
    return distance <= thresholds.simhash_hamming


def _proper_conflict(left: ClusterText, right: ClusterText) -> bool:
    left_tokens = proper_tokens(f"{left.title} {left.summary}")
    right_tokens = proper_tokens(f"{right.title} {right.summary}")
    if not left_tokens or not right_tokens:
        return False
    return bool(left_tokens.symmetric_difference(right_tokens) and left_tokens != right_tokens and not left_tokens <= right_tokens and not right_tokens <= left_tokens)


def _entity_and_number_match(left: ClusterText, right: ClusterText, aliases: dict[str, str]) -> bool:
    """Narrow cross-language hint. Shared alias plus a shared number or name."""

    left_numbers = normalized_numbers(left.body)
    right_numbers = normalized_numbers(right.body)
    if left_numbers and right_numbers and left_numbers.isdisjoint(right_numbers):
        return False
    shared_entities = canonical_entities(left.body, aliases) & canonical_entities(right.body, aliases)
    if not shared_entities:
        return False
    shared_numbers = left_numbers & right_numbers
    shared_names = proper_tokens(left.body) & proper_tokens(right.body)
    return bool(shared_numbers or shared_names)


def _pivot(article: ClusterText, translator: Translator) -> ClusterText | None:
    if article.language == PIVOT_LANGUAGE:
        return article
    translated = translator.translate(article.body, article.language, PIVOT_LANGUAGE)
    if not translated:
        return None
    return ClusterText(
        title=translated,
        summary=translated,
        language=PIVOT_LANGUAGE,
        canonical_url=article.canonical_url,
    )
