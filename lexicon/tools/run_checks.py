#!/usr/bin/env python3
"""Run every lexicon check and write machine-readable evidence under checks/.

Covers: reproducible base build, frozen corpus, libpinyin native round-trip,
real engine reads, learning persistence/gating, import/export, backup/restore,
corruption handling, fixed-corpus scoring and the unit suite.  Temporary user
data lives in checks/runtime/; engine data fingerprints are compared before and
after so the evidence shows the base model was not trained or edited.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from lexicon import corpus, service, transfer  # noqa: E402
from lexicon import engine as bridge  # noqa: E402
from lexicon.errors import LexiconError  # noqa: E402
from lexicon.records import read_json, read_jsonl, sha256_file, utcnow, validate_entry  # noqa: E402
from lexicon.store import UserStore  # noqa: E402

CHECKS = ROOT / "checks"
RUNTIME = CHECKS / "runtime"
LOGS = CHECKS / "logs"
BASE = ROOT / "data/base/lexicon-v1.jsonl"
BASE_MANIFEST = ROOT / "data/base/manifest.json"
CORPUS = ROOT / "corpus/eval/cases-v1.jsonl"
CORPUS_MANIFEST = ROOT / "corpus/eval/manifest.json"
BASE_NATIVE = ROOT / "build/base-v1/native"
PY = sys.executable


class Runner:
    def __init__(self):
        self.steps = []
        self.started = time.time()

    def step(self, name, function, *, required=True):
        started = time.time()
        LOGS.mkdir(parents=True, exist_ok=True)
        log_path = LOGS / f"{name}.log"
        try:
            detail = function()
            ok = not (isinstance(detail, dict) and detail.get("ok") is False)
            error = None if ok else {"type": "CheckFailed", "message": "step reported ok=false"}
        except Exception as exc:
            detail = None
            ok = False
            error = {"type": type(exc).__name__, "message": str(exc)}
            if isinstance(exc, LexiconError):
                error.update(exc.to_dict()["error"])
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
        elapsed = round(time.time() - started, 3)
        record = {"name": name, "required": required, "ok": ok, "seconds": elapsed,
                  "log": str(log_path.relative_to(ROOT)) if log_path.exists() else None}
        if detail is not None:
            record["detail"] = detail
        if error:
            record["error"] = error
        self.steps.append(record)
        print(json.dumps({"step": name, "ok": ok, "seconds": elapsed, "error": error}, ensure_ascii=False))
        return record

    def ok(self):
        return all(step["ok"] for step in self.steps if step["required"])


def run_tool(name, args):
    started = time.time()
    result = subprocess.run([PY, *args], cwd=str(REPO), capture_output=True, text=True)
    log = LOGS / f"{name}.tool.log"
    log.write_text("$ " + " ".join([PY, *args]) + "\n" + result.stdout + "\n--- stderr ---\n" + result.stderr,
                   encoding="utf-8")
    if result.returncode != 0:
        raise LexiconError("check_failed", f"{name} exited {result.returncode}", {"stderr": result.stderr[-2000:]})
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload = {"stdout": result.stdout[-2000:]}
    return {"seconds": round(time.time() - started, 3), "output": payload,
            "log": str(log.relative_to(ROOT))}


def load_base():
    return [validate_entry(row, require_source=True, kinds=("base",)) for row in read_jsonl(BASE)]


def engine_source_fingerprint():
    rows = {}
    for path in sorted((REPO / "engine/src").rglob("*.py")):
        rows[str(path.relative_to(REPO))] = sha256_file(path)
    return rows


def dir_fingerprint(path):
    rows = {}
    for item in sorted(Path(path).iterdir()):
        if item.is_file():
            rows[item.name] = sha256_file(item)
    return rows


def main():
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    CHECKS.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(RUNTIME, ignore_errors=True)
    (RUNTIME / "tmp").mkdir(parents=True)
    (RUNTIME / "home").mkdir(parents=True)
    shutil.rmtree(LOGS, ignore_errors=True)
    LOGS.mkdir(parents=True)

    runner = Runner()
    runtime, data = bridge.engine_paths()
    engine_data_before = bridge.fingerprint_data(data)
    engine_src_before = engine_source_fingerprint()
    base_hash_before = sha256_file(BASE)
    corpus_hash_before = sha256_file(CORPUS)

    environment = {
        "python": sys.version,
        "platform": platform.platform(),
        "repo": str(REPO),
        "runtime_dir": str(runtime),
        "system_data": str(data),
        "engine_data_files": engine_data_before,
        "base_before": base_hash_before,
        "corpus_before": corpus_hash_before,
    }

    runner.step("base_build", lambda: run_tool("base_build", ["lexicon/tools/build_base.py"]))
    runner.step("base_reproducible", lambda: run_tool("base_reproducible", ["lexicon/tools/build_base.py", "--check"]))
    runner.step("corpus_frozen", lambda: run_tool("corpus_frozen", ["lexicon/tools/freeze_corpus.py"]))
    runner.step("native_base_build", lambda: run_tool("native_base_build", ["lexicon/tools/build_native.py"]))

    def engine_reading():
        entries = load_base()
        with open(BASE_MANIFEST, encoding="utf-8") as handle:
            base_manifest = json.load(handle)
        probe_base = bridge.open_engine()
        try:
            before = bridge.probe_entries(probe_base, entries)
        finally:
            probe_base.close()
        probe_enhanced = bridge.open_engine(user_dir=BASE_NATIVE)
        try:
            after = bridge.probe_entries(probe_enhanced, entries)
        finally:
            probe_enhanced.close()
        improved = [row for row, original in zip(after, before) if row["top1"] and not original["top1"]]
        regressed = [row for row, original in zip(after, before) if original["top1"] and not row["top1"]]
        payload = {
            "kind": "coverage probe (the probes are the enhancement entries themselves, not the evaluation corpus)",
            "engine": {
                "api_version": "1.0",
                "component_version": probe_enhanced.lexicon_bridge["engine_component_version"],
                "backend": probe_enhanced.lexicon_bridge["backend"],
                "backend_version": probe_enhanced.lexicon_bridge["backend_version"],
                "bridge": probe_enhanced.lexicon_bridge["bridge"],
                "user_dir": str(BASE_NATIVE),
            },
            "base_lexicon": {"version": base_manifest["lexicon_version"],
                             "sha256": base_manifest["files"]["lexicon-v1.jsonl"]["sha256"],
                             "entries": len(entries)},
            "pristine_model": {"top1": sum(row["top1"] for row in before),
                               "top5": sum(row["top5"] for row in before)},
            "with_base_lexicon": {"top1": sum(row["top1"] for row in after),
                                  "top5": sum(row["top5"] for row in after)},
            "improved_top1": len(improved),
            "regressed_top1": len(regressed),
            "samples_improved": improved[:10],
            "failures": [row for row in after if not row["top5"]][:20],
            "native_manifest": read_json(ROOT / "build/base-v1/manifest.json"),
        }
        (CHECKS / "engine-read.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                                                 encoding="utf-8")
        return {key: payload[key] for key in ("pristine_model", "with_base_lexicon", "improved_top1", "regressed_top1")}

    runner.step("engine_reads_dictionary", engine_reading)

    def user_lifecycle():
        base_keys = {(entry["text"], entry["pinyin"]) for entry in load_base()}
        user_root = RUNTIME / "user"
        store = UserStore(user_root, create=True, base_manifest=BASE_MANIFEST)
        result = {"store_id": store.meta["store_id"], "initial_learning": store.learning_enabled, "steps": []}

        def record(name, ok, **extra):
            result["steps"].append({"name": name, "ok": bool(ok), **extra})

        # Disabled by default and no write at all.
        words, meta = store.root / "words.jsonl", store.root / "meta.json"
        before = (sha256_file(words), sha256_file(meta))
        denied = store.record_commit("词库增强", "ci'ku'zeng'qiang", event_id="disabled-1")
        after = (sha256_file(words), sha256_file(meta))
        record("disabled_writes_nothing", not denied["recorded"] and before == after,
               reason=denied["reason"], hashes_unchanged=before == after)
        store.set_learning(True, reason="checks")
        first = store.record_commit("词库增强", "ci'ku'zeng'qiang", event_id="check-1")
        duplicate = store.record_commit("词库增强", "ci'ku'zeng'qiang", event_id="check-1")
        record("learn_and_dedupe", first["recorded"] and not duplicate["recorded"],
               count=first["entry"]["count"], duplicate_reason=duplicate["reason"])
        store.add_phrase("芷若词库", "zhi'ruo'ci'ku", 500)
        store.record_commit("麒麟操作系统", "qi'lin'cao'zuo'xi'tong", event_id="check-2")
        reopened = UserStore(user_root)
        entries = reopened.list_words(limit=1000)["entries"]
        record("restart_persists", reopened.learning_enabled and reopened.list_words()["total"] >= 3,
               entries=len(entries))
        rebuilt = service.rebuild_native(reopened, BASE, base_manifest=BASE_MANIFEST, probe=3)
        expected_merged = len(base_keys) + len({(row["text"], row["pinyin"]) for row in entries} - base_keys)
        record("native_rebuild", rebuilt["entries"] == expected_merged and rebuilt["personal"] == len(entries),
               entries=rebuilt["entries"], personal=rebuilt["personal"], expected=expected_merged)
        engine = bridge.open_engine(user_dir=reopened.native_dir)
        try:
            custom = bridge.probe(engine, "zhiruociku")
            learned = bridge.probe(engine, "qilincaozuoxitong")
        finally:
            engine.close()
        record("engine_sees_personal", custom["texts"][0] == "芷若词库", top=custom["texts"][:3],
               learned_top=learned["texts"][:3])

        bundle = RUNTIME / "user-export.json"
        exported = transfer.export_bundle(reopened, bundle)
        copy = UserStore(RUNTIME / "user-copy", create=True)
        imported = transfer.import_bundle(copy, bundle)
        roundtrip = transfer.export_bundle(copy, RUNTIME / "user-export-2.json")
        record("export_import_roundtrip",
               imported["entries"] == exported["entries"] and roundtrip["checksum"] == exported["checksum"]
               and reopened.list_words()["entries"] == copy.list_words()["entries"],
               entries=exported["entries"], checksum=exported["checksum"])
        legacy = RUNTIME / "legacy.tsv"
        legacy.write_text("临时测试词\tlin'shi'ce'shi'ci\t3\n", encoding="utf-8")
        migrated = transfer.import_bundle(copy, legacy)
        record("legacy_migration", migrated["migrated_from"] == "ime-user-words/0")
        legacy_entry = [row for row in copy.list_words()["entries"] if row["text"] == "临时测试词"]
        record("legacy_entry", bool(legacy_entry) and legacy_entry[0]["source"] == "legacy-v0")

        backup = transfer.make_backup(reopened, label="checks", note="before restore")
        original = reopened.list_words(limit=1000)["entries"]
        reopened.add_phrase("恢复测试短语", "hui'fu'ce'shi'duan'yu", 100)
        restored = transfer.restore_backup(reopened, backup["backup_id"])
        record("backup_restore", reopened.list_words()["entries"] == original,
               pre_restore=restored["pre_restore_backup"], entries=restored["entries"])
        rebuilt_restore = service.rebuild_native(reopened, BASE, base_manifest=BASE_MANIFEST)
        expected_restore = len(base_keys) + len({(row["text"], row["pinyin"]) for row in original} - base_keys)
        record("rebuild_after_restore", rebuilt_restore["entries"] == expected_restore,
               entries=rebuilt_restore["entries"], expected=expected_restore)

        before = sha256_file(words)
        raw = json.loads(bundle.read_text(encoding="utf-8"))
        raw["entries"][0]["count"] = 999
        bad = RUNTIME / "bad-bundle.json"
        bad.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        try:
            transfer.import_bundle(reopened, bad)
            corrupt_code = "none"
        except LexiconError as exc:
            corrupt_code = exc.code
        record("corrupt_bundle_rejected", corrupt_code == "checksum_mismatch" and sha256_file(words) == before,
               code=corrupt_code)
        bad_backup = transfer.make_backup(reopened, label="corrupt")
        (reopened.backups_dir / bad_backup["backup_id"] / "words.jsonl").write_text("tampered\n", encoding="utf-8")
        before = sha256_file(words)
        try:
            transfer.restore_backup(reopened, bad_backup["backup_id"])
            backup_code = "none"
        except LexiconError as exc:
            backup_code = exc.code
        record("corrupt_backup_rejected", backup_code == "checksum_mismatch" and sha256_file(words) == before,
               code=backup_code)

        reopened.set_learning(False, reason="private session")
        before = (sha256_file(words), sha256_file(meta))
        denied = reopened.record_commit("用户词库", "yong'hu'ci'ku", event_id="disabled-2")
        after = (sha256_file(words), sha256_file(meta))
        restored = UserStore(user_root)
        record("disabled_after_restart", not denied["recorded"] and before == after
               and not restored.learning_enabled,
               reason=denied["reason"], hashes_unchanged=before == after)
        final_rebuild = service.rebuild_native(restored, BASE, base_manifest=BASE_MANIFEST)
        verification = restored.verify()
        record("store_verify", verification["ok"], issues=verification["issues"],
               warnings=verification["warnings"], entries=final_rebuild["entries"])
        result.update({
            "final_entries": restored.list_words(limit=1000)["entries"],
            "learning": restored.learning_enabled,
            "verify": verification,
            "ok": all(item["ok"] for item in result["steps"]),
        })
        (CHECKS / "persistence.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                                 encoding="utf-8")
        return {"ok": result["ok"], "steps": result["steps"], "final_entries": len(result["final_entries"])}

    runner.step("personal_data", user_lifecycle)

    def evaluation():
        cases = corpus.load_cases(CORPUS)
        baseline = corpus.run(cases, corpus_path=CORPUS)
        corpus.write_result(baseline, CHECKS / "eval-base.json")
        enhanced = corpus.run(cases, user_dir=BASE_NATIVE, corpus_path=CORPUS)
        corpus.write_result(enhanced, CHECKS / "eval-enhanced.json")
        comparison = corpus.compare(baseline, enhanced)
        (CHECKS / "eval-compare.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=1) + "\n",
                                                  encoding="utf-8")
        guard = corpus.contamination(load_base(), cases)
        return {
            "cases": len(cases),
            "baseline": baseline["overall"],
            "enhanced": enhanced["overall"],
            "categories_baseline": baseline["categories"],
            "categories_enhanced": enhanced["categories"],
            "comparison": comparison["overall"],
            "contamination": guard,
        }

    runner.step("fixed_corpus_eval", evaluation)

    def unit_tests():
        env = dict(os.environ)
        env["TMPDIR"] = str(RUNTIME / "tmp")
        env["HOME"] = str(RUNTIME / "home")
        started = time.time()
        result = subprocess.run([PY, "-m", "unittest", "discover", "-s", "lexicon/tests", "-v"],
                                cwd=str(REPO), capture_output=True, text=True, env=env)
        log = CHECKS / "unittest.log"
        log.write_text(result.stdout + "\n--- stderr ---\n" + result.stderr, encoding="utf-8")
        if result.returncode != 0:
            raise LexiconError("check_failed", "unit tests failed", {"log": str(log), "stderr": result.stderr[-2000:]})
        lines = [line for line in result.stderr.splitlines() if line.startswith("Ran ")]
        return {"seconds": round(time.time() - started, 3), "summary": lines[-1] if lines else "",
                "log": "checks/unittest.log"}

    runner.step("unit_tests", unit_tests)

    engine_data_after = bridge.fingerprint_data(data)
    engine_src_after = engine_source_fingerprint()
    base_hash_after = sha256_file(BASE)
    corpus_hash_after = sha256_file(CORPUS)
    fingerprints = {
        "engine_data_unchanged": engine_data_before == engine_data_after,
        "engine_source_unchanged": engine_src_before == engine_src_after,
        "base_lexicon_unchanged": base_hash_before == base_hash_after,
        "corpus_unchanged": corpus_hash_before == corpus_hash_after,
        "engine_data_files": len(engine_data_before),
        "engine_source_files": len(engine_src_before),
    }
    summary = {
        "schema": "ime-lexicon-checks/1",
        "component": {"employee_id": "lexicon", "version": "0.1.0"},
        "generated_at": utcnow(),
        "ok": runner.ok() and all(fingerprints[key] for key in
                                  ("engine_data_unchanged", "engine_source_unchanged",
                                   "base_lexicon_unchanged", "corpus_unchanged")),
        "seconds": round(time.time() - runner.started, 3),
        "environment": environment,
        "fingerprints": fingerprints,
        "steps": runner.steps,
        "artifacts": {
            "base_lexicon": {"file": "data/base/lexicon-v1.jsonl", "sha256": base_hash_after},
            "base_manifest": {"file": "data/base/manifest.json", "sha256": sha256_file(BASE_MANIFEST)},
            "corpus": {"file": "corpus/eval/cases-v1.jsonl", "sha256": corpus_hash_after},
            "corpus_manifest": {"file": "corpus/eval/manifest.json", "sha256": sha256_file(CORPUS_MANIFEST)},
            "native_base_manifest": {"file": "build/base-v1/manifest.json",
                                      "sha256": sha256_file(ROOT / "build/base-v1/manifest.json")},
        },
        "limitations": [
            "The engine bridge replaces the Native class for one construction call because engine 0.1.0 hardcodes user_dir=NULL.",
            "Mixed Chinese/Latin and typo categories expose engine capabilities that are not implemented; they are scored, not skipped.",
            "The coverage probe uses the enhancement entries themselves and is not a general accuracy claim.",
            "No GUI, remote desktop or real application input is exercised here; platform owns that evidence.",
        ],
    }
    (CHECKS / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": summary["ok"],
        "steps": [{step["name"]: step["ok"]} for step in runner.steps],
        "fingerprints": fingerprints,
        "summary": str(CHECKS / "summary.json"),
    }, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
