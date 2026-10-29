#!/usr/bin/python3
"""命令行入口：设置界面、候选面板、配置校验与映射。"""
from __future__ import annotations

import argparse
import json
import sys

from . import config as config_mod


def _caps(args):
    if args.caps:
        return config_mod.Capabilities.from_file(args.caps)
    try:
        from server_ime_engine import Engine

        with Engine() as engine:
            return config_mod.Capabilities.from_engine(engine)
    except Exception:
        return config_mod.Capabilities()


def cmd_defaults(args):
    json.dump(config_mod.defaults(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_validate(args):
    caps = _caps(args)
    settings, errors, path = config_mod.load(args.config, caps=caps)
    payload = {"path": str(path), "ok": not errors, "errors": errors,
               "settings": settings, "engine_patch": config_mod.engine_patch(settings, caps),
               "platform_patch": config_mod.platform_patch(settings),
               "mapping": config_mod.mapping_report(settings, caps),
               "capabilities": caps.summary()}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def cmd_save(args):
    caps = _caps(args)
    settings, errors, path = config_mod.load(args.config, caps=caps)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    if args.set_page_size:
        settings["input"]["page_size"] = args.set_page_size
    try:
        saved = config_mod.save(settings, path=args.config, caps=caps)
    except config_mod.ConfigError as error:
        print(json.dumps({"ok": False, "errors": error.errors}, ensure_ascii=False, indent=2))
        return 1
    path = config_mod.config_path() if not args.config else args.config
    print(json.dumps({"ok": True, "path": str(path), "settings": saved}, ensure_ascii=False, indent=2))
    return 0


def cmd_reset(args):
    caps = _caps(args)
    saved = config_mod.reset(path=args.config, caps=caps)
    print(json.dumps({"ok": True, "settings": saved}, ensure_ascii=False, indent=2))
    return 0


def cmd_apply_engine(args):
    caps = _caps(args)
    settings, errors, path = config_mod.load(args.config, caps=caps)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    try:
        patch, state = config_mod.apply_engine(settings, caps=caps)
    except config_mod.ConfigError as error:
        print(json.dumps({"ok": False, "errors": error.errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "patch": patch,
                      "engine_state": state}, ensure_ascii=False, indent=2))
    return 0


def cmd_settings(args):
    from . import settings_ui

    return settings_ui.main(["--config", args.config] if args.config else [])


def cmd_panel(args):
    from . import panel

    argv = []
    if args.config:
        argv += ["--config", args.config]
    if args.caps:
        argv += ["--caps", args.caps]
    return panel.main(argv)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ime-interface", description="服务器输入法界面工具（employee_id=interface）")
    parser.add_argument("--config", default=None, help="设置文件路径（默认 $XDG_CONFIG_HOME/server-ime/settings.json）")
    parser.add_argument("--caps", default=None, help="引擎 capabilities JSON；缺省读取真实引擎，失败则按全部未支持处理")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("defaults", help="打印默认设置")
    sub.add_parser("validate", help="校验并可读地打印映射结果")
    save = sub.add_parser("save", help="保存当前设置（可带 --set-page-size）")
    save.add_argument("--set-page-size", type=int, default=None)
    sub.add_parser("reset", help="恢复默认设置")
    sub.add_parser("apply-engine", help="把设置映射到真实引擎 configure 并回读")
    sub.add_parser("settings", help="打开中文设置界面")
    sub.add_parser("panel", help="打开候选面板")
    args = parser.parse_args(argv)
    return {"defaults": cmd_defaults, "validate": cmd_validate, "save": cmd_save, "reset": cmd_reset,
            "apply-engine": cmd_apply_engine, "settings": cmd_settings, "panel": cmd_panel}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
