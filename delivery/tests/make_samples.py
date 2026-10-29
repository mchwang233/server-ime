#!/usr/bin/env python3
"""构建隔离的样例 ime-bundle 安装包，专供安装工具自检使用。

这些包不是最终输入法：组件是 "ime-demo" 样例程序，仅包含一个打印版本的
可执行文件、少量配置与文档，用来验证安装/升级/回滚/卸载/校验/诊断逻辑。
所有产物写入 delivery/samples/，测试前缀写入 delivery/.check/。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLES = os.path.join(ROOT, "samples")
PACKAGES = os.path.join(SAMPLES, "packages")
MANIFESTS = os.path.join(SAMPLES, "manifests")
WORK = os.path.join(SAMPLES, "work")

FIXED_MTIME = 1730000000
BUNDLE_FORMAT = "ime-bundle/1"
MANIFEST_SCHEMA = "ime.component-manifest/1"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def demo_script(version):
    return '''#!/usr/bin/env python3
"""ime-demo %s：隔离样例组件，仅用于安装工具自检。"""

import json
import os
import sys

VERSION = "%s"


def data_summary():
    base = os.environ.get("IME_DATA_DIR")
    info = {"data_dir_configured": bool(base), "personal_files": 0, "learning_files": 0}
    if base and os.path.isdir(base):
        for name in ("personal", "learning"):
            path = os.path.join(base, name)
            if os.path.isdir(path):
                info[name + "_files"] = len([n for n in os.listdir(path) if os.path.isfile(os.path.join(path, n))])
    return info


def main(argv):
    if "--version" in argv:
        print("ime-demo " + VERSION)
        return 0
    if "--selftest" in argv:
        payload = {"version": VERSION}
        payload.update(data_summary())
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    if "--help" in argv:
        print("usage: ime-demo [--version|--selftest|--help]")
        return 0
    sys.stderr.write("usage: ime-demo [--version|--selftest|--help]\\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
''' % (version, version)


def settings_script(version):
    return '''#!/usr/bin/env python3
"""ime-demo-settings %s：样例设置入口。"""

import sys

VERSION = "%s"

if __name__ == "__main__":
    print("ime-demo-settings " + VERSION)
    sys.exit(0)
''' % (version, version)


def file_entry(content, mode="0644", kind="data", description=""):
    if isinstance(content, str):
        content = content.encode("utf-8")
    entry = {
        "data": content,
        "mode": mode,
        "kind": kind,
        "description": description,
    }
    return entry


def version_files(version):
    files = {
        "bin/ime-demo": file_entry(demo_script(version), "0755", "executable", "样例命令行入口"),
        "lib/ime_demo/__init__.py": file_entry(
            '"""ime-demo 样例库（隔离自检用）。"""\n\nVERSION = "%s"\n' % version,
            "0644",
            "library",
            "样例库",
        ),
        "share/ime/defaults.json": file_entry(
            json.dumps(
                {
                    "schema": "ime.sample-settings/1",
                    "version": version,
                    "candidate_page_size": 7 if version == "1.0.0" else 9,
                    "chinese_punctuation": True,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "0644",
            "config",
            "默认配置",
        ),
        "share/ime/README.txt": file_entry(
            "ime-demo %s 样例数据：仅用于 delivery 安装工具自检，不是真实输入法词库。\n" % version,
            "0644",
            "doc",
            "样例说明",
        ),
        "share/ime/locale/zh_CN.json": file_entry(
            json.dumps(
                {
                    "schema": "ime.sample-locale/1",
                    "candidate_window.title": "候选",
                    "settings.title": "输入法设置",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "0644",
            "locale",
            "界面文案",
        ),
    }
    if version != "1.0.0":
        files["share/ime/features.json"] = file_entry(
            json.dumps({"schema": "ime.sample-features/1", "fuzzy_pinyin": True, "shuangpin": "ziranma"}, indent=2, sort_keys=True)
            + "\n",
            "0644",
            "config",
            "新增能力配置",
        )
        files["bin/ime-demo-settings"] = file_entry(settings_script(version), "0755", "executable", "样例设置入口")
    return files


def entrypoints(version):
    entries = [
        {
            "id": "demo-cli",
            "kind": "cli",
            "argv": ["{prefix}/bin/ime-demo", "--version"],
            "description": "样例版本查询入口",
        }
    ]
    if version != "1.0.0":
        entries.append(
            {
                "id": "demo-settings",
                "kind": "panel",
                "argv": ["{prefix}/bin/ime-demo-settings"],
                "description": "样例设置入口",
            }
        )
    return entries


def base_manifest(component_id, name, version, files, entries, *, retain=2, notes=""):
    file_records = []
    for path in sorted(files):
        item = files[path]
        file_records.append(
            {
                "path": path,
                "sha256": sha256_bytes(item["data"]),
                "size": len(item["data"]),
                "mode": item["mode"],
                "kind": item["kind"],
                "description": item["description"],
            }
        )
    return {
        "schema": MANIFEST_SCHEMA,
        "component": {
            "id": component_id,
            "name": name,
            "version": version,
            "kind": "tool",
            "license": "MIT",
            "description": "隔离样例组件，仅用于安装工具自检，不代表最终输入法。",
        },
        "package": {
            "format": BUNDLE_FORMAT,
            "payload_root": "payload",
            "created_at": "2026-10-28T00:00:00Z",
            "builder": "delivery/tests/make_samples.py",
        },
        "compatibility": {"platform": ["linux"], "python": ">=3.6", "arch": ["x86_64", "aarch64"]},
        "files": file_records,
        "runtime": {
            "requires": [
                {
                    "id": "python3",
                    "kind": "executable",
                    "probe": ["python3", "--version"],
                    "minimum": "3.6",
                    "required": True,
                    "description": "样例组件的解释器",
                },
                {
                    "id": "json",
                    "kind": "python-module",
                    "module": "json",
                    "required": True,
                    "description": "标准库 JSON",
                },
            ],
            "env": {"IME_DATA_DIR": "{data_dir}"},
            "data_dirs": [
                {"path": "personal", "description": "个人词库与短语（安装/升级/卸载不得删除）", "preserve": True},
                {"path": "learning", "description": "学习与统计状态", "preserve": True},
            ],
        },
        "entrypoints": entries,
        "install": {"link_dir": "bin", "retain_versions": retain},
        "preserve": {"data_globs": ["personal/**", "learning/**"]},
        "notes": notes,
    }


def _tar_add(tar, name, data, mode=0o644, is_dir=False):
    info = tarfile.TarInfo(name)
    info.mtime = FIXED_MTIME
    info.uid = 0
    info.gid = 0
    info.uname = "ime"
    info.gname = "ime"
    info.mode = mode
    if is_dir:
        info.type = tarfile.DIRTYPE
        info.size = 0
        tar.addfile(info)
    else:
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def write_bundle(outdir, stem, manifest, files, *, tamper=None, extra_payload=None, payload_drop=(), sidecar_override=None):
    """写出 PACKAGE 与 .sha256 sidecar；tamper 在清单生成后篡改内容以测试校验失败。"""
    os.makedirs(outdir, exist_ok=True)
    package_path = os.path.join(outdir, stem + ".tar.gz")
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    payload_entries = {}
    for path, item in files.items():
        payload_entries[path] = item["data"]
    for path in payload_drop:
        payload_entries.pop(path, None)
    if tamper:
        victim, suffix = tamper
        if victim not in payload_entries:
            raise SystemExit("tamper target missing: %s" % victim)
        payload_entries[victim] = payload_entries[victim] + suffix
    if extra_payload:
        payload_entries.update(extra_payload)

    tmp_path = package_path + ".tmp"
    with tarfile.open(tmp_path, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        _tar_add(tar, "component-manifest.json", manifest_bytes, 0o644)
        _tar_add(tar, "payload", b"", 0o755, is_dir=True)
        dirs = set()
        for path in sorted(payload_entries):
            parts = path.split("/")[:-1]
            for index in range(1, len(parts) + 1):
                directory = "/".join(parts[:index])
                full = "payload/" + directory
                if full not in dirs:
                    dirs.add(full)
                    _tar_add(tar, full, b"", 0o755, is_dir=True)
        for path in sorted(payload_entries):
            item = files.get(path, {"mode": "0644"})
            mode = int(item.get("mode", "0644"), 8)
            _tar_add(tar, "payload/" + path, payload_entries[path], mode)
    os.replace(tmp_path, package_path)
    digest = hashlib.sha256(open(package_path, "rb").read()).hexdigest()
    if sidecar_override:
        digest = sidecar_override
    with open(package_path + ".sha256", "w", encoding="utf-8") as fh:
        fh.write(digest + "  " + os.path.basename(package_path) + "\n")
    return package_path


def build_demo(version, *, stem=None, tamper=None, sidecar_override=None, extra_payload=None, payload_drop=()):
    files = version_files(version)
    manifest = base_manifest("ime-demo", "隔离样例输入法组件", version, files, entrypoints(version))
    stem = stem or ("ime-demo-%s" % version)
    return write_bundle(
        PACKAGES,
        stem,
        manifest,
        files,
        tamper=tamper,
        sidecar_override=sidecar_override,
        extra_payload=extra_payload,
        payload_drop=payload_drop,
    )


def build_invalid_manifests():
    os.makedirs(MANIFESTS, exist_ok=True)
    good_files = version_files("1.0.0")
    good = base_manifest("ime-demo", "隔离样例输入法组件", "1.0.0", good_files, entrypoints("1.0.0"))
    with open(os.path.join(MANIFESTS, "good-component.json"), "w", encoding="utf-8") as fh:
        json.dump(good, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    variants = {}

    bad = json.loads(json.dumps(good))
    bad["files"][0]["path"] = "/etc/passwd"
    variants["bad-absolute-path.json"] = bad

    bad = json.loads(json.dumps(good))
    bad["files"][0]["sha256"] = "not-a-hex-digest"
    variants["bad-sha256.json"] = bad

    bad = json.loads(json.dumps(good))
    bad["files"][0]["path"] = "../escape.txt"
    variants["bad-traversal.json"] = bad

    bad = json.loads(json.dumps(good))
    bad["entrypoints"][0]["argv"] = ["{prefix}/bin/ime-missing", "--version"]
    variants["bad-entrypoint.json"] = bad

    bad = json.loads(json.dumps(good))
    del bad["runtime"]
    variants["bad-missing-runtime.json"] = bad

    bad = json.loads(json.dumps(good))
    bad["schema"] = "ime.component-manifest/2"
    variants["bad-schema.json"] = bad

    bad = json.loads(json.dumps(good))
    bad["files"].append(dict(bad["files"][0]))
    variants["bad-duplicate-file.json"] = bad

    for name, data in variants.items():
        with open(os.path.join(MANIFESTS, name), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")


def build_product_samples():
    """样例产品清单：用于验证汇总校验；真实产品清单见 manifest/product-manifest.json。"""
    sample = {
        "schema": "ime.product-manifest/1",
        "product": {
            "id": "ime-selfcheck",
            "name": "安装工具自检样例产品",
            "version": "1.0.0",
            "license": "MIT",
            "description": "只包含隔离样例组件的产品清单，用于验证打包汇总校验。",
        },
        "components": [
            {
                "id": "ime-demo",
                "employee_id": "delivery",
                "role": "样例组件",
                "status": "ready",
                "version": "1.0.0",
                "bundle": "packages/ime-demo-1.0.0.tar.gz",
                "entrypoints": ["demo-cli"],
                "data_dirs": ["personal", "learning"],
                "notes": "自检 fixture",
            }
        ],
        "notes": "样例产品清单，不代表最终输入法。",
    }
    with open(os.path.join(SAMPLES, "product-demo-ready.json"), "w", encoding="utf-8") as fh:
        json.dump(sample, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    broken = json.loads(json.dumps(sample))
    broken["components"][0]["version"] = "9.9.9"
    broken["components"][0]["bundle"] = "packages/ime-demo-9.9.9.tar.gz"
    with open(os.path.join(SAMPLES, "product-demo-missing.json"), "w", encoding="utf-8") as fh:
        json.dump(broken, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")

    mismatch = json.loads(json.dumps(sample))
    mismatch["components"][0]["version"] = "1.1.0"
    with open(os.path.join(SAMPLES, "product-demo-mismatch.json"), "w", encoding="utf-8") as fh:
        json.dump(mismatch, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def main():
    if os.path.isdir(PACKAGES):
        shutil.rmtree(PACKAGES)
    os.makedirs(PACKAGES, exist_ok=True)
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    built = []
    built.append(build_demo("1.0.0"))
    built.append(build_demo("1.1.0"))
    built.append(build_demo("1.2.0"))
    built.append(
        build_demo(
            "1.1.0",
            stem="ime-demo-1.1.0-tampered",
            tamper=("share/ime/defaults.json", b"\n// tampered after manifest hash\n"),
        )
    )
    built.append(build_demo("1.1.0", stem="ime-demo-1.1.0-badsidecar", sidecar_override="f" * 64))
    built.append(
        build_demo(
            "1.2.0",
            stem="ime-demo-1.2.0-extra-payload",
            extra_payload={"share/ime/undeclared.txt": b"not in manifest\n"},
        )
    )
    built.append(build_demo("1.2.0", stem="ime-demo-1.2.0-missing-file", payload_drop=("share/ime/features.json",)))
    build_invalid_manifests()
    build_product_samples()
    for path in built:
        size = os.path.getsize(path)
        print("built %s (%d bytes)" % (os.path.relpath(path, ROOT), size))
    print("manifests in %s" % os.path.relpath(MANIFESTS, ROOT))
    print("product samples in %s" % os.path.relpath(SAMPLES, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
