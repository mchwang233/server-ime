"""JSON-first command line for lexicon data and personal word management.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import argparse
import json
import sys
from pathlib import Path

from . import corpus as corpus_mod
from . import engine as engine_bridge
from . import service, transfer
from .errors import LexiconError
from .records import read_json, sha256_file
from .store import UserStore, default_data_dir

REPO = Path(__file__).resolve().parents[3]
BASE = REPO / "lexicon/data/base/lexicon-v1.jsonl"
BASE_MANIFEST = REPO / "lexicon/data/base/manifest.json"
CORPUS = REPO / "lexicon/corpus/eval/cases-v1.jsonl"
CORPUS_MANIFEST = REPO / "lexicon/corpus/eval/manifest.json"

EXIT = {
    "invalid_argument": 2, "invalid_record": 2, "invalid_text": 2, "invalid_pinyin": 2,
    "pinyin_length_mismatch": 2, "unknown_operation": 2,
    "store_locked": 4,
    "incompatible_version": 5, "checksum_mismatch": 5, "store_corrupt": 5,
    "invalid_format": 5, "invalid_json": 5, "corpus_frozen": 5, "contamination": 5,
    "native_unavailable": 6, "native_build_failed": 6, "engine_unavailable": 6,
    "engine_incompatible": 6, "user_data_missing": 6, "invalid_base": 6,
    "store_missing": 3, "unknown_backup": 3, "limit_exceeded": 3,
}


def emit(payload, code=0):
    print(json.dumps(payload, ensure_ascii=False, sort_keys=False))
    return code


def fail(exc):
    return emit(exc.to_dict(), EXIT.get(exc.code, 1))


def store_from(args, create=False):
    return UserStore(args.data_dir or default_data_dir(), create=create, base_manifest=BASE_MANIFEST)


def build_parser():
    parser = argparse.ArgumentParser(prog="lexicon", description="server-ime lexicon data and user word manager")
    parser.add_argument("--data-dir", default=None, help="personal data directory; defaults to $XDG_DATA_HOME/server-ime/lexicon")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create a personal data store")
    sub.add_parser("status", help="show schema, counts, learning switch and native table")
    sub.add_parser("verify", help="verify personal data and native table integrity")
    repair = sub.add_parser("repair", help="recompute counts and hashes")
    repair.add_argument("--yes", action="store_true")

    learning = sub.add_parser("learning", help="read or change the learning switch")
    learning_sub = learning.add_subparsers(dest="action", required=True)
    learning_sub.add_parser("status")
    for name in ("on", "off"):
        item = learning_sub.add_parser(name)
        item.add_argument("--reason", default="")
        item.add_argument("--actor", default="user")

    learn = sub.add_parser("learn", help="record one eligible candidate commit")
    learn.add_argument("text")
    learn.add_argument("pinyin")
    learn.add_argument("--event-id", default=None)
    learn.add_argument("--source", default="commit")
    learn.add_argument("--purpose", default="text")
    learn.add_argument("--private", action="store_true")
    learn.add_argument("--not-eligible", action="store_true")

    phrase = sub.add_parser("phrase", help="manage custom phrases")
    phrase_sub = phrase.add_subparsers(dest="action", required=True)
    add = phrase_sub.add_parser("add")
    add.add_argument("text")
    add.add_argument("pinyin")
    add.add_argument("--count", type=int, default=50)
    remove = phrase_sub.add_parser("remove")
    remove.add_argument("text", nargs="?")
    remove.add_argument("--pinyin", default=None)
    remove.add_argument("--all", action="store_true")
    phrase_sub.add_parser("list")

    words = sub.add_parser("words", help="list personal entries")
    words.add_argument("--kind", choices=("learned", "custom"), default=None)
    words.add_argument("--query", default=None)
    words.add_argument("--limit", type=int, default=100)
    words.add_argument("--offset", type=int, default=0)

    export = sub.add_parser("export", help="write a portable user bundle")
    export.add_argument("--out", required=True)

    imp = sub.add_parser("import", help="load a bundle or a pre-1.0 word list")
    imp.add_argument("file")
    imp.add_argument("--mode", choices=("merge", "replace"), default="merge")
    imp.add_argument("--dry-run", action="store_true")

    backup = sub.add_parser("backup", help="snapshot personal data")
    backup.add_argument("--label", default="manual")
    backup.add_argument("--note", default="")
    backups = sub.add_parser("backups", help="list, restore or prune backups")
    backups_sub = backups.add_subparsers(dest="action", required=True)
    backups_sub.add_parser("list")
    restore = backups_sub.add_parser("restore")
    restore.add_argument("backup_id")
    restore.add_argument("--rebuild", action="store_true")
    prune = backups_sub.add_parser("prune")
    prune.add_argument("--keep", type=int, default=10)

    native = sub.add_parser("native", help="build or inspect the derived libpinyin user table")
    native_sub = native.add_subparsers(dest="action", required=True)
    build = native_sub.add_parser("build")
    build.add_argument("--base", default=str(BASE))
    build.add_argument("--base-manifest", default=str(BASE_MANIFEST))
    build.add_argument("--runtime-dir", default=None)
    build.add_argument("--system-data", default=None)
    build.add_argument("--probe", type=int, default=0)
    list_native = native_sub.add_parser("list")
    list_native.add_argument("--runtime-dir", default=None)
    list_native.add_argument("--system-data", default=None)

    probe = sub.add_parser("engine-probe", help="show candidates from the engine with this user table")
    probe.add_argument("pinyin")
    probe.add_argument("--page-size", type=int, default=10)
    probe.add_argument("--base-model", action="store_true", help="skip the personal native table")

    evaluate = sub.add_parser("eval", help="score the frozen corpus")
    evaluate.add_argument("--corpus", default=str(CORPUS))
    evaluate.add_argument("--manifest", default=str(CORPUS_MANIFEST))
    evaluate.add_argument("--out", required=True)
    evaluate.add_argument("--with-native", action="store_true")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            store = store_from(args, create=True)
            return emit(store.status())
        if args.command == "status":
            return emit(store_from(args).status())
        if args.command == "verify":
            result = store_from(args).verify()
            return emit(result, 0 if result["ok"] else 5)
        if args.command == "repair":
            return emit(store_from(args).repair(apply=args.yes))
        if args.command == "learning":
            store = store_from(args)
            if args.action == "status":
                return emit({"ok": True, "learning": store.status()["learning"], "revision": store.meta["revision"]})
            return emit(store.set_learning(args.action == "on", reason=args.reason, actor=args.actor))
        if args.command == "learn":
            return emit(store_from(args).record_commit(
                args.text, args.pinyin, source=args.source, event_id=args.event_id,
                learning_eligible=not args.not_eligible, private=args.private, purpose=args.purpose))
        if args.command == "phrase":
            store = store_from(args)
            if args.action == "add":
                return emit(store.add_phrase(args.text, args.pinyin, args.count))
            if args.action == "remove":
                return emit(store.remove_phrase(args.text, args.pinyin, all_entries=args.all))
            return emit(store.list_words(kind="custom", limit=1000))
        if args.command == "words":
            return emit(store_from(args).list_words(kind=args.kind, query=args.query,
                                                   limit=args.limit, offset=args.offset))
        if args.command == "export":
            return emit(transfer.export_bundle(store_from(args), args.out))
        if args.command == "import":
            return emit(transfer.import_bundle(store_from(args), args.file, mode=args.mode, dry_run=args.dry_run))
        if args.command == "backup":
            return emit(transfer.make_backup(store_from(args), label=args.label, note=args.note))
        if args.command == "backups":
            store = store_from(args)
            if args.action == "list":
                return emit(transfer.list_backups(store))
            if args.action == "prune":
                return emit(transfer.prune_backups(store, keep=args.keep))
            result = transfer.restore_backup(store, args.backup_id)
            if args.rebuild:
                result["native"] = service.rebuild_native(
                    store, BASE, base_manifest=BASE_MANIFEST)
            return emit(result)
        if args.command == "native":
            store = store_from(args)
            if args.action == "build":
                return emit(service.rebuild_native(
                    store, args.base, base_manifest=args.base_manifest,
                    runtime_dir=args.runtime_dir, system_data=args.system_data,
                    probe=args.probe))
            return emit(service.list_native(store, runtime_dir=args.runtime_dir, system_data=args.system_data))
        if args.command == "engine-probe":
            user_dir = None
            if not args.base_model:
                store = store_from(args)
                if store.native_dir.is_dir():
                    user_dir = store.native_dir
            engine = engine_bridge.open_engine(user_dir=user_dir)
            try:
                result = engine_bridge.probe(engine, args.pinyin, args.page_size)
            finally:
                engine.close()
            return emit({"ok": True, "user_dir": str(user_dir) if user_dir else None, **result})
        if args.command == "eval":
            cases = corpus_mod.load_cases(args.corpus)
            manifest = read_json(args.manifest)
            digest = sha256_file(args.corpus)
            if manifest.get("frozen") is not True or manifest.get("sha256") != digest:
                raise LexiconError("corpus_frozen", "corpus does not match its frozen manifest",
                                   {"manifest": manifest.get("sha256"), "actual": digest})
            user_dir = None
            if args.with_native:
                store = UserStore(args.data_dir or default_data_dir())
                if not store.native_dir.is_dir():
                    raise LexiconError("native_unavailable", "build the native table first")
                user_dir = store.native_dir
            result = corpus_mod.run(cases, user_dir=user_dir, corpus_path=args.corpus)
            corpus_mod.write_result(result, args.out)
            return emit({"ok": True, "out": str(args.out), "overall": result["overall"],
                         "categories": result["categories"], "configuration": result["configuration"]})
        raise LexiconError("unknown_operation", f"unknown command {args.command}")
    except LexiconError as exc:
        return fail(exc)
    except FileNotFoundError as exc:
        return emit({"ok": False, "error": {"code": "missing_file", "message": str(exc)}}, 3)


if __name__ == "__main__":
    raise SystemExit(main())
