import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

LEXICON = Path(__file__).resolve().parents[1]
REPO = LEXICON.parent
sys.path.insert(0, str(LEXICON / "src"))

from lexicon import corpus, service, transfer  # noqa: E402
from lexicon import engine as engine_bridge  # noqa: E402
from lexicon.errors import LexiconError  # noqa: E402
from lexicon.native import Libpinyin  # noqa: E402
from lexicon.records import (  # noqa: E402
    MAX_COUNT, check_reading, read_json, read_jsonl, sha256_file,
    validate_entry, write_jsonl_atomic,
)
from lexicon.store import UserStore  # noqa: E402

BASE = LEXICON / "data/base/lexicon-v1.jsonl"
BASE_MANIFEST = LEXICON / "data/base/manifest.json"
CORPUS = LEXICON / "corpus/eval/cases-v1.jsonl"
CORPUS_MANIFEST = LEXICON / "corpus/eval/manifest.json"
RUNTIME, DATA = engine_bridge.engine_paths()


def load_base():
    return [validate_entry(row, require_source=True, kinds=("base",)) for row in read_jsonl(BASE)]


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lex-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def store(self, name="store", **kwargs):
        return UserStore(self.tmp / name, create=True, base_manifest=BASE_MANIFEST, **kwargs)


class BaseDataTests(TempCase):
    def test_manifest_matches_lexicon(self):
        manifest = read_json(BASE_MANIFEST)
        self.assertEqual(manifest["schema"], "ime-lexicon-base/1")
        self.assertGreaterEqual(manifest["entry_count"], 300)
        self.assertEqual(manifest["files"]["lexicon-v1.jsonl"]["sha256"], sha256_file(BASE))
        entries = load_base()
        self.assertEqual(len(entries), manifest["entry_count"])
        for entry in entries:
            self.assertEqual(entry["license"], "CC-BY-4.0")
            self.assertEqual(entry["source"], "server-ime-curation-v1")
            self.assertEqual(len(check_reading(entry["text"], entry["pinyin"])), len(entry["text"]))
        self.assertEqual(len({entry["text"] for entry in entries}), len(entries))

    def test_build_is_reproducible(self):
        result = subprocess.run([sys.executable, str(LEXICON / "tools/build_base.py"), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])


class CorpusTests(TempCase):
    def test_frozen_manifest_and_categories(self):
        manifest = read_json(CORPUS_MANIFEST)
        cases = corpus.load_cases(CORPUS)
        self.assertTrue(manifest["frozen"])
        self.assertEqual(manifest["schema"], "ime-eval-corpus/1")
        self.assertEqual(manifest["sha256"], sha256_file(CORPUS))
        self.assertEqual(len(cases), 200)
        self.assertEqual(manifest["cases"], len(cases))
        self.assertEqual(set(manifest["categories"]), set(corpus.CATEGORIES))
        self.assertEqual(manifest["scoring"]["id"], corpus.SCORING)
        self.assertEqual(len({case["id"] for case in cases}), 200)

    def test_no_evaluation_answers_in_base_data(self):
        guard = corpus.contamination(load_base(), corpus.load_cases(CORPUS))
        self.assertTrue(guard["ok"], guard)

    def test_freezing_again_keeps_hash(self):
        before = sha256_file(CORPUS)
        result = subprocess.run([sys.executable, str(LEXICON / "tools/freeze_corpus.py")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sha256_file(CORPUS), before)

    def test_scoring_shape(self):
        cases = corpus.load_cases(CORPUS)[:12]
        result = corpus.run(cases, corpus_path=CORPUS)
        self.assertEqual(result["scoring"], corpus.SCORING)
        self.assertEqual(result["overall"]["cases"], 12)
        self.assertEqual(len(result["rows"]), 12)
        self.assertIn("top1_rate", result["overall"])
        self.assertIn("mean_cer", result["overall"])
        self.assertEqual(sum(1 for row in cases if row["category"] == "common"),
                         result["categories"]["common"]["cases"])


class NativeTests(TempCase):
    def test_native_roundtrip_and_engine_reads_data(self):
        entries = load_base()
        lib = Libpinyin(RUNTIME, DATA)
        destination = self.tmp / "native"
        result = lib.build_into(destination, entries)
        exported = lib.export(destination)
        self.assertEqual(result["accepted"], len(entries))
        self.assertEqual({(row["text"], row["pinyin"]) for row in exported},
                         {(entry["text"], entry["pinyin"]) for entry in entries})
        engine = engine_bridge.open_engine(user_dir=destination)
        try:
            probe = engine_bridge.probe_entries(engine, entries, limit=30)
        finally:
            engine.close()
        self.assertTrue(all(row["top1"] for row in probe), probe)
        # The same entries are mostly absent from the pristine model: the visible
        # difference proves the engine loaded the lexicon table.
        base_engine = engine_bridge.open_engine()
        try:
            before = engine_bridge.probe_entries(base_engine, entries, limit=30)
        finally:
            base_engine.close()
        self.assertTrue(any(not row["top1"] for row in before))

    def test_native_rejects_bad_reading(self):
        lib = Libpinyin(RUNTIME, DATA)
        destination = self.tmp / "bad"
        with self.assertRaises(LexiconError) as caught:
            lib.build_into(destination, [{"text": "词库", "pinyin": "ci'ku'extra", "count": 1}])
        self.assertEqual(caught.exception.code, "native_build_failed")
        self.assertFalse(destination.exists())


class StoreTests(TempCase):
    def test_learning_persists_and_deduplicates(self):
        store = self.store()
        self.assertFalse(store.learning_enabled)
        store.set_learning(True, reason="test")
        first = store.record_commit("词库增强", "ci'ku'zeng'qiang", event_id="e-1")
        self.assertTrue(first["recorded"])
        duplicate = store.record_commit("词库增强", "ci'ku'zeng'qiang", event_id="e-1")
        self.assertFalse(duplicate["recorded"])
        self.assertEqual(duplicate["reason"], "duplicate_event")
        self.assertEqual(store.list_words()["entries"][0]["count"], 1)
        reopened = UserStore(store.root)
        self.assertTrue(reopened.learning_enabled)
        self.assertEqual(reopened.list_words()["entries"][0]["text"], "词库增强")
        again = reopened.record_commit("词库增强", "ci'ku'zeng'qiang")
        self.assertEqual(again["entry"]["count"], 2)

    def test_disabled_learning_writes_nothing(self):
        store = self.store()
        store.set_learning(False, reason="privacy")
        words = store.root / "words.jsonl"
        meta = store.root / "meta.json"
        before = (sha256_file(words), sha256_file(meta))
        for _ in range(3):
            result = store.record_commit("你好", "ni'hao")
            self.assertFalse(result["recorded"])
            self.assertEqual(result["reason"], "learning_disabled")
        self.assertEqual((sha256_file(words), sha256_file(meta)), before)
        reopened = UserStore(store.root)
        self.assertFalse(reopened.learning_enabled)
        self.assertEqual(reopened.list_words()["total"], 0)

    def test_privacy_and_purpose_gates(self):
        store = self.store()
        store.set_learning(True)
        cases = [
            store.record_commit("秘密", "mi'mi", private=True),
            store.record_commit("密码", "mi'ma", purpose="password"),
            store.record_commit("你好", "ni'hao", learning_eligible=False),
        ]
        self.assertEqual([row["reason"] for row in cases],
                         ["private_input", "purpose_not_allowed", "not_eligible"])
        self.assertEqual(store.list_words()["total"], 0)

    def test_invalid_reading_never_written(self):
        store = self.store()
        store.set_learning(True)
        result = store.record_commit("词库", "ci'ku'extra")
        self.assertFalse(result["recorded"])
        self.assertEqual(result["reason"], "invalid_record")
        unknown = store.record_commit("词库", "ci'zzz")
        self.assertFalse(unknown["recorded"])
        self.assertEqual(unknown["reason"], "invalid_record")
        self.assertEqual(store.list_words()["total"], 0)

    def test_counts_and_custom_phrases(self):
        store = self.store()
        added = store.add_phrase("芷若词库", "zhi'ruo'ci'ku", 777)
        self.assertEqual(added["entry"]["kind"], "custom")
        store.set_learning(True)
        store.record_commit("芷若词库", "zhi'ruo'ci'ku")
        self.assertEqual(store.list_words(kind="custom")["entries"][0]["count"], 778)
        removed = store.remove_phrase("芷若词库")
        self.assertEqual(removed["count"], 1)
        self.assertEqual(store.list_words()["total"], 0)
        capped = store.add_phrase("极限词", "ji'xian'ci", MAX_COUNT)
        store.record_commit("极限词", "ji'xian'ci")
        self.assertEqual(store.list_words()["entries"][0]["count"], MAX_COUNT)

    def test_store_corruption_is_reported(self):
        store = self.store()
        store.set_learning(True)
        store.record_commit("你好", "ni'hao")
        with open(store.root / "words.jsonl", "a", encoding="utf-8") as handle:
            handle.write('{"text":"篡改","pinyin":"cuan\'gai","count":1,"kind":"learned"}\n')
        with self.assertRaises(LexiconError) as caught:
            UserStore(store.root)
        self.assertEqual(caught.exception.code, "store_corrupt")

    def test_lock_blocks_second_writer(self):
        store = self.store()
        script = (
            "import sys, time\n"
            f"sys.path.insert(0, {str(LEXICON / 'src')!r})\n"
            "from lexicon.store import UserStore\n"
            f"s = UserStore({str(store.root)!r})\n"
            "with s.lock():\n"
            "    print('locked', flush=True)\n"
            "    time.sleep(3)\n"
        )
        process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.addCleanup(process.wait)
        try:
            line = process.stdout.readline()
            self.assertIn("locked", line)
            with self.assertRaises(LexiconError) as caught:
                store.add_phrase("锁测试", "suo'ce'shi")
            self.assertEqual(caught.exception.code, "store_locked")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()


class TransferTests(TempCase):
    def test_export_import_roundtrip(self):
        source = self.store("source")
        source.set_learning(True)
        source.record_commit("词库增强", "ci'ku'zeng'qiang")
        source.add_phrase("芷若词库", "zhi'ruo'ci'ku", 321)
        exported = transfer.export_bundle(source, self.tmp / "bundle.json")
        self.assertEqual(exported["entries"], 2)
        target = self.store("target")
        result = transfer.import_bundle(target, self.tmp / "bundle.json")
        self.assertEqual(result["added"], 2)
        self.assertEqual(source.list_words()["entries"], target.list_words()["entries"])
        second = transfer.export_bundle(target, self.tmp / "bundle2.json")
        self.assertEqual(exported["checksum"], second["checksum"])

    def test_failed_imports_leave_store_unchanged(self):
        store = self.store()
        store.set_learning(True)
        store.record_commit("你好", "ni'hao")
        before = sha256_file(store.root / "words.jsonl")
        bundle = read_json(self.tmp / "missing.json") if (self.tmp / "missing.json").exists() else None
        good = transfer.export_bundle(store, self.tmp / "good.json")
        raw = json.loads((self.tmp / "good.json").read_text(encoding="utf-8"))
        raw["entries"][0]["count"] = 999
        (self.tmp / "bad-checksum.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        raw2 = json.loads((self.tmp / "good.json").read_text(encoding="utf-8"))
        raw2["format"] = "ime-lexicon-user-bundle/2"
        (self.tmp / "bad-version.json").write_text(json.dumps(raw2, ensure_ascii=False), encoding="utf-8")
        (self.tmp / "bad-json.json").write_text("{not json", encoding="utf-8")
        expected = {
            "bad-checksum.json": "checksum_mismatch",
            "bad-version.json": "incompatible_version",
            "bad-json.json": "invalid_json",
        }
        for name, code in expected.items():
            with self.assertRaises(LexiconError) as caught:
                transfer.import_bundle(store, self.tmp / name, mode="replace")
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(sha256_file(store.root / "words.jsonl"), before)
        self.assertEqual(good["entries"], 1)
        self.assertIsNone(bundle)

    def test_legacy_migration(self):
        store = self.store()
        (self.tmp / "legacy-list.json").write_text(json.dumps(
            [{"word": "词库增强", "pinyin": "ci'ku'zeng'qiang", "freq": 4}], ensure_ascii=False),
            encoding="utf-8")
        result = transfer.import_bundle(store, self.tmp / "legacy-list.json")
        self.assertEqual(result["migrated_from"], "ime-user-words/0")
        entry = store.list_words()["entries"][0]
        self.assertEqual(entry["source"], "legacy-v0")
        self.assertEqual(entry["count"], 4)
        (self.tmp / "legacy-v0.json").write_text(json.dumps(
            {"format": "ime-user-words/0", "words": [
                {"text": "用户词库", "pinyin": "yong'hu'ci'ku", "count": 2, "kind": "custom"}]},
            ensure_ascii=False), encoding="utf-8")
        result = transfer.import_bundle(store, self.tmp / "legacy-v0.json")
        self.assertEqual(result["migrated_from"], "ime-user-words/0")
        self.assertEqual(store.list_words(kind="custom")["total"], 1)
        (self.tmp / "legacy.tsv").write_text("词库增强\tci'ku'zeng'qiang\t5\n", encoding="utf-8")
        result = transfer.import_bundle(store, self.tmp / "legacy.tsv")
        self.assertEqual(result["migrated_from"], "ime-user-words/0")
        tsv = [row for row in store.list_words()["entries"] if row["text"] == "词库增强"][0]
        self.assertEqual(tsv["count"], 5)
        self.assertEqual(tsv["source"], "legacy-v0")

    def test_backup_and_restore(self):
        store = self.store()
        store.set_learning(True)
        store.record_commit("词库增强", "ci'ku'zeng'qiang")
        backup = transfer.make_backup(store, label="check")
        original = store.list_words()["entries"]
        store.add_phrase("临时短语", "lin'shi'duan'yu")
        store.set_learning(False)
        restored = transfer.restore_backup(store, backup["backup_id"])
        self.assertTrue(restored["ok"])
        self.assertEqual(store.list_words()["entries"], original)
        self.assertTrue(store.learning_enabled)
        self.assertTrue((store.backups_dir / restored["pre_restore_backup"]).is_dir())
        verified = transfer.verify_backup(store, backup["backup_id"])
        self.assertTrue(verified["ok"])

    def test_corrupt_backup_rejected(self):
        store = self.store()
        store.record_commit("你好", "ni'hao")
        backup = transfer.make_backup(store, label="corrupt")
        path = store.backups_dir / backup["backup_id"] / "words.jsonl"
        path.write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(LexiconError) as caught:
            transfer.restore_backup(store, backup["backup_id"])
        self.assertEqual(caught.exception.code, "checksum_mismatch")
        self.assertEqual(store.list_words()["total"], 0)

    def test_prune_keeps_newest(self):
        store = self.store()
        ids = [transfer.make_backup(store, label=f"b{i}")["backup_id"] for i in range(4)]
        result = transfer.prune_backups(store, keep=2)
        self.assertEqual(len(result["removed"]), 2)
        remaining = [row["backup_id"] for row in transfer.list_backups(store)["backups"]]
        self.assertEqual(len(remaining), 2)


class NativePersonalTests(TempCase):
    def test_merge_keeps_base_prior(self):
        base = [{"text": "词库增强", "pinyin": "ci'ku'zeng'qiang", "count": 160}]
        personal = [{"text": "词库增强", "pinyin": "ci'ku'zeng'qiang", "count": 2, "kind": "learned"}]
        merged = service.merged_entries(base, personal)
        self.assertEqual(merged[0]["count"], 162)
        self.assertEqual(merged[0]["kind"], "learned")

    def test_personal_and_learned_words_reach_engine_after_restart(self):
        store = self.store()
        store.add_phrase("芷若词库", "zhi'ruo'ci'ku", 500)
        store.set_learning(True)
        store.record_commit("麒麟操作系统", "qi'lin'cao'zuo'xi'tong")
        result = service.rebuild_native(store, BASE, base_manifest=BASE_MANIFEST, probe=2)
        self.assertEqual(result["personal"], 2)
        reopened = UserStore(store.root)
        engine = engine_bridge.open_engine(user_dir=reopened.native_dir)
        try:
            custom = engine_bridge.probe(engine, "zhiruociku")
            learned = engine_bridge.probe(engine, "qilincaozuoxitong")
        finally:
            engine.close()
        self.assertEqual(custom["texts"][0], "芷若词库")
        self.assertEqual(learned["texts"][0], "麒麟操作系统")
        self.assertEqual(reopened.list_words(kind="custom")["total"], 1)

    def test_engine_data_is_not_modified(self):
        before = engine_bridge.fingerprint_data(DATA)
        store = self.store()
        store.add_phrase("芷若词库", "zhi'ruo'ci'ku", 500)
        service.rebuild_native(store, BASE, base_manifest=BASE_MANIFEST)
        self.assertEqual(before, engine_bridge.fingerprint_data(DATA))


class CliTests(TempCase):
    def test_cli_lifecycle(self):
        data = self.tmp / "cli"
        binary = LEXICON / "bin/lexicon"
        def run(*args):
            result = subprocess.run([str(binary), "--data-dir", str(data), *args],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(run("init")["schema"], "ime-lexicon-user/1")
        self.assertTrue(run("learning", "on")["learning"]["enabled"])
        self.assertTrue(run("learn", "词库增强", "ci'ku'zeng'qiang")["recorded"])
        self.assertEqual(run("export", "--out", str(self.tmp / "cli.json"))["entries"], 1)
        self.assertEqual(run("words")["total"], 1)
        self.assertFalse(run("learning", "off")["learning"]["enabled"])
        self.assertFalse(run("learn", "用户词库", "yong'hu'ci'ku")["recorded"])
        self.assertEqual(run("words")["total"], 1)


if __name__ == "__main__":
    unittest.main()
