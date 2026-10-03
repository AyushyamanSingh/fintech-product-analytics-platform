"""Command-line entry point for the AI analyst.

    python -m ai_analyst.cli facts                      # print the fact sheet the model is allowed to use
    python -m ai_analyst.cli summary [--offline]        # weekly executive summary -> outputs/ai/
    python -m ai_analyst.cli ask "question" [--offline] # grounded natural-language Q&A
"""
from __future__ import annotations

import argparse
import json
import sys

from ai_analyst.fact_sheet import build_fact_sheet, facts_for_prompt
from ai_analyst.llm import LLMUnavailable
from ai_analyst.qa import ask
from ai_analyst.summarizer import generate_summary
from python.config import get_settings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Grounded AI analyst (synthetic data).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("facts")
    s = sub.add_parser("summary")
    s.add_argument("--offline", action="store_true")
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--offline", action="store_true")
    args = p.parse_args(argv)
    settings = get_settings()

    if args.cmd == "facts":
        print(facts_for_prompt(build_fact_sheet(settings)))
        return 0
    if args.cmd == "summary":
        res = generate_summary(settings, offline=args.offline)
        print("mode=%s grounded=%s -> %s" % (res["mode"], res["validation"]["grounded"], res["path"]))
        if res.get("note"):
            print(res["note"])
        return 0 if res["validation"]["grounded"] else 1
    try:
        res = ask(args.question, settings, offline=args.offline)
    except LLMUnavailable as exc:
        print("Claude unavailable (%s); falling back to offline KPI answers." % exc, file=sys.stderr)
        res = ask(args.question, settings, offline=True)
    print(res["answer"]["answer"])
    for c in res["answer"].get("caveats", []):
        print("  caveat:", c)
    for qid, q in res.get("queries", {}).items():
        print("\n[%s] %s\n%s" % (qid, q["purpose"], q["sql"]))
    v = res["validation"]
    print("\nnumeric grounding: %s (%d numbers checked%s)" % (
        "PASSED" if v["grounded"] else "FAILED", v["numbers_checked"],
        "; ungrounded: " + ", ".join(v["ungrounded_numbers"]) if v.get("ungrounded_numbers") else ""))
    return 0 if v["grounded"] else 1


if __name__ == "__main__":
    sys.exit(main())
