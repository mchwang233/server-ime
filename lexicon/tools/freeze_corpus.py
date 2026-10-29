#!/usr/bin/env python3
"""Validate and freeze the evaluation corpus; refuse silent edits after freeze."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from lexicon.corpus import CATEGORIES, SCORING, contamination, load_cases  # noqa: E402
from lexicon.errors import LexiconError  # noqa: E402
from lexicon.records import (  # noqa: E402
    SCHEMA_CORPUS, read_jsonl, sha256_file, utcnow, validate_entry, write_json_atomic,
)

CASES = ROOT / "corpus/eval/cases-v1.jsonl"
MANIFEST = ROOT / "corpus/eval/manifest.json"
BASE = ROOT / "data/base/lexicon-v1.jsonl"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-freeze even if the hash changed")
    args = parser.parse_args()
    try:
        cases = load_cases(CASES)
        entries = [validate_entry(row, require_source=True, kinds=("base",)) for row in read_jsonl(BASE)]
        guard = contamination(entries, cases)
        if not guard["ok"]:
            raise LexiconError("contamination", "evaluation answers appear in the base lexicon", guard)
        digest = sha256_file(CASES)
        previous = None
        if MANIFEST.is_file():
            previous = json.loads(MANIFEST.read_text(encoding="utf-8"))
            if previous.get("sha256") != digest and not args.force:
                raise LexiconError(
                    "corpus_frozen",
                    "corpus content changed after it was frozen; create a new version instead of editing",
                    {"frozen_sha256": previous.get("sha256"), "new_sha256": digest},
                )
        categories = Counter(case["category"] for case in cases)
        manifest = {
            "schema": SCHEMA_CORPUS,
            "name": "server-ime fixed quality corpus",
            "version": "1.0",
            "frozen": True,
            "created_at": (previous or {}).get("created_at") or utcnow(),
            "frozen_at": utcnow(),
            "file": "cases-v1.jsonl",
            "sha256": digest,
            "cases": len(cases),
            "categories": {name: categories.get(name, 0) for name in CATEGORIES},
            "scoring": {
                "id": SCORING,
                "metrics": ["top1_exact", "top5_exact", "mean_character_error_rate"],
                "denominator": "all cases, including cases where the engine rejects the input",
                "normalization": "none; candidate and reference strings are compared exactly",
                "top5": "expected text appears among the first five candidates",
                "cer": "Levenshtein(top1, expected) / max(len(top1), len(expected)); whole expected length when no candidate exists",
                "unsupported": "category 'mixed' needs Latin/digit pass-through, and 'typo' needs correction; both are scored, never skipped",
            },
            "provenance": "Authored for this project as independent reference answers. They were not used to build data/base/lexicon-v1.jsonl.",
            "license": "CC0-1.0",
            "contamination": guard,
        }
        write_json_atomic(MANIFEST, manifest)
        print(json.dumps({
            "ok": True,
            "corpus": str(CASES),
            "manifest": str(MANIFEST),
            "sha256": digest,
            "cases": len(cases),
            "categories": manifest["categories"],
            "contamination": guard,
        }, ensure_ascii=False))
        return 0
    except LexiconError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
