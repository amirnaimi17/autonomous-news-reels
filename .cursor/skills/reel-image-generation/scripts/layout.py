"""Pick a visual treatment before any image call."""

from __future__ import annotations


def choose_treatment(narration: str, *, allow_one_hero: bool = False) -> dict:
    """Results and explainers use type and charts. A hero image is optional and never four calls."""

    data_story = any(token in narration for token in ("درصد", "%", "کرسی", "نوامبر"))
    return {
        "treatment": "data-graphic" if data_story else "typographic",
        "generated_images": 1 if allow_one_hero else 0,
        "charts": 2 if data_story else 0,
        "reusable_backgrounds": 1,
        "licensed_photographs": 0,
        "present_ai_as_photograph": False,
        "reason": "Spend image calls only on a scene that type and a chart cannot carry. Licensed news photography can be added as a local file; none is configured.",
    }
