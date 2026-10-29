#!/usr/bin/env python3
"""校验发布包内容：许可材料、中文说明、工具、对应源码与运行代码哈希是否保持。

只读检查，不修改任何发布产物。用法：

    python3 delivery/tests/verify_release_content.py --json
    python3 delivery/tests/verify_release_content.py --baseline delivery/evidence/license-fix-<ts>

退出码：0 全部通过；1 存在失败项（失败项逐条打印）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DELIVERY = ROOT / "delivery"
DIST = DELIVERY / "dist"
sys.path.insert(0, str(DELIVERY / "lib"))

from ime_delivery.manifest import load_bundle  # noqa: E402

# 包内必须存在的许可/来源材料（工程根相对路径 → 载荷路径）。
LICENSE_MEMBERS = (
    ("engine/LICENSE", "engine/LICENSE"),
    ("platform/LICENSE", "platform/LICENSE"),
    ("integration/LICENSE", "integration/LICENSE"),
    ("lexicon/SOURCES.md", "lexicon/SOURCES.md"),
    ("interface/LICENSE", "interface/LICENSE"),
    ("interface/SOURCES.md", "interface/SOURCES.md"),
)
# 工作区中文完整文档（不入包，避免文档哈希与包哈希互相引用）。
WORKSPACE_DOCS = ("使用指南.md", "licenses.md", "feature-matrix.md", "install-lifecycle.md", "diagnostics-privacy.md", "evidence-index.md")
# 包内中文快速说明（由 ime-build 生成，内容不含包哈希）。
PAYLOAD_GUIDE = "share/ime/docs/README.zh_CN.md"
GUIDE_SECTIONS = ("安装", "启动与使用", "常见故障", "许可与来源")
# 源码包内必须存在的对应源码与构建材料。
SOURCE_REQUIRED = (
    "engine/vendor/libpinyin-2.6.0.tar.gz",
    "engine/vendor/libpinyin-2.6.0-4.el9.src.rpm",
    "engine/vendor/sources/glib2-2.68.4-19.el9_8.1.src.rpm",
    "engine/vendor/sources/libdb-5.3.28-57.el9_6.src.rpm",
    "engine/vendor/sources/pcre-8.44-4.el9.src.rpm",
    "engine/vendor.lock.json",
    "engine/LICENSE",
    "platform/LICENSE",
    "integration/LICENSE",
    "lexicon/SOURCES.md",
    "interface/LICENSE",
    "interface/SOURCES.md",
)
TOOLS = ("ime-build", "ime-install", "ime-diagnose", "ime-manifest", "ime-selfcheck", "ime-release-check")
# 允许与旧版本不同的载荷路径（仅元数据/文档；运行代码与数据必须逐字节不变）。
ALLOWED_CHANGED = {"share/ime/release.json", PAYLOAD_GUIDE}
FORBIDDEN_TEXT = ("未提供许可证文件", "发布阻断项")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Report:
    def __init__(self):
        self.checks = []

    def add(self, ident, ok, detail):
        self.checks.append({"id": ident, "ok": bool(ok), "detail": detail})
        return ok

    def failures(self):
        return [item for item in self.checks if not item["ok"]]


def check_sums(report):
    sums = {}
    for line in (DIST / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        sums[name] = digest
    bad = [name for name, digest in sums.items() if not (DIST / name).is_file() or sha256_file(DIST / name) != digest]
    listed = set(sums)
    on_disk = {p.name for p in DIST.iterdir() if p.is_file() and p.suffix != ".sha256" and p.name != "SHA256SUMS"}
    report.add("SHA256SUMS", not bad and listed == on_disk,
               {"files": len(sums), "bad": bad, "unlisted": sorted(on_disk - listed), "missing": sorted(listed - on_disk)})
    return sums


def check_package(report, version, baseline):
    package = DIST / ("server-ime-%s.tar.gz" % version)
    manifest = json.loads((DIST / ("server-ime-%s.component-manifest.json" % version)).read_text(encoding="utf-8"))
    by_path = {item["path"]: item for item in manifest["files"]}
    evidence = {"package": package.name, "sha256": sha256_file(package), "files": len(manifest["files"]),
                "payload_bytes": sum(item["size"] for item in manifest["files"])}
    # 1. 解包校验（复用安装工具的 load_bundle，逐文件 sha256）。
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / ("ime-verify-%s-%d" % (version, os.getpid()))
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        loaded, _payload, _root = load_bundle(str(package), str(tmp))
        report.add("%s.bundle" % version, loaded.version == version and len(loaded.files) == len(manifest["files"]),
                   {"version": loaded.version, "files": len(loaded.files), "manifest_sha256": loaded.sha256})
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
    # 2. 许可材料逐字节来自工作区原件。
    lic = {}
    for src_rel, dst_rel in LICENSE_MEMBERS:
        item = by_path.get(dst_rel)
        actual = sha256_file(ROOT / src_rel)
        lic[dst_rel] = bool(item) and item["sha256"] == actual and item["kind"] == "doc"
    report.add("%s.license_material" % version, all(lic.values()), lic)
    # 3. 包内中文快速说明（安装/启动/排查/许可）存在且不含哈希或占位。
    guide_item = by_path.get(PAYLOAD_GUIDE)
    guide_text = ""
    probe = Path(os.environ.get("TMPDIR", "/tmp")) / ("ime-guide-%s-%d" % (version, os.getpid()))
    probe.mkdir(parents=True, exist_ok=True)
    try:
        _loaded, payload_dir, _root = load_bundle(str(package), str(probe))
        guide_text = (Path(payload_dir) / PAYLOAD_GUIDE).read_text(encoding="utf-8")
    finally:
        import shutil

        shutil.rmtree(probe, ignore_errors=True)
    sections = [name for name in GUIDE_SECTIONS if name in guide_text]
    guide_ok = bool(guide_item) and len(sections) == len(GUIDE_SECTIONS) and not any(len(word) == 64 for word in guide_text.split())
    report.add("%s.payload_guide" % version, guide_ok,
               {"path": PAYLOAD_GUIDE, "sha256": guide_item["sha256"] if guide_item else None,
                "sections": sections, "bytes": len(guide_text.encode("utf-8"))})
    # 4. 包内不再出现许可占位。
    with tarfile.open(package, "r:gz") as tar:
        release = json.load(tar.extractfile("payload/share/ime/release.json"))
        report.add(version + ".external_manifest", json.load(tar.extractfile("component-manifest.json")) == manifest, "external manifest equals archive manifest")
    blob = json.dumps(release, ensure_ascii=False) + (DELIVERY / "docs" / "licenses.md").read_text(encoding="utf-8")
    hits = [word for word in FORBIDDEN_TEXT if word in blob]
    interface = next(item for item in release["components"] if item["id"] == "interface")
    report.add("%s.license_metadata" % version, not hits and interface.get("license") == "GPL-3.0-or-later",
               {"forbidden_hits": hits, "interface": interface, "product_license": release.get("entrypoint") and manifest["component"]["license"]})
    # 5. 与基线相比只有文档/许可/元数据变化。
    if baseline:
        old = json.loads((baseline / ("baseline-%s.component-manifest.json" % version)).read_text(encoding="utf-8"))
        before = {item["path"]: item["sha256"] for item in old["files"]}
        added = sorted(set(by_path) - set(before))
        removed = sorted(set(before) - set(by_path))
        changed = sorted(path for path in set(before) & set(by_path) if before[path] != by_path[path]["sha256"])
        allowed_added = {dst for _src, dst in LICENSE_MEMBERS} | {PAYLOAD_GUIDE}
        ok = not removed and set(changed) <= ALLOWED_CHANGED and set(added) <= allowed_added
        report.add("%s.runtime_unchanged" % version, ok,
                   {"added": added, "removed": removed, "changed": changed,
                    "runtime_files_compared": len(set(before) & set(by_path)) - len(changed)})
    return evidence


def check_sources(report, version):
    package = DIST / ("server-ime-%s-sources.tar.gz" % version)
    names = set()
    lic_bytes = b""
    with tarfile.open(package, "r:gz") as tar:
        for member in tar.getmembers():
            names.add(member.name.rstrip("/"))
            if member.name == "interface/LICENSE":
                lic_bytes = tar.extractfile(member).read()
    required = SOURCE_REQUIRED + tuple("delivery/bin/" + n for n in TOOLS) + (
        "engine/src/server_ime_engine/core.py", "engine/CMakeLists.txt", "engine/tools/build_bundle.py",
        "integration/tools/build_product.py", "integration/src/server_ime_product/cli.py",
        "interface/src/ime_interface/settings_ui.py", "platform/server_ime/controller.py",
        "lexicon/bin/lexicon", "delivery/lib/ime_delivery/installer.py", "delivery/docs/SOURCE-BUILD.md")
    # Check source bytes as well as member names, including every packaged project source.
    missing = [name for name in required if name not in names]
    with tarfile.open(package, "r:gz") as tar:
        mismatches = [m.name for m in tar.getmembers() if m.isfile()
                      and (not (ROOT / m.name).is_file() or
                           hashlib.sha256(tar.extractfile(m).read()).hexdigest() != sha256_file(ROOT / m.name))]
    forbidden = [n for n in names if set(n.split('/')) & {'__pycache__', '.check', 'build', 'evidence', 'browser-runtime'}]
    missing += mismatches + forbidden
    same = lic_bytes == (ROOT / "interface/LICENSE").read_bytes()
    report.add("%s.sources" % version, not missing and same,
               {"members": len(names), "missing": missing, "interface_license_identical": same,
                "sha256": sha256_file(package)})


def check_tools(report):
    tools = {}
    for name in TOOLS:
        path = DELIVERY / "bin" / name
        tools[name] = path.is_file() and os.access(path, os.X_OK)
    docs = {}
    for name in WORKSPACE_DOCS:
        path = DELIVERY / "docs" / name
        if not path.is_file():
            docs[name] = "missing"
            continue
        text = path.read_text(encoding="utf-8")
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
        docs[name] = "ok" if has_cjk and not any(word in text for word in FORBIDDEN_TEXT) else "placeholder-or-empty"
    report.add("tools", all(tools.values()), tools)
    report.add("chinese_docs_in_workspace", all(value == "ok" for value in docs.values()), docs)


def check_records(report, sums, delivery=None):
    base = Path(delivery or DELIVERY).resolve()
    try:
        lock = json.loads((base / "manifest/lock.json").read_text())
        product = json.loads((base / "manifest/product-manifest.json").read_text())
        assert lock["path_base"] == "delivery"
        assert product["path_base"] == "manifest-directory"
        def resolve(value, directory):
            path = (directory / value).resolve()
            assert path.is_relative_to(base), "path escapes delivery: " + str(path)
            assert path.is_file(), "missing: " + str(path)
            return path
        def hashed(value, digest, directory):
            path = resolve(value, directory)
            assert sha256_file(path) == digest, "hash mismatch: " + str(path)
            return path
        package = hashed(lock["package"]["path"], lock["package"]["sha256"], base)
        sources = hashed(lock["sources"]["path"], lock["sources"]["sha256"], base)
        record_path = hashed(lock["build_record"], lock["build_record_sha256"], base)
        record = json.loads(record_path.read_text())
        assert record["version"] == lock["version"]
        assert record["inputs"] == lock["components"]
        assert record["locked_runtime"] == lock["locked_runtime"]
        assert record["license_material"] == lock["license_material"]
        for key, expected in (("package", package), ("sources", sources)):
            assert hashed(record[key]["path"], record[key]["sha256"], base) == expected
            assert record[key]["bytes"] == expected.stat().st_size
        c = product["components"][0]
        mbase = base / "manifest"
        assert hashed(c["bundle"], c["sha256"], mbase) == package
        assert c["version"] == lock["version"] == product["product"]["version"]
        artifacts = c["artifacts"]
        assert hashed(artifacts["sources"], artifacts["sources_sha256"], mbase) == sources
        manifest = hashed(artifacts["manifest"], artifacts["manifest_file_sha256"], mbase)
        assert sha256_file(manifest) == record["package"]["manifest_sha256"]
        assert len(json.loads(manifest.read_text())["files"]) == lock["package"]["files"] == record["package"]["files"]
        assert resolve(artifacts["build_record"], mbase) == record_path
        assert resolve(artifacts["version_lock"], mbase) == base / "manifest/lock.json"
        assert resolve(artifacts["sha256sums"], mbase) == base / "dist/SHA256SUMS"
        hashed(c["upgrade_test_package"]["path"], c["upgrade_test_package"]["sha256"], mbase)
        report.add("records", True, {"package": str(package), "sources": str(sources), "build_record": str(record_path)})
    except (AssertionError, OSError, ValueError, KeyError) as exc:
        report.add("records", False, str(exc))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="verify_release_content", description="发布包内容与许可材料校验")
    parser.add_argument("--baseline", default=None, help="基线目录（含 baseline-<版本>.component-manifest.json）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = Report()
    sums = check_sums(report)
    packages = [check_package(report, version, Path(args.baseline) if args.baseline else None) for version in ("0.1.0", "0.1.1")]
    for version in ("0.1.0", "0.1.1"):
        check_sources(report, version)
    check_tools(report)
    check_records(report, sums)

    result = {
        "schema": "ime.release-content-check/1",
        "checks": report.checks,
        "failures": len(report.failures()),
        "result": "PASS" if not report.failures() else "FAIL",
        "packages": packages,
    }
    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        for item in report.checks:
            sys.stdout.write("%-4s %s\n" % ("ok" if item["ok"] else "FAIL", item["id"]))
        sys.stdout.write("result: %s (%d 项检查，%d 失败)\n" % (result["result"], len(report.checks), len(report.failures())))
    return 0 if not report.failures() else 1


if __name__ == "__main__":
    sys.exit(main())
