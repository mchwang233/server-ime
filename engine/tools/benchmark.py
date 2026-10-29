#!/usr/bin/env python3
"""Measure the public API against the unmodified packaged dictionaries."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from server_ime_engine import Engine


def stats(values):
    ordered = sorted(values)
    return {"samples": len(values), "unit": "ms", "p50": ordered[math.ceil(len(values)*.50)-1],
            "p95": ordered[math.ceil(len(values)*.95)-1], "p99": ordered[math.ceil(len(values)*.99)-1],
            "max": max(values), "mean": sum(values)/len(values)}


def digest_runtime():
    return {str(p.relative_to(ROOT / "vendor/runtime")): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "vendor/runtime/data").iterdir()) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "checks/baseline")
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    corpus_path = ROOT / "data/baseline-v1.json"
    cases = json.loads(corpus_path.read_text())["cases"]
    before = digest_runtime()
    raw_timings, quality, initializations = [], [], []
    for _ in range(5):
        start = time.perf_counter_ns()
        with Engine() as engine:
            session = engine.create_session()
            loaded = time.perf_counter_ns()
            session.input("nihao")
            first = time.perf_counter_ns()
        initializations.append({"init_ms": (loaded-start)/1e6, "first_request_ms": (first-loaded)/1e6})
    with Engine() as engine:
        session = engine.create_session()
        for case in cases:
            state = session.set_input(case["pinyin"])
            top = [c["text"] for c in state["candidates"]["items"]]
            quality.append({**case, "top5": top, "total_candidates": state["candidates"]["total"],
                            "top1_match": bool(top and top[0] == case["expected"]),
                            "top5_match": case["expected"] in top})
        rng = random.Random(20261028)
        for repeat in range(args.repeats):
            order = cases[:]
            rng.shuffle(order)
            for case in order:
                start = time.perf_counter_ns()
                session.set_input(case["pinyin"])
                elapsed = (time.perf_counter_ns()-start)/1e6
                raw_timings.append({"mode": "whole_input", "repeat": repeat, "case": case["id"], "ms": elapsed})
        for repeat in range(5):
            for case in cases:
                session.reset()
                for index, char in enumerate(case["pinyin"]):
                    start = time.perf_counter_ns()
                    session.input(char)
                    elapsed = (time.perf_counter_ns()-start)/1e6
                    raw_timings.append({"mode": "per_key", "repeat": repeat, "case": case["id"], "key_index": index, "ms": elapsed})
    process_times = []
    requests = (ROOT / "examples/requests.jsonl").read_bytes()
    for _ in range(5):
        start = time.perf_counter_ns()
        result = subprocess.run([str(ROOT / "bin/server-ime-engine")], input=requests,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30)
        process_times.append((time.perf_counter_ns()-start)/1e6)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        assert all(reply["ok"] for reply in replies)
        assert replies[3]["result"]["commits"][0]["text"] == "我爱北京天安门"
    unchanged = before == digest_runtime()
    assert unchanged, "baseline modified packaged dictionaries"
    grouped = {}
    for group in ["all"] + sorted(set(case["group"] for case in cases)):
        rows = quality if group == "all" else [q for q in quality if q["group"] == group]
        grouped[group] = {"cases": len(rows), "top1_matches": sum(q["top1_match"] for q in rows),
                          "top5_matches": sum(q["top5_match"] for q in rows)}
    report = {"employee_id": "engine", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "uid": os.getuid(), "platform": platform.platform(), "python": platform.python_version(),
              "capabilities": Engine.capabilities(), "seed": 20261028,
              "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
              "dictionary_sha256": before, "dictionary_unchanged": unchanged,
              "quality": grouped, "context_initializations": initializations,
              "latency": {mode: stats([t["ms"] for t in raw_timings if t["mode"] == mode])
                          for mode in ["whole_input", "per_key"]},
              "process_start_create_convert_commit_exit_ms": process_times,
              "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "limitations": ["40 task-authored cases, exact reference matching, not Windows 11 comparison",
                              "page cache was warm; init numbers are not physical disk cold-start latency",
                              "API and local subprocess timings exclude IBus, application and remote-desktop latency",
                              "learning disabled; only packaged stock model, no domain/user dictionaries"]}
    (args.output / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n")
    (args.output / "quality.jsonl").write_text(''.join(json.dumps(q,ensure_ascii=False)+"\n" for q in quality))
    (args.output / "latency.jsonl").write_text(''.join(json.dumps(t)+"\n" for t in raw_timings))
    print(json.dumps({"quality": grouped, "latency": report["latency"], "peak_rss_kib": report["peak_rss_kib"]},indent=2))


if __name__ == "__main__":
    main()
