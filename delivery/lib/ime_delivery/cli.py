"""命令行入口：ime-install / ime-diagnose / ime-manifest。"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import TOOL_VERSION
from . import diagnose as diagnose_mod
from . import policy
from .installer import (
    Logger,
    list_versions,
    recover,
    run_install,
    run_rollback,
    run_uninstall,
    verify_installed,
)
from .manifest import load_bundle, validate_manifest_data
from .product import validate_product_data
from .util import ImeError

PROG = "ime-install"


def _emit(result, as_json):
    if as_json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    elif result.get("message"):
        sys.stdout.write(result["message"] + "\n")
    sys.stdout.flush()


def _common(p, *, json_flag=True):
    p.add_argument("--allowed-root", action="append", default=[], metavar="DIR", help="把写入限制在该根目录之下，可重复")
    p.add_argument("--lock-timeout", type=float, default=0.0, metavar="SEC", help="等待前缀锁的秒数，默认 0（立即失败）")
    if json_flag:
        p.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p.add_argument("-v", "--verbose", action="store_true", help="把审计日志同时打印到 stderr")


def _fault_arg(p):
    p.add_argument(
        "--fault",
        metavar="POINT",
        default=None,
        help="（仅测试）在指定阶段强制退出以模拟崩溃: after_verify/after_stage/after_version_placed/after_switch/after_links/before_state_commit/after_state_commit",
    )


def build_install_parser():
    parser = argparse.ArgumentParser(prog=PROG, description="用户级输入法安装/升级/回滚/卸载工具（无需 root）")
    parser.add_argument("--version", action="version", version="%(prog)s " + TOOL_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (("install", "安装一个组件包"), ("upgrade", "升级到新版本（要求已安装）")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("package", metavar="PACKAGE", help="ime-bundle tar.gz 路径")
        p.add_argument("--prefix", required=True, help="安装前缀（显式指定，必须是当前用户可写的绝对路径）")
        p.add_argument("--data-dir", required=True, help="运行数据目录（个人词库/学习数据，必须在前缀之外）")
        p.add_argument("--sha256", default=None, help="安装包整体校验值；缺省时读取 PACKAGE.sha256")
        p.add_argument("--force-conflicts", action="store_true", help="把占位冲突文件移入 ime/backup 后继续（不删除）")
        p.add_argument("--repair", action="store_true", help="重装同版本/覆盖异常版本目录（旧内容移入 backup）")
        p.add_argument("--retain", type=int, default=None, metavar="N", help="保留的版本数（含当前与上一版本）")
        p.add_argument("--allow-data-dir-change", action="store_true", help="允许更换已记录的数据目录")
        _fault_arg(p)
        _common(p)

    p = sub.add_parser("rollback", help="回滚到之前的版本")
    p.add_argument("--prefix", required=True)
    p.add_argument("--to", default=None, metavar="VERSION", help="目标版本，缺省为安装记录中的 previous")
    p.add_argument("--allow-drift", action="store_true", help="即使目标版本文件被修改也强制回滚")
    _fault_arg(p)
    _common(p)

    p = sub.add_parser("uninstall", help="卸载（默认保留运行数据）")
    p.add_argument("--prefix", required=True)
    p.add_argument("--data-dir", default=None, help="运行数据目录；缺省使用安装记录中的路径")
    p.add_argument("--purge-data", action="store_true", help="同时删除运行数据目录（需 --yes）")
    p.add_argument("--yes", action="store_true", help="确认删除运行数据")
    _fault_arg(p)
    _common(p)

    p = sub.add_parser("recover", help="恢复被中断的事务")
    p.add_argument("--prefix", required=True)
    _fault_arg(p)
    _common(p)

    p = sub.add_parser("list", help="列出版本与安装状态")
    p.add_argument("--prefix", required=True)
    _common(p)

    p = sub.add_parser("verify", help="校验当前（或指定）版本的已安装文件")
    p.add_argument("--prefix", required=True)
    p.add_argument("--version", default=None)
    _common(p)
    return parser


def _logger(args):
    return Logger(echo=bool(getattr(args, "verbose", False)))


def main_install(argv=None):
    parser = build_install_parser()
    args = parser.parse_args(argv)
    allowed = policy.check_allowed_roots(args.allowed_root)
    as_json = bool(getattr(args, "json", False))
    try:
        if args.command in ("install", "upgrade"):
            result = run_install(
                args.package,
                args.prefix,
                args.data_dir,
                upgrade_only=(args.command == "upgrade"),
                force_conflicts=args.force_conflicts,
                repair=args.repair,
                retain_override=args.retain,
                allow_data_dir_change=args.allow_data_dir_change,
                fault=args.fault,
                allowed_roots=allowed,
                lock_timeout=args.lock_timeout,
                log=_logger(args),
            )
            _emit(result, as_json)
            return 0
        if args.command == "rollback":
            result = run_rollback(
                args.prefix,
                to_version=args.to,
                allow_drift=args.allow_drift,
                fault=args.fault,
                allowed_roots=allowed,
                lock_timeout=args.lock_timeout,
                log=_logger(args),
            )
            _emit(result, as_json)
            return 0
        if args.command == "uninstall":
            result = run_uninstall(
                args.prefix,
                purge_data=args.purge_data,
                yes=args.yes,
                data_dir=args.data_dir,
                fault=args.fault,
                allowed_roots=allowed,
                lock_timeout=args.lock_timeout,
                log=_logger(args),
            )
            _emit(result, as_json)
            return 0
        if args.command == "recover":
            prefix = policy.check_prefix(args.prefix, allowed)
            from .installer import Layout

            lay = Layout(prefix)
            if not os.path.isdir(lay.root):
                result = {"status": "clean", "prefix": prefix, "message": "前缀 %s 没有安装目录，无需恢复" % prefix}
                _emit(result, as_json)
                return 0
            result = recover(lay, _logger(args), fault=args.fault)
            result["prefix"] = prefix
            result["message"] = "事务恢复完成: %s" % result.get("status")
            _emit(result, as_json)
            return 0
        if args.command == "list":
            result = list_versions(args.prefix, allowed_roots=allowed)
            if as_json:
                _emit(result, True)
            else:
                sys.stdout.write("前缀: %s\n" % result["prefix"])
                sys.stdout.write("已安装: %s 当前: %s 上一版本: %s\n" % (result["installed"], result["current"], result["previous"]))
                sys.stdout.write("数据目录: %s\n" % result.get("data_dir"))
                for row in result["versions"]:
                    marks = []
                    if row["current"]:
                        marks.append("当前")
                    if row["previous"]:
                        marks.append("上一版本")
                    sys.stdout.write(
                        "  %-10s 组件=%-12s 文件=%3d 目录存在=%s %s\n"
                        % (row["version"], row["component"], row["files"], row["present"], ",".join(marks))
                    )
                if result.get("pending_journal"):
                    sys.stdout.write("未完成事务: %s\n" % result["pending_journal"].get("txid"))
                sys.stdout.flush()
            return 0
        if args.command == "verify":
            result = verify_installed(args.prefix, args.version, allowed_roots=allowed)
            if as_json:
                _emit(result, True)
            else:
                sys.stdout.write(
                    "版本 %s: 检查 %d 个文件, %s\n"
                    % (result["version"], result["files"], "全部一致" if result["ok"] else "存在不一致")
                )
                for item in result["drift"]:
                    sys.stdout.write("  漂移: %s (%s)\n" % (item["path"], item["reason"]))
                for item in result["links"]:
                    sys.stdout.write("  入口: %s 存在=%s 受管=%s\n" % (item["path"], item["exists"], item["managed"]))
                sys.stdout.flush()
            return 0 if result["ok"] else 5
        parser.error("未知命令: %s" % args.command)
    except ImeError as exc:
        _print_error(exc, as_json)
        return exc.exit_code
    except KeyboardInterrupt:
        sys.stderr.write("已中断（已安装版本不受影响；如事务未完成请运行 recover）\n")
        return 130


def _print_error(exc, as_json):
    if as_json:
        sys.stdout.write(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stderr.write("错误: %s\n" % exc.message)
        for item in exc.details:
            sys.stderr.write("  - %s\n" % item)
    sys.stderr.flush()


def main_diagnose(argv=None):
    parser = argparse.ArgumentParser(prog="ime-diagnose", description="输出不含输入内容的安装诊断报告")
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--allowed-root", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    allowed = policy.check_allowed_roots(args.allowed_root)
    try:
        report = diagnose_mod.collect(args.prefix, args.data_dir, allowed_roots=allowed)
    except ImeError as exc:
        _print_error(exc, args.json)
        return exc.exit_code
    if args.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(diagnose_mod.render_text(report))
    sys.stdout.flush()
    return 0 if report["ok"] else 5


def main_manifest(argv=None):
    parser = argparse.ArgumentParser(prog="ime-manifest", description="组件/产品交付清单校验工具")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate", help="校验组件清单（可选校验 payload）")
    p.add_argument("manifest")
    p.add_argument("--payload", default=None, help="payload 目录，给出时逐文件校验大小与 sha256")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("inspect", help="校验整个安装包（解包 + 清单 + 载荷 + 入口）")
    p.add_argument("package")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("product", help="校验产品级交付清单（汇总各组件包）")
    p.add_argument("manifest")
    p.add_argument("--no-bundles", action="store_true", help="只校验结构，不打开组件包")
    p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            manifest = _load_manifest(args.manifest, args.payload)
            result = {
                "status": "valid",
                "component": manifest.component_id,
                "name": manifest.name,
                "version": manifest.version,
                "files": len(manifest.files),
                "entrypoints": [item["link_rel"] for item in manifest.entrypoints],
                "manifest_sha256": manifest.sha256,
                "payload_verified": bool(args.payload),
            }
            if args.json:
                _emit(result, True)
            else:
                sys.stdout.write(
                    "清单有效: %s %s, 文件 %d, 启动入口 %s%s\n"
                    % (
                        result["component"],
                        result["version"],
                        result["files"],
                        ",".join(result["entrypoints"]),
                        "，载荷校验通过" if args.payload else "（未校验载荷，可用 --payload 指定）",
                    )
                )
            return 0
        if args.command == "inspect":
            import shutil
            import tempfile

            from .manifest import verify_package_sha256
            from .util import read_sha256_sidecar

            sidecar = read_sha256_sidecar(os.path.abspath(args.package))
            package_sha = None
            if sidecar:
                package_sha = verify_package_sha256(os.path.abspath(args.package), sidecar)
            work = tempfile.mkdtemp(prefix="ime-inspect-")
            try:
                manifest, payload, root = load_bundle(args.package, work)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            result = {
                "status": "valid",
                "package": os.path.abspath(args.package),
                "package_sha256": package_sha,
                "sidecar_verified": bool(sidecar),
                "component": manifest.component_id,
                "name": manifest.name,
                "version": manifest.version,
                "files": len(manifest.files),
                "total_bytes": sum(int(item["size"]) for item in manifest.files),
                "entrypoints": [item["link_rel"] for item in manifest.entrypoints],
                "runtime_requires": [item["id"] for item in manifest.runtime.get("requires", [])],
                "data_dirs": [item["path"] for item in manifest.data_dirs],
                "manifest_sha256": manifest.sha256,
            }
            if args.json:
                _emit(result, True)
            else:
                sys.stdout.write(
                    "安装包有效: %s %s（%d 个文件，%d 字节）\n启动入口: %s\n运行依赖: %s\n数据目录: %s\n"
                    % (
                        result["component"],
                        result["version"],
                        result["files"],
                        result["total_bytes"],
                        ", ".join(result["entrypoints"]),
                        ", ".join(result["runtime_requires"]) or "-",
                        ", ".join(result["data_dirs"]) or "-",
                    )
                )
            return 0
        if args.command == "product":
            path = os.path.abspath(args.manifest)
            import json as _json

            with open(path, "rb") as fh:
                try:
                    data = _json.loads(fh.read().decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ImeError("manifest", "产品清单不是合法 JSON: %s" % exc, 5)
            result = validate_product_data(data, os.path.dirname(path), check_bundles=not args.no_bundles)
            if args.json:
                _emit(result, True)
            else:
                sys.stdout.write(
                    "产品 %s %s: 就绪组件 %d, 未就绪 %d, 可打包=%s\n"
                    % (result["product"]["id"], result["product"]["version"], result["ready"], result["not_ready"], result["packaging_ready"])
                )
                for item in result["components"]:
                    sys.stdout.write(
                        "  %-10s %-8s 版本=%-12s 入口=%s\n"
                        % (item["id"], item["status"], item.get("version") or "-", ",".join(item.get("entrypoints") or []) or "-")
                    )
            return 0
    except ImeError as exc:
        _print_error(exc, getattr(args, "json", False))
        return exc.exit_code
    parser.error("未知命令")


def _load_manifest(path, payload):
    from .manifest import load_manifest_file

    return load_manifest_file(path, payload)
