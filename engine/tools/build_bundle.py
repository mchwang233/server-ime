#!/usr/bin/env python3
"""Assemble the runnable component; never execute third-party build scripts."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile

from verify_vendor import ROOT, verify
from syllable_table import check as check_syllables


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "build/bundle")
    args = parser.parse_args()
    output = args.output.resolve()
    if ROOT not in output.parents or len(output.relative_to(ROOT).parts) < 2:
        raise SystemExit("bundle output must be a subdirectory of an engine build directory")
    # Refuse destinations overlapping sources or pinned dependencies.
    if output.relative_to(ROOT).parts[0] in {"src", "vendor", "tools", "docs", "tests", "data", "bin"}:
        raise SystemExit("bundle destination overlaps source inputs")
    verify()
    check_syllables()
    if output.exists():
        shutil.rmtree(output)
    payload = output / "payload/engine"
    payload.mkdir(parents=True)
    for name in ("src", "bin", "docs", "examples", "tools", "tests", "data",
                 "vendor/runtime", "vendor/sources", "checks/baseline"):
        shutil.copytree(ROOT / name, payload / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("README.md", "LICENSE", "CMakeLists.txt", "vendor.lock.json",
                 "api-v1.schema.json", "dependencies.json", "checks/README.md",
                 "vendor/libpinyin-2.6.0-4.el9.src.rpm", "vendor/libpinyin-2.6.0.tar.gz"):
        shutil.copyfile(ROOT / name, payload / name)
    # Consume the lexicon component without editing or regenerating its data.
    lexicon = ROOT.parent / "lexicon"
    shutil.copytree(lexicon / "src/lexicon", payload / "src/lexicon",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(lexicon / "data/base", payload / "data/lexicon")
    shutil.copytree(lexicon / "licenses", payload / "vendor/lexicon-licenses")
    shutil.copyfile(lexicon / "SOURCES.md", payload / "vendor/LEXICON-SOURCES.md")
    dependency = {"employee_id": "lexicon", "code_license": "GPL-3.0-or-later",
                  "data_license": "CC-BY-4.0", "source": "project lexicon component, unmodified",
                  "files": {str(p.relative_to(lexicon)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for folder in ("src/lexicon", "data/base", "licenses")
                            for p in sorted((lexicon / folder).rglob("*"))
                            if p.is_file() and p.suffix != ".pyc"}}
    (payload / "vendor/lexicon-dependency.json").write_text(json.dumps(dependency, indent=2) + "\n")
    files = []
    for path in sorted((output / "payload").rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(output / "payload"))
        executable = rel == "engine/bin/server-ime-engine"
        mode = 0o755 if executable else 0o644
        path.chmod(mode)
        kind = ("executable" if executable else "library" if "/src/" in rel or "/lib/" in rel
                else "data" if "/data/" in rel else "doc")
        files.append({"path": rel, "size": path.stat().st_size,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "mode": f"0{mode:o}", "kind": kind})
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", str(int(datetime(2026, 10, 28, tzinfo=timezone.utc).timestamp()))))
    manifest = {
        "schema": "ime.component-manifest/1",
        "component": {"id": "engine", "name": "服务器拼音转换引擎", "version": "0.4.0", "kind": "engine",
                      "license": "GPL-3.0-or-later", "description": "employee_id=engine; libpinyin 2.6.0 conversion API 1.0"},
        "package": {"format": "ime-bundle/1", "payload_root": "payload", "builder": "engine/tools/build_bundle.py",
                    "created_at": datetime.fromtimestamp(epoch, timezone.utc).isoformat()},
        "compatibility": {"platform": ["linux"], "arch": ["x86_64"], "python": ">=3.9",
                          "notes": "Verified on Rocky Linux 9.8, glibc 2.34, GCC 11 runtime; includes non-system dependency sources."},
        "files": files,
        "runtime": {"requires": [
            {"id": "python3", "kind": "executable", "probe": ["python3", "--version"], "minimum": "3.9", "required": True},
            {"id": "ctypes", "kind": "python-module", "module": "ctypes", "required": True},
            {"id": "libstdcpp", "kind": "file", "path": "/lib64/libstdc++.so.6", "required": True},
            {"id": "libgcc", "kind": "file", "path": "/lib64/libgcc_s.so.1", "required": True},
            {"id": "glibc", "kind": "file", "path": "/lib64/libc.so.6", "required": True}], "data_dirs": [], "env": {}},
        "entrypoints": [{"id": "server-ime-engine", "kind": "engine", "argv": ["{prefix}/bin/server-ime-engine"],
                         "description": "UTF-8 JSON Lines 转换会话服务"}],
        "install": {"link_dir": "bin", "retain_versions": 2}, "preserve": {"data_globs": []},
        "notes": "employee_id=engine; explicit user_data_dir is lexicon-owned persistent data; never remove it on upgrade/uninstall. Default invocation has no personal data writes. Sources for all bundled native dependencies are under engine/vendor/."}
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False)+"\n").encode()
    (output / "component-manifest.json").write_bytes(manifest_bytes)
    archive = output.parent / "server-ime-engine-0.4.0.tar.gz"
    with archive.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for path in [output / "component-manifest.json"] + sorted((output / "payload").rglob("*")):
                if not path.is_file():
                    continue
                info = tar.gettarinfo(str(path), str(path.relative_to(output)))
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = epoch
                with path.open("rb") as f:
                    tar.addfile(info, f)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(sha + "  " + archive.name + "\n")
    print(json.dumps({"employee_id": "engine", "bundle": str(archive), "sha256": sha,
                      "files": len(files), "payload_bytes": sum(f["size"] for f in files)}))


if __name__ == "__main__":
    main()
