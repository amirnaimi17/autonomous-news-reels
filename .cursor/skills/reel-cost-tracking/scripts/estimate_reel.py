#!/usr/bin/env python3
"""Price one Reel plan and refuse it when the estimate is incomplete or over target."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from costing import estimate_plan, gate, load_budget, load_pricing, month_spend, record  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate a Reel and apply the budget gate")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--month", required=True)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    pricing = load_pricing()
    budget = load_budget()
    estimate = estimate_plan(plan, pricing, budget)
    spent, uncertain = month_spend(args.ledger, args.month)
    decision = gate(estimate, budget, spent_usd=spent)
    decision["month_has_non_actual_rows"] = uncertain
    payload = {"estimate": estimate, "decision": decision}
    if args.record:
        record(
            args.ledger,
            {
                "reel_id": plan["reel_id"],
                "usd": estimate["estimated_usd"],
                "cost_kind": "estimate" if decision["allowed"] else "rejected",
                "allowed": decision["allowed"],
                "reasons": decision["reasons"],
            },
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not decision["allowed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
