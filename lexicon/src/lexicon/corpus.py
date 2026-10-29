"""Frozen evaluation corpus loading, contamination checks and scoring.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import json
import re
from collections import Counter
from pathlib import Path

from . import engine as engine_bridge
from .errors import LexiconError
from .records import SCHEMA_CORPUS, read_jsonl, sha256_file, utcnow

CATEGORIES = ("common", "sentence", "ambiguity", "long", "mixed", "typo")
SCORING = "ime-eval-score/1"
INPUT_RE = re.compile(r"[a-z']+\Z")
MIXED_INPUT_RE = re.compile(r"[a-z0-9@._-]+\Z")


def load_cases(path):
    path = Path(path)
    rows = read_jsonl(path, code="invalid_json")
    cases, ids = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise LexiconError("invalid_record", f"case {index} is not an object")
        for field in ("id", "category", "input", "expected"):
            if field not in row:
                raise LexiconError("invalid_record", f"case {index} is missing {field}")
        case_id = row["id"]
        if not isinstance(case_id, str) or not re.fullmatch(r"[A-Z]\d{3}\Z", case_id):
            raise LexiconError("invalid_record", f"case {index} has an invalid id {case_id!r}")
        if case_id in ids:
            raise LexiconError("invalid_record", f"duplicate case id {case_id}")
        ids.add(case_id)
        if row["category"] not in CATEGORIES:
            raise LexiconError("invalid_record", f"case {case_id} has an unknown category")
        input_text = str(row["input"])
        allowed = MIXED_INPUT_RE if row["category"] == "mixed" else INPUT_RE
        if not allowed.fullmatch(input_text):
            raise LexiconError("invalid_record", f"case {case_id} input is not lower-case pinyin")
        expected = str(row["expected"])
        if not expected or len(expected) > 80:
            raise LexiconError("invalid_record", f"case {case_id} has an invalid expected text")
        cases.append({
            "id": case_id,
            "category": row["category"],
            "input": input_text,
            "expected": expected,
            "tags": list(row.get("tags") or []),
            "note": str(row.get("note") or ""),
        })
    if len(cases) < 200:
        raise LexiconError("invalid_corpus", f"corpus has {len(cases)} cases, at least 200 are required")
    return cases


def corpus_digest(path):
    path = Path(path)
    return {"file": str(path), "sha256": sha256_file(path), "cases": len(load_cases(path))}


def contamination(base_entries, cases):
    texts = {entry["text"] for entry in base_entries}
    readings = {entry["pinyin"] for entry in base_entries}
    hits = []
    for case in cases:
        reasons = []
        if case["expected"] in texts:
            reasons.append("expected text is a base lexicon entry")
        if case["input"] in readings:
            reasons.append("input reading is a base lexicon entry reading")
        if reasons:
            hits.append({"id": case["id"], "reasons": reasons})
    return {"ok": not hits, "hits": hits}


def levenshtein(left, right):
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (char != other)))
        previous = current
    return previous[-1]


def _summary(rows):
    total = len(rows)
    top1 = sum(row["top1"] for row in rows)
    top5 = sum(row["top5"] for row in rows)
    errors = sum(row["status"] == "error" for row in rows)
    cer = sum(row["cer"] for row in rows) / total if total else 0.0
    return {
        "cases": total,
        "top1": top1,
        "top5": top5,
        "errors": errors,
        "top1_rate": round(top1 / total, 4) if total else 0.0,
        "top5_rate": round(top5 / total, 4) if total else 0.0,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "mean_cer": round(cer, 4),
    }


def run(cases, *, user_dir=None, data_dir=None, runtime_dir=None, corpus_path=None):
    """Score a configuration without writing learning data or training."""
    engine = engine_bridge.open_engine(user_dir=user_dir, data_dir=data_dir, runtime_dir=runtime_dir)
    rows = []
    try:
        session = engine.create_session(config={"page_size": 5})
        for case in cases:
            try:
                state = session.set_input(case["input"])
                texts = [item["text"] for item in state["candidates"]["items"]]
                status, error = "ok", None
            except Exception as exc:  # engine errors are part of the measurement
                texts, status, error = [], "error", getattr(exc, "code", type(exc).__name__)
            top1 = bool(texts) and texts[0] == case["expected"]
            top5 = case["expected"] in texts[:5]
            distance = levenshtein(texts[0], case["expected"]) if texts else len(case["expected"])
            length = max(len(texts[0]), len(case["expected"])) if texts else len(case["expected"])
            rows.append({
                "id": case["id"],
                "category": case["category"],
                "input": case["input"],
                "expected": case["expected"],
                "top": texts[:5],
                "status": status,
                "error": error,
                "top1": top1,
                "top5": top5,
                "cer": round(distance / length, 4) if length else 0.0,
            })
        session.close()
    finally:
        engine.close()
    categories = {}
    for name in CATEGORIES:
        subset = [row for row in rows if row["category"] == name]
        if subset:
            categories[name] = _summary(subset)
    return {
        "schema": "ime-eval-result/1",
        "scoring": SCORING,
        "generated_at": utcnow(),
        "corpus": {
            "file": str(corpus_path) if corpus_path else None,
            "sha256": sha256_file(corpus_path) if corpus_path else None,
            "cases": len(cases),
            "categories": dict(Counter(case["category"] for case in cases)),
        },
        "configuration": {
            "user_dir": str(user_dir) if user_dir else None,
            "data_dir": str(engine_bridge.engine_paths(data_dir, runtime_dir)[1]),
            "learning": False,
            "training": False,
            "page_size": 5,
        },
        "engine": getattr(engine, "lexicon_bridge", {}),
        "overall": _summary(rows),
        "categories": categories,
        "rows": rows,
    }


def compare(baseline, enhanced):
    """Per-category deltas; positive is better for rates, negative for CER."""
    result = {}
    for name in sorted(set(baseline["categories"]) | set(enhanced["categories"])):
        left = baseline["categories"].get(name) or _summary([])
        right = enhanced["categories"].get(name) or _summary([])
        result[name] = {
            "top1_delta": round(right["top1_rate"] - left["top1_rate"], 4),
            "top5_delta": round(right["top5_rate"] - left["top5_rate"], 4),
            "cer_delta": round(right["mean_cer"] - left["mean_cer"], 4),
            "errors_delta": right["errors"] - left["errors"],
        }
    return {
        "overall": {
            "top1_delta": round(enhanced["overall"]["top1_rate"] - baseline["overall"]["top1_rate"], 4),
            "top5_delta": round(enhanced["overall"]["top5_rate"] - baseline["overall"]["top5_rate"], 4),
            "cer_delta": round(enhanced["overall"]["mean_cer"] - baseline["overall"]["mean_cer"], 4),
            "errors_delta": enhanced["overall"]["errors"] - baseline["overall"]["errors"],
        },
        "categories": result,
    }


def write_result(result, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
