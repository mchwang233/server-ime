"""组件交付清单（component manifest）的校验、打包读取与载荷校验。

清单 schema 见 manifest/component-manifest.schema.json，人类可读说明见
manifest/README.md。这里不使用第三方 jsonschema，而是实现等价的显式校验，
以便在没有网络/无额外依赖的服务器上直接运行。
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import tarfile

from .util import (
    ImeError,
    is_sha256,
    safe_relpath,
    sha256_bytes,
    sha256_file,
    safe_relpath as _safe_relpath,
)

MANIFEST_SCHEMA = "ime.component-manifest/1"
BUNDLE_FORMAT = "ime-bundle/1"
COMPONENT_KINDS = {"product", "engine", "frontend", "data", "tool"}
FILE_KINDS = {"executable", "library", "data", "config", "doc", "locale"}
REQUIRE_KINDS = {"executable", "python-module", "file"}
ENTRY_KINDS = {"cli", "engine", "panel", "service", "setup"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
LINK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}([.-][0-9A-Za-z.-]+)?$")
MODE_RE = re.compile(r"^0[0-7]{3}$")
MAX_PAYLOAD_FILES = 20000
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024 * 1024

REQUIRED_TOP = ("schema", "component", "package", "compatibility", "files", "runtime", "entrypoints")


def _fail(message, details=None):
    raise ImeError("manifest", message, 5, details)


def _need(cond, message, details=None):
    if not cond:
        _fail(message, details)


def _str(value, what, allow_empty=False):
    _need(isinstance(value, str), "%s 必须是字符串" % what)
    if not allow_empty:
        _need(value.strip() != "", "%s 不能为空" % what)
    return value


def _dict(value, what):
    _need(isinstance(value, dict), "%s 必须是对象" % what)
    return value


def _list(value, what, non_empty=False):
    _need(isinstance(value, list), "%s 必须是数组" % what)
    if non_empty:
        _need(len(value) > 0, "%s 不能为空" % what)
    return value


def _check_version(value, what):
    _str(value, what)
    _need(bool(VERSION_RE.match(value)), "%s 不是合法版本号: %r" % (what, value))


def _check_mode(value, what):
    _str(value, what)
    _need(bool(MODE_RE.match(value)), "%s 必须是形如 0644/0755 的八进制模式: %r" % (what, value))
    _need(int(value, 8) & 0o7777 <= 0o777, "%s 不允许 setuid/setgid/sticky 位: %r" % (what, value))


def _check_glob(pattern, what):
    _str(pattern, what)
    _need(not pattern.startswith("/") and "\\" not in pattern, "%s 必须是相对 glob: %r" % (what, pattern))
    parts = pattern.split("/")
    _need(".." not in parts, "%s 不允许包含 ..: %r" % (what, pattern))


def normalize_member(name):
    """把 tar 成员名规范化为干净相对路径；非法返回 None。"""
    if not isinstance(name, str) or not name:
        return None
    while name.startswith("./"):
        name = name[2:]
    if name.startswith("/") or name.endswith("/"):
        return None
    cleaned = posixpath.normpath(name)
    if cleaned in (".", "") or cleaned.startswith("../") or "/../" in cleaned:
        return None
    if cleaned.split("/")[0] == "..":
        return None
    return cleaned


class Manifest(object):
    def __init__(self, data, raw_bytes):
        self.data = data
        self.raw = raw_bytes
        self.sha256 = sha256_bytes(raw_bytes)

    @property
    def component_id(self):
        return self.data["component"]["id"]

    @property
    def version(self):
        return self.data["component"]["version"]

    @property
    def name(self):
        return self.data["component"]["name"]

    @property
    def files(self):
        return self.data["files"]

    @property
    def entrypoints(self):
        return self.data["entrypoints"]

    @property
    def runtime(self):
        return self.data["runtime"]

    @property
    def link_dir(self):
        return self.data.get("install", {}).get("link_dir", "bin")

    @property
    def retain_versions(self):
        return int(self.data.get("install", {}).get("retain_versions", 2))

    @property
    def data_dirs(self):
        return self.runtime.get("data_dirs", [])

    def file_map(self):
        return {item["path"]: item for item in self.files}

    def link_target_rel(self, entry):
        return "../ime/current/" + entry["file_rel"]

    def to_state_entry(self, *, installed_at, package_sha256, source_package):
        return {
            "component_id": self.component_id,
            "component_name": self.name,
            "component_kind": self.data["component"].get("kind"),
            "version": self.version,
            "installed_at": installed_at,
            "manifest_sha256": self.sha256,
            "package_sha256": package_sha256,
            "source_package": source_package,
            "files": [
                {
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "size": item["size"],
                    "mode": item["mode"],
                    "kind": item["kind"],
                }
                for item in self.files
            ],
            "entrypoints": self.entrypoints,
            "runtime": self.runtime,
        }


def validate_manifest_data(data, payload_dir=None):
    """校验清单结构；给出 payload_dir 时同时校验文件内容。返回 Manifest。"""
    _dict(data, "清单")
    for key in REQUIRED_TOP:
        _need(key in data, "清单缺少必需字段 %s" % key)
    _need(data["schema"] == MANIFEST_SCHEMA, "不支持的清单 schema: %r（期望 %s）" % (data.get("schema"), MANIFEST_SCHEMA))

    component = _dict(data["component"], "component")
    _str(component.get("id"), "component.id")
    _need(bool(ID_RE.match(component["id"])), "component.id 非法: %r" % component["id"])
    _str(component.get("name"), "component.name")
    _check_version(component.get("version"), "component.version")
    _str(component.get("kind"), "component.kind")
    _need(component["kind"] in COMPONENT_KINDS, "component.kind 必须是 %s 之一" % "/".join(sorted(COMPONENT_KINDS)))
    _str(component.get("license"), "component.license")
    _str(component.get("description"), "component.description")

    package = _dict(data["package"], "package")
    _need(package.get("format") == BUNDLE_FORMAT, "package.format 必须为 %s" % BUNDLE_FORMAT)
    payload_root = _str(package.get("payload_root", "payload"), "package.payload_root")
    safe_relpath(payload_root, "package.payload_root")

    compat = _dict(data["compatibility"], "compatibility")
    platforms = _list(compat.get("platform"), "compatibility.platform", non_empty=True)
    _need(all(isinstance(x, str) and x for x in platforms), "compatibility.platform 必须是非空字符串数组")
    _need("linux" in platforms, "compatibility.platform 必须包含 linux（本工具只支持 Linux）")
    if "python" in compat:
        _str(compat["python"], "compatibility.python")
    if "arch" in compat:
        arches = _list(compat["arch"], "compatibility.arch")
        _need(all(isinstance(x, str) and x for x in arches), "compatibility.arch 必须为字符串数组")

    files = _list(data["files"], "files", non_empty=True)
    _need(len(files) <= MAX_PAYLOAD_FILES, "清单文件数超过上限 %d" % MAX_PAYLOAD_FILES)
    seen_paths = set()
    link_names = {}
    total_size = 0
    for index, item in enumerate(files):
        what = "files[%d]" % index
        _dict(item, what)
        path = safe_relpath(item.get("path"), what + ".path")
        _need(path not in seen_paths, "files 中存在重复路径: %s" % path)
        seen_paths.add(path)
        _need(is_sha256(item.get("sha256")), "%s.sha256 必须是 64 位小写十六进制" % what)
        size = item.get("size")
        _need(isinstance(size, int) and not isinstance(size, bool) and size >= 0, "%s.size 必须是非负整数" % what)
        total_size += size
        _check_mode(item.get("mode"), what + ".mode")
        _str(item.get("kind"), what + ".kind")
        _need(item["kind"] in FILE_KINDS, "%s.kind 必须是 %s 之一" % (what, "/".join(sorted(FILE_KINDS))))
        if item["kind"] == "executable":
            _need(int(item["mode"], 8) & 0o111, "%s 声明为 executable 但 mode 无可执行位" % what)
        if "description" in item:
            _str(item["description"], what + ".description", allow_empty=True)
        base = path.rsplit("/", 1)[-1]
        if item["kind"] == "executable":
            _need(base not in link_names, "可执行文件名重复，无法生成唯一启动入口: %s" % base)
            link_names[base] = path
    _need(total_size <= MAX_PAYLOAD_BYTES, "载荷总大小超过上限 %d 字节" % MAX_PAYLOAD_BYTES)

    runtime = _dict(data["runtime"], "runtime")
    requires = _list(runtime.get("requires", []), "runtime.requires")
    req_ids = set()
    for index, item in enumerate(requires):
        what = "runtime.requires[%d]" % index
        _dict(item, what)
        rid = _str(item.get("id"), what + ".id")
        _need(rid not in req_ids, "runtime.requires 中 id 重复: %s" % rid)
        req_ids.add(rid)
        _str(item.get("kind"), what + ".kind")
        _need(item["kind"] in REQUIRE_KINDS, "%s.kind 必须是 %s 之一" % (what, "/".join(sorted(REQUIRE_KINDS))))
        if item["kind"] == "executable":
            probe = _list(item.get("probe"), what + ".probe", non_empty=True)
            _need(all(isinstance(x, str) and x for x in probe), "%s.probe 必须是非空字符串数组" % what)
        if item["kind"] == "python-module":
            _str(item.get("module", item.get("id")), what + ".module")
        if item["kind"] == "file":
            _str(item.get("path"), what + ".path")
        if "minimum" in item:
            _str(item["minimum"], what + ".minimum")
        if "required" in item:
            _need(isinstance(item["required"], bool), "%s.required 必须是布尔值" % what)
        if "description" in item:
            _str(item["description"], what + ".description", allow_empty=True)
    env = runtime.get("env", {})
    _dict(env, "runtime.env")
    for key, value in env.items():
        _str(key, "runtime.env 键")
        _str(value, "runtime.env[%s]" % key, allow_empty=True)
        _need(not re.search(r"(?i)(password|passwd|secret|token|api[_-]?key)", key), "runtime.env 不允许携带凭据类变量: %s" % key)
    data_dirs = _list(runtime.get("data_dirs", []), "runtime.data_dirs")
    seen_data = set()
    for index, item in enumerate(data_dirs):
        what = "runtime.data_dirs[%d]" % index
        _dict(item, what)
        path = safe_relpath(item.get("path"), what + ".path")
        _need(path not in seen_data, "runtime.data_dirs 路径重复: %s" % path)
        seen_data.add(path)
        _str(item.get("description"), what + ".description")
        if "preserve" in item:
            _need(isinstance(item["preserve"], bool), "%s.preserve 必须是布尔值" % what)

    entrypoints = _list(data["entrypoints"], "entrypoints", non_empty=True)
    seen_ids = set()
    computed = []
    for index, item in enumerate(entrypoints):
        what = "entrypoints[%d]" % index
        _dict(item, what)
        eid = _str(item.get("id"), what + ".id")
        _need(eid not in seen_ids, "entrypoints id 重复: %s" % eid)
        seen_ids.add(eid)
        _str(item.get("kind"), what + ".kind")
        _need(item["kind"] in ENTRY_KINDS, "%s.kind 必须是 %s 之一" % (what, "/".join(sorted(ENTRY_KINDS))))
        argv = _list(item.get("argv"), what + ".argv", non_empty=True)
        _need(all(isinstance(x, str) and x for x in argv), "%s.argv 必须是非空字符串数组" % what)
        _need(argv[0].startswith("{prefix}/"), "%s.argv[0] 必须以 {prefix}/ 开头: %r" % (what, argv[0]))
        rest = argv[0][len("{prefix}/"):]
        _need(rest.startswith("bin/") or rest.startswith("ime/current/"), "%s.argv[0] 必须指向 {prefix}/bin/<名> 或 {prefix}/ime/current/<路径>" % what)
        if rest.startswith("bin/"):
            name = rest[len("bin/"):]
            _need(bool(LINK_NAME_RE.match(name)), "%s 启动入口名非法: %r" % (what, name))
            _need(name in link_names, "%s 指向的 bin/%s 没有对应的 executable 文件" % (what, name))
            file_rel = link_names[name]
            link_name = name
        else:
            file_rel = rest[len("ime/current/"):]
            _need(file_rel in seen_paths, "%s 指向的 %s 不在 files 中" % (what, file_rel))
            link_name = file_rel.rsplit("/", 1)[-1]
            _need(link_names.get(link_name) == file_rel, "%s 目标 %s 未声明为可执行文件" % (what, file_rel))
        if "description" in item:
            _str(item["description"], what + ".description", allow_empty=True)
        e_env = item.get("env", {})
        _dict(e_env, "entrypoints[%d].env" % index)
        for key, value in e_env.items():
            _str(key, "%s.env 键" % what)
            _str(value, "%s.env[%s]" % (what, key), allow_empty=True)
        computed.append(
            {
                "id": eid,
                "kind": item["kind"],
                "argv": list(argv),
                "file_rel": file_rel,
                "link_name": link_name,
                "link_rel": "bin/" + link_name,
                "description": item.get("description", ""),
                "env": dict(e_env),
            }
        )

    install = _dict(data.get("install", {}), "install")
    link_dir = _str(install.get("link_dir", "bin"), "install.link_dir")
    _need(bool(LINK_NAME_RE.match(link_dir)), "install.link_dir 必须是单级目录名: %r" % link_dir)
    _need(link_dir == "bin", "当前实现只支持 install.link_dir=bin")
    retain = install.get("retain_versions", 2)
    _need(isinstance(retain, int) and not isinstance(retain, bool) and 1 <= retain <= 10, "install.retain_versions 必须是 1..10 的整数")

    preserve = _dict(data.get("preserve", {}), "preserve")
    for index, pattern in enumerate(_list(preserve.get("data_globs", []), "preserve.data_globs")):
        _check_glob(pattern, "preserve.data_globs[%d]" % index)

    if "notes" in data:
        _str(data["notes"], "notes", allow_empty=True)

    manifest = Manifest(data, json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    manifest.data["entrypoints"] = computed  # 规范化后的启动入口（含 link/file 映射）
    if payload_dir is not None:
        verify_payload(manifest, payload_dir)
    return manifest


def verify_payload(manifest, payload_dir):
    """校验 payload 与清单逐文件一致，且没有清单之外的额外文件。"""
    if not os.path.isdir(payload_dir):
        _fail("payload 目录不存在: %s" % payload_dir)
    declared = {item["path"]: item for item in manifest.files}
    found = {}
    for base, dirs, names in os.walk(payload_dir):
        dirs.sort()
        for name in list(dirs):
            full = os.path.join(base, name)
            if os.path.islink(full):
                _fail("payload 中不允许符号链接目录: %s" % os.path.relpath(full, payload_dir))
        for name in sorted(names):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, payload_dir).replace(os.sep, "/")
            if os.path.islink(full):
                _fail("payload 中不允许符号链接文件: %s" % rel)
            found[rel] = full
    extra = sorted(set(found) - set(declared))
    missing = sorted(set(declared) - set(found))
    if missing:
        _fail("payload 缺少清单声明的文件", missing)
    if extra:
        _fail("payload 含有清单未声明的文件", extra)
    for path, item in sorted(declared.items()):
        full = found[path]
        actual_size = os.path.getsize(full)
        if actual_size != item["size"]:
            _fail("文件大小与清单不符: %s（实际 %d，清单 %d）" % (path, actual_size, item["size"]))
        actual_hash = sha256_file(full)
        if actual_hash != item["sha256"]:
            _fail("文件校验值不符: %s（实际 %s，清单 %s）" % (path, actual_hash, item["sha256"]))
    return True


def load_manifest_file(path, payload_dir=None):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ImeError("manifest", "无法读取清单 %s: %s" % (path, exc), 5)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ImeError("manifest", "清单不是合法 JSON: %s: %s" % (path, exc), 5)
    return validate_manifest_data(data, payload_dir)


def verify_package_sha256(package_path, expected):
    actual = sha256_file(package_path)
    if actual != expected:
        raise ImeError(
            "package",
            "安装包整体校验值不符: %s（实际 %s，期望 %s）" % (os.path.basename(package_path), actual, expected),
            5,
        )
    return actual


def extract_bundle(package_path, dest_dir):
    """安全解包 ime-bundle：拒绝绝对路径、..、链接与异常成员。"""
    try:
        tar = tarfile.open(package_path, "r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise ImeError("package", "无法读取安装包 %s: %s" % (package_path, exc), 5)
    total = 0
    count = 0
    seen = set()
    with tar:
        for member in tar:
            if not member.isfile() and not member.isdir():
                raise ImeError("package", "安装包中不允许链接或特殊文件: %s" % member.name, 5)
            name = normalize_member(member.name)
            if name is None:
                raise ImeError("package", "安装包成员路径非法: %r" % member.name, 5)
            if name in seen:
                raise ImeError("package", "安装包成员重复: %s" % name, 5)
            seen.add(name)
            target = os.path.join(dest_dir, name)
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            count += 1
            total += member.size
            if count > MAX_PAYLOAD_FILES or total > MAX_PAYLOAD_BYTES:
                raise ImeError("package", "安装包内容超过上限", 5)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                raise ImeError("package", "无法读取安装包成员: %s" % name, 5)
            with src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            mode = (member.mode & 0o777) or 0o644
            os.chmod(target, mode)
    if not os.path.isfile(os.path.join(dest_dir, "component-manifest.json")):
        raise ImeError("package", "安装包缺少 component-manifest.json", 5)
    return dest_dir


def load_bundle(package_path, work_dir):
    """解包并校验，返回 (manifest, payload_dir, bundle_root)。"""
    bundle_root = os.path.join(work_dir, "bundle")
    os.makedirs(bundle_root, exist_ok=True)
    extract_bundle(package_path, bundle_root)
    manifest_path = os.path.join(bundle_root, "component-manifest.json")
    with open(manifest_path, "rb") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ImeError("manifest", "清单不是合法 JSON: %s" % exc, 5)
    payload_root = "payload"
    if isinstance(data, dict) and isinstance(data.get("package"), dict):
        payload_root = data["package"].get("payload_root", "payload")
    payload_dir = os.path.join(bundle_root, payload_root)
    manifest = validate_manifest_data(data, payload_dir)
    return manifest, payload_dir, bundle_root
