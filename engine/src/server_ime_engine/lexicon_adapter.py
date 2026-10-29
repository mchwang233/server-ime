"""Consume the lexicon employee's formats and sole-writer UserStore API.

No learning data is written by this module. The editable project uses the
sibling component; standalone bundles carry its unmodified source and notices.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
source = ROOT.parent / "lexicon/src"
if source.is_dir() and str(source) not in sys.path:
    sys.path.insert(0, str(source))
from lexicon.store import UserStore

from lexicon.errors import LexiconError
from lexicon.service import load_base, merged_entries
from lexicon.records import validate_entry, check_reading, new_entry, MAX_ENTRIES


def default_base():
    bundled = ROOT / "data/lexicon/lexicon-v1.jsonl"
    return bundled if bundled.is_file() else ROOT.parent / "lexicon/data/base/lexicon-v1.jsonl"


def base_entries(path):
    if path is False:
        return [], {"entry_count": 0, "enabled": False}
    path = Path(path) if path else default_base()
    return load_base(path, path.parent / "manifest.json")


def validate_import(entries):
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise LexiconError("invalid_record", "entries must be an array of at most 20000 lexicon records")
    rows = [validate_entry(row, require_source=True, kinds=("base",)) for row in entries]
    if any(len(row["text"]) >= 16 for row in rows):
        raise LexiconError("invalid_record", "native domain entries are limited to 15 characters")
    return merged_entries(rows, [])
