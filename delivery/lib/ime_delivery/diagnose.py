"""诊断入口：只输出环境事实、安装状态、文件校验值、依赖探测与数据目录清单。

隐私约束：本模块从不读取文件内容用于展示，也从不拼接词条或按键文本到输出；
数据目录只列出相对路径、大小、权限与校验值（哈希），并显式声明不含输入内容。
"""

from __future__ import annotations

import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys

from . import TOOL_VERSION
from . import policy
from .installer import Layout, _is_managed_link, _staging_leftovers, _version_dirs, verify_version_files
from .state import load_journal, load_state
from .util import ImeError, human_bytes, sha256_file, utc_now, within

DIAGNOSE_SCHEMA = "ime.diagnose/1"
PRIVACY_NOTE = "本报告不含任何输入文本或个人词条内容：仅包含路径、大小、权限与校验值。"
PROBE_TIMEOUT = 8
DATA_FILE_LIMIT = 500


def _probe_executable(item):
    probe = item.get("probe") or []
    if not probe:
        return "error", "清单未提供 probe", None
    found = shutil.which(probe[0])
    if not found:
        return "missing", "未在 PATH 中找到 %s" % probe[0], None
    if len(probe) == 1:
        return "ok", found, None
    try:
        proc = subprocess.run(
            probe,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=PROBE_TIMEOUT,
            check=False,
            env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "error", "无法执行探测命令 %s: %s" % (probe[0], exc), None
    first = (proc.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    text = first[0][:120] if first else ""
    if proc.returncode != 0:
        return "error", "探测命令退出码 %d: %s" % (proc.returncode, text), text
    minimum = item.get("minimum")
    if minimum:
        got = re.search(r"(\d+(?:\.\d+)+)", text)
        if not got:
            return "warn", "无法从输出解析版本: %s" % text, text
        if _version_tuple(got.group(1)) < _version_tuple(minimum):
            return "error", "版本 %s 低于要求的 %s" % (got.group(1), minimum), text
    return "ok", text or found, text


def _version_tuple(value):
    parts = []
    for piece in re.split(r"[.\-+]", value):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            break
    return tuple(parts)


def _probe_require(item, prefix, data_dir):
    kind = item.get("kind")
    if kind == "executable":
        return _probe_executable(item)
    if kind == "python-module":
        module = item.get("module") or item.get("id")
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, ValueError) as exc:
            return "error", "无法查询模块 %s: %s" % (module, exc), None
        if spec is None:
            return "missing", "Python 模块 %s 不可用" % module, None
        return "ok", "Python 模块 %s 可用" % module, None
    if kind == "file":
        path = str(item.get("path", ""))
        path = path.replace("{prefix}", prefix).replace("{data_dir}", data_dir or "")
        if not os.path.isabs(path):
            path = os.path.join(prefix, path)
        if os.path.exists(path):
            return "ok", path, None
        return "missing", "缺少文件 %s" % path, None
    return "error", "未知依赖类型 %s" % kind, None


def _data_inventory(data_dir):
    inventory = {"path": data_dir, "exists": os.path.isdir(data_dir), "files": [], "truncated": False}
    if not inventory["exists"]:
        return inventory
    st = os.stat(data_dir)
    inventory["mode"] = oct(st.st_mode & 0o777)
    inventory["world_accessible"] = bool(st.st_mode & 0o077)
    entries = []
    for base, dirs, names in os.walk(data_dir):
        dirs.sort()
        for name in sorted(names):
            entries.append(os.path.join(base, name))
            if len(entries) > DATA_FILE_LIMIT:
                inventory["truncated"] = True
                break
        if inventory["truncated"]:
            break
    seen = set()
    for full in entries:
        rel = os.path.relpath(full, data_dir)
        if rel in seen:
            continue
        seen.add(rel)
        record = {"path": rel}
        try:
            if os.path.islink(full):
                record["kind"] = "symlink"
                record["size"] = 0
            else:
                record["kind"] = "file"
                record["size"] = os.path.getsize(full)
                record["sha256"] = sha256_file(full)
            record["mode"] = oct(os.stat(full).st_mode & 0o777)
        except OSError as exc:
            record["error"] = str(exc)
        inventory["files"].append(record)
    inventory["count"] = len(inventory["files"])
    inventory["total_bytes"] = sum(item.get("size", 0) for item in inventory["files"])
    return inventory


def collect(prefix, data_dir=None, *, allowed_roots=(), include_hashes=True):
    report = {
        "schema": DIAGNOSE_SCHEMA,
        "tool": "ime-install",
        "tool_version": TOOL_VERSION,
        "generated_at": utc_now(),
        "privacy": PRIVACY_NOTE,
        "environment": {},
        "policy": {},
        "install": {},
        "files": {},
        "runtime": [],
        "entrypoints": [],
        "data": {},
        "warnings": [],
        "errors": [],
    }
    report["environment"] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "uid": os.getuid(),
        "euid": os.geteuid(),
        "is_root": os.geteuid() == 0,
    }

    try:
        prefix_canon = policy.check_prefix(prefix, allowed_roots)
        report["policy"]["prefix"] = {"path": prefix_canon, "accepted": True}
    except ImeError as exc:
        report["policy"]["prefix"] = {"path": str(prefix), "accepted": False, "message": exc.message}
        report["errors"].append(exc.message)
        prefix_canon = os.path.realpath(os.path.abspath(str(prefix)))
    lay = Layout(prefix_canon)

    state = None
    try:
        state = load_state(lay)
    except ImeError as exc:
        report["errors"].append(exc.message)
    journal = load_journal(lay)
    current = state.get("current") if state else None
    report["install"] = {
        "prefix": prefix_canon,
        "installed": state is not None,
        "current": current,
        "previous": state.get("previous") if state else None,
        "data_dir": (state or {}).get("data_dir"),
        "versions": [],
        "pending_transaction": journal,
        "staging_leftovers": [os.path.basename(path) for path in _staging_leftovers(lay)],
    }
    if state:
        for version, entry in sorted(state.get("versions", {}).items()):
            version_dir = os.path.join(lay.versions, version)
            report["install"]["versions"].append(
                {
                    "version": version,
                    "component": entry.get("component_id"),
                    "installed_at": entry.get("installed_at"),
                    "present": os.path.isdir(version_dir),
                    "files": len(entry.get("files", [])),
                    "size": sum(int(item.get("size", 0)) for item in entry.get("files", [])),
                }
            )
    orphans = [name for name in _version_dirs(lay) if state and name not in state.get("versions", {})]
    if orphans:
        report["install"]["orphan_version_dirs"] = orphans
        report["warnings"].append("存在未被安装状态引用的版本目录: %s" % ", ".join(orphans))
    if journal:
        report["warnings"].append("存在未完成的事务 %s（阶段 %s）；请运行 ime-install recover" % (journal.get("txid"), journal.get("phase")))
    if (state or {}).get("prefix_mismatch"):
        report["warnings"].append("安装状态记录的前缀与当前路径不同（前缀可能被移动），请复核")

    effective_data = data_dir or (state or {}).get("data_dir")
    if effective_data:
        try:
            effective_data = policy.check_data_dir(effective_data, prefix_canon, allowed_roots)
            report["policy"]["data_dir"] = {"path": effective_data, "accepted": True}
        except ImeError as exc:
            report["policy"]["data_dir"] = {"path": str(effective_data), "accepted": False, "message": exc.message}
            report["errors"].append(exc.message)
    report["data"] = _data_inventory(effective_data) if effective_data else {"exists": False, "note": "未配置运行数据目录"}
    if report["data"].get("world_accessible"):
        report["warnings"].append("运行数据目录权限过宽（%s），建议 chmod 700" % report["data"].get("mode"))
    if effective_data and not report["data"].get("exists"):
        report["warnings"].append("运行数据目录不存在: %s" % effective_data)

    if state and current:
        entry = state["versions"].get(current, {})
        version_dir = os.path.join(lay.versions, current)
        drift = verify_version_files(version_dir, entry.get("files", []))
        report["files"] = {
            "version": current,
            "checked": len(entry.get("files", [])),
            "drift": drift,
            "ok": not drift,
        }
        if drift:
            report["errors"].append("当前版本有 %d 个文件与安装记录不一致" % len(drift))
        for item in entry.get("runtime", {}).get("requires", []):
            status, detail, raw = _probe_require(item, prefix_canon, effective_data or "")
            required = item.get("required", True)
            record = {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "required": required,
                "status": status,
                "detail": detail,
            }
            if raw:
                record["probe_output"] = raw[:120]
            report["runtime"].append(record)
            if status in ("missing", "error") and required:
                report["errors"].append("运行依赖 %s 不可用: %s" % (item.get("id"), detail))
        for item in entry.get("entrypoints", []):
            argv = [str(token).replace("{prefix}", prefix_canon).replace("{data_dir}", effective_data or "") for token in item.get("argv", [])]
            link_path = os.path.join(prefix_canon, item.get("link_rel", ""))
            executable = bool(argv) and os.path.isfile(argv[0]) and os.access(argv[0], os.X_OK)
            record = {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "link": item.get("link_rel"),
                "link_present": os.path.lexists(link_path),
                "link_managed": _is_managed_link(link_path, lay),
                "argv0": argv[0] if argv else None,
                "executable": executable,
            }
            report["entrypoints"].append(record)
            if not record["link_present"] or not record["link_managed"] or not executable:
                report["errors"].append("启动入口 %s 不可用" % item.get("id"))
    else:
        report["warnings"].append("前缀 %s 中没有可用的安装记录" % prefix_canon)

    report["ok"] = not report["errors"]
    report["summary"] = {
        "installed": state is not None,
        "current": current,
        "files_ok": report.get("files", {}).get("ok", None),
        "data_files": report["data"].get("count", 0),
        "errors": len(report["errors"]),
        "warnings": len(report["warnings"]),
    }
    return report


def render_text(report):
    lines = []
    lines.append("输入法安装诊断 (ime-diagnose %s)" % report["tool_version"])
    lines.append("时间: %s" % report["generated_at"])
    lines.append("隐私: %s" % report["privacy"])
    env = report["environment"]
    lines.append("")
    lines.append("[环境]")
    lines.append("  python: %s | platform: %s | uid: %s | root: %s" % (env["python"], env["platform"], env["uid"], env["is_root"]))
    pol = report["policy"]
    for key in ("prefix", "data_dir"):
        if key in pol:
            item = pol[key]
            state_text = "通过" if item.get("accepted") else "拒绝: %s" % item.get("message")
            lines.append("  %s: %s (%s)" % (key, item.get("path"), state_text))
    lines.append("")
    install = report["install"]
    lines.append("[安装状态]")
    lines.append("  installed: %s | current: %s | previous: %s" % (install.get("installed"), install.get("current"), install.get("previous")))
    for row in install.get("versions", []):
        lines.append(
            "  版本 %-10s 组件 %-12s 文件 %3d 大小 %-10s 目录存在 %s 安装于 %s"
            % (row["version"], row["component"], row["files"], human_bytes(row["size"]), row["present"], row["installed_at"])
        )
    if install.get("pending_transaction"):
        lines.append("  未完成事务: %s" % install["pending_transaction"].get("txid"))
    files = report.get("files") or {}
    lines.append("")
    lines.append("[文件校验]")
    if files:
        lines.append("  版本 %s: 检查 %d 个文件, 结果 %s" % (files["version"], files["checked"], "一致" if files["ok"] else "不一致"))
        for item in files["drift"][:20]:
            lines.append("  漂移: %s (%s)" % (item["path"], item["reason"]))
    else:
        lines.append("  未安装，跳过")
    lines.append("")
    lines.append("[运行依赖]")
    if report["runtime"]:
        for item in report["runtime"]:
            lines.append("  %-14s %-16s %-8s %s" % (item["id"], item["kind"], item["status"], item["detail"]))
    else:
        lines.append("  无记录")
    lines.append("")
    lines.append("[启动入口]")
    if report["entrypoints"]:
        for item in report["entrypoints"]:
            lines.append("  %-16s 链接 %s (存在 %s / 受管 %s) 可执行 %s" % (item["id"], item["link"], item["link_present"], item["link_managed"], item["executable"]))
    else:
        lines.append("  无记录")
    data = report["data"]
    lines.append("")
    lines.append("[运行数据]")
    if data.get("exists"):
        lines.append("  目录: %s | 权限: %s | 文件数: %s | 合计: %s" % (data["path"], data.get("mode"), data.get("count"), human_bytes(data.get("total_bytes", 0))))
        for item in data["files"][:20]:
            lines.append("  %s (%s, %s)" % (item["path"], human_bytes(item.get("size", 0)), item.get("sha256", "-")))
        if data.get("truncated"):
            lines.append("  ...（清单已截断）")
    else:
        lines.append("  目录不存在或未配置: %s" % data.get("path"))
    lines.append("")
    lines.append("[结论]")
    lines.append("  ok=%s 错误=%d 警告=%d" % (report["ok"], report["summary"]["errors"], report["summary"]["warnings"]))
    for item in report["errors"]:
        lines.append("  错误: %s" % item)
    for item in report["warnings"]:
        lines.append("  警告: %s" % item)
    return "\n".join(lines) + "\n"
