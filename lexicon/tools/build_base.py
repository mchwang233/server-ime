#!/usr/bin/env python3
"""Build the traceable base lexicon enhancement data from its two source files.

Input : data/base/terms-v1.tsv      (authored terms, domain, weight)
        data/base/readings-v1.json  (pinned pypinyin readings + overrides)
Output: data/base/lexicon-v1.jsonl  (one immutable base-v1 entry per line)
        data/base/manifest.json     (counts, hashes, sources, licences)

The output contains no evaluation answers.  If the frozen corpus exists, the
build fails when an entry text or reading exactly equals a corpus case.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from lexicon.errors import LexiconError
from lexicon.records import (  # noqa: E402
    SCHEMA_BASE, canonical_bytes, new_entry, read_json, sha256_bytes, sha256_file,
    utcnow, validate_entry, write_json_atomic, write_jsonl_atomic,
)

TERMS = ROOT / "data/base/terms-v1.tsv"
READINGS = ROOT / "data/base/readings-v1.json"
CORPUS = ROOT / "corpus/eval/cases-v1.jsonl"
LEXICON = ROOT / "data/base/lexicon-v1.jsonl"
MANIFEST = ROOT / "data/base/manifest.json"
LICENSE = "CC-BY-4.0"


def load_terms(path):
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise LexiconError("invalid_record", f"terms line {number}: expected 3 tab-separated fields")
        domain, text, count = fields
        if text in {row["text"] for row in rows}:
            raise LexiconError("duplicate_entry", f"duplicate term {text!r} on line {number}")
        rows.append({"domain": domain, "text": text, "count": int(count)})
    return rows


def corpus_guard(entries, corpus):
    if not corpus.is_file():
        return {"checked": False, "overlap": 0}
    texts, pinyins = set(), set()
    for line in corpus.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        texts.add(case.get("expected"))
        pinyins.add(case.get("input"))
    overlap = [
        {"text": entry["text"], "pinyin": entry["pinyin"]}
        for entry in entries
        if entry["text"] in texts or entry["pinyin"] in pinyins
    ]
    if overlap:
        raise LexiconError(
            "contamination",
            "base lexicon shares an exact answer or reading with the frozen evaluation corpus",
            {"overlap": overlap[:20]},
        )
    return {"checked": True, "overlap": 0}


def build():
    terms = load_terms(TERMS)
    readings = read_json(READINGS)
    if readings.get("schema") != "ime-lexicon-readings/1":
        raise LexiconError("incompatible_version", f"unexpected readings schema {readings.get('schema')!r}")
    table = readings["readings"]
    missing = sorted({row["text"] for row in terms} - set(table))
    unused = sorted(set(table) - {row["text"] for row in terms})
    if missing or unused:
        raise LexiconError("invalid_record", "readings and terms disagree", {"missing": missing[:20], "unused": unused[:20]})

    entries = []
    for row in terms:
        entry = new_entry(
            row["text"], table[row["text"]], row["count"], "base",
            source="server-ime-curation-v1",
            license=LICENSE,
            domain=row["domain"],
            reading_source="pypinyin-0.55.0",
        )
        validate_entry(entry, require_source=True, kinds=("base",))
        entries.append(entry)
    guard = corpus_guard(entries, CORPUS)
    return entries, guard


def manifest_for(entries, guard):
    terms_sha = sha256_file(TERMS)
    readings = read_json(READINGS)
    return {
        "schema": SCHEMA_BASE,
        "name": "server-ime base lexicon enhancement",
        "lexicon_version": "base-v1",
        "created_at": utcnow(),
        "entry_count": len(entries),
        "domains": dict(sorted(Counter(entry["domain"] for entry in entries).items())),
        "count_range": [min(entry["count"] for entry in entries), max(entry["count"] for entry in entries)],
        "license": LICENSE,
        "license_note": (
            "The authored term selection and generated readings in this file are released under "
            "CC BY 4.0. The readings were generated with pypinyin 0.55.0 (MIT) and spot-checked "
            "against a CC-CEDICT snapshot (CC BY-SA 4.0) as a verification reference only; no "
            "CC-CEDICT definitions are copied. The engine's own model data stays under its "
            "upstream licence (libpinyin-data, GPL-3.0-or-later) and is not redistributed here."
        ),
        "sources": [
            {
                "id": "curated-terms-v1",
                "kind": "authored term list",
                "file": "data/base/terms-v1.tsv",
                "sha256": terms_sha,
                "license": LICENSE,
            },
            {
                "id": "readings-v1",
                "kind": "generated pinyin readings",
                "file": "data/base/readings-v1.json",
                "sha256": sha256_file(READINGS),
                "license": LICENSE,
                "generator": readings["generator"],
                "overrides": readings.get("overrides", {}),
                "verification": readings.get("verification", {}),
            },
        ],
        "build": {
            "tool": "lexicon/tools/build_base.py",
            "command": "python3 lexicon/tools/build_base.py",
            "deterministic": True,
        },
        "validation": {
            "text": "CJK only, 1-16 characters",
            "pinyin": "lowercase ASCII, v for ü, one syllable per character",
            "duplicate_text": 0,
            "corpus": guard,
        },
        "files": {
            "lexicon-v1.jsonl": {
                "sha256": sha256_bytes(canonical_rows(entries)),
                "bytes": len(canonical_rows(entries)),
            }
        },
    }


def canonical_rows(entries):
    return "".join(
        json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries
    ).encode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the committed data differs from a rebuild")
    args = parser.parse_args()
    try:
        entries, guard = build()
        payload = canonical_rows(entries)
        if args.check:
            if not LEXICON.is_file():
                raise LexiconError("invalid_record", f"missing {LEXICON}")
            current = LEXICON.read_bytes()
            print(json.dumps({
                "ok": current == payload,
                "entries": len(entries),
                "committed_sha256": sha256_bytes(current),
                "rebuilt_sha256": sha256_bytes(payload),
                "corpus": guard,
            }, ensure_ascii=False))
            return 0 if current == payload else 1
        LEXICON.parent.mkdir(parents=True, exist_ok=True)
        with open(LEXICON, "wb") as handle:
            handle.write(payload)
        manifest = manifest_for(entries, guard)
        manifest["files"]["lexicon-v1.jsonl"]["sha256"] = sha256_bytes(payload)
        manifest["files"]["lexicon-v1.jsonl"]["bytes"] = len(payload)
        write_json_atomic(MANIFEST, manifest)
        print(json.dumps({
            "ok": True,
            "lexicon": str(LEXICON),
            "manifest": str(MANIFEST),
            "entries": len(entries),
            "sha256": sha256_bytes(payload),
            "domains": manifest["domains"],
            "corpus": guard,
        }, ensure_ascii=False))
        return 0
    except LexiconError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
