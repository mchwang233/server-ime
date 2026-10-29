#!/usr/bin/env python3
"""Generate data/base/readings-v1.json from terms-v1.tsv.

This is a maintainer-only tool: normal builds and checks read the committed
readings file and do not need pypinyin or network access.

Readings are generated with pypinyin 0.55.0 (MIT) and cross-checked against the
pinned CC-CEDICT snapshot (CC BY-SA 4.0) where an entry exists.  Explicit
overrides correct context-dependent heteronyms that pypinyin's phrase table does
not resolve for these technical compounds.
"""
import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TERMS = ROOT / "data/base/terms-v1.tsv"
OUT = ROOT / "data/base/readings-v1.json"

OVERRIDES = {
    # 去重 = qu chong (deduplicate), not qu zhong.
    "去重策略": "qu'chong'ce'lve",
    # 重试 = chong shi (retry), not zhong shi.
    "重试机制": "chong'shi'ji'zhi",
}

PYPYININ = {
    "name": "pypinyin",
    "version": "0.55.0",
    "license": "MIT",
    "url": "https://files.pythonhosted.org/packages/b9/7b/4cabc76fcc21c3c7d5c671d8783984d30ac9d3bb387c4ba784fca3cdfa3a/pypinyin-0.55.0-py2.py3-none-any.whl",
    "sha256": "d53b1e8ad2cdb815fb2cb604ed3123372f5a28c6f447571244aca36fc62a286f",
}


def terms():
    rows = []
    for line in TERMS.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        domain, text, count = line.split("\t")
        rows.append((domain, text, int(count)))
    return rows


def normalize_cedict(pinyin):
    out = []
    for token in pinyin.replace("u:", "v").replace("ü", "v").lower().split():
        token = re.sub(r"[0-5]", "", token)
        if not re.fullmatch(r"[a-zv]+", token):
            return None
        out.append(token)
    return "'".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pypinyin-path", default="", help="directory that contains the pypinyin package")
    parser.add_argument("--cedict", default="", help="optional cedict_ts.u8.gz snapshot for cross-checking")
    args = parser.parse_args()
    if args.pypinyin_path:
        sys.path.insert(0, args.pypinyin_path)
    try:
        from pypinyin import Style, pinyin
        import pypinyin as module
    except ImportError:
        sys.exit("pypinyin is required to regenerate readings; pass --pypinyin-path or install pypinyin==0.55.0")
    if module.__version__ != PYPYININ["version"]:
        sys.exit(f"pypinyin {module.__version__} differs from pinned {PYPYININ['version']}")

    cedict = {}
    snapshot = None
    if args.cedict:
        digest = hashlib.sha256(Path(args.cedict).read_bytes()).hexdigest()
        snapshot = {"sha256": digest, "url": "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"}
        with gzip.open(args.cedict, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("#"):
                    if line.startswith("#! date="):
                        snapshot["date"] = line.strip().split("=", 1)[1]
                    continue
                match = re.match(r"^(\S+) (\S+) \[([^\]]+)\] /", line)
                if match:
                    cedict.setdefault(match.group(2), []).append(match.group(3))

    readings, errors, checked, mismatches = {}, [], 0, []
    for domain, text, count in terms():
        generated = pinyin(text, style=Style.NORMAL, heteronym=False, errors="default")
        syllables = [item[0] for item in generated]
        if len(syllables) != len(text) or any(not re.fullmatch(r"[a-zv]+", item) for item in syllables):
            errors.append({"text": text, "generated": syllables})
            continue
        reading = "'".join(syllables)
        if text in OVERRIDES:
            reading = OVERRIDES[text]
        readings[text] = reading
        candidates = [normalize_cedict(item) for item in cedict.get(text, [])]
        candidates = [item for item in candidates if item and len(item.split("'")) == len(text)]
        if candidates:
            checked += 1
            if reading not in candidates:
                mismatches.append({"text": text, "reading": reading, "cedict": candidates})
    if errors or mismatches:
        print(json.dumps({"errors": errors, "mismatches": mismatches}, ensure_ascii=False, indent=1))
        sys.exit("readings rejected: fix pinyin overrides before writing")
    payload = {
        "schema": "ime-lexicon-readings/1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "generator": PYPYININ,
        "overrides": OVERRIDES,
        "readings": dict(sorted(readings.items())),
        "verification": {
            "cedict_snapshot": snapshot,
            "cross_checked_entries": checked,
            "mismatches": 0,
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "entries": len(readings), "cross_checked": checked}, ensure_ascii=False))


if __name__ == "__main__":
    main()
