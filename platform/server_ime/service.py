import argparse
import importlib
import json
import os
from pathlib import Path
import signal
import sys
from xml.etree import ElementTree as ET

from . import __version__

COMPONENT = "org.freedesktop.IBus.ServerIME"


def main():
    parser = argparse.ArgumentParser(description="Isolated IBus adapter (employee_id=platform)")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--test-backend", action="store_true", help="finite deterministic fixture, not a pinyin engine")
    choice.add_argument("--backend", metavar="MODULE:FACTORY", help="zero-argument EngineSession factory")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--register", action="store_true", help="register a running component on the explicit IBus bus")
    mode.add_argument("--ibus", action="store_true", help="started by IBus from a manifest")
    mode.add_argument("--manifest", metavar="PATH", help="generate a manifest only; never installs it")
    parser.add_argument("--engine-name", default="server-ime-test")
    args = parser.parse_args()
    backend = "server_ime.deterministic:create_session" if args.test_backend else args.backend
    if args.manifest:
        import shlex
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / "launch.py"),
                   "--ibus", "--engine-name", args.engine_name, "--backend", backend]
        root = ET.Element("component")
        for name, value in {"name": COMPONENT, "description": "Server IME platform adapter",
                            "exec": shlex.join(command), "version": __version__, "license": "MIT",
                            "author": "Server IME platform", "homepage": "", "textdomain": ""}.items():
            ET.SubElement(root, name).text = value
        engines = ET.SubElement(root, "engines")
        engine = ET.SubElement(engines, "engine")
        for name, value in {"name": args.engine_name, "longname": "服务器输入法（链路测试）" if args.test_backend else "服务器输入法",
                            "description": "Deterministic framework test" if args.test_backend else "Replaceable conversion backend",
                            "language": "zh_CN", "license": "MIT", "author": "Server IME platform",
                            "layout": "us", "rank": "0"}.items():
            ET.SubElement(engine, name).text = value
        ET.indent(root)
        ET.ElementTree(root).write(args.manifest, encoding="utf-8", xml_declaration=True)
        return 0
    # Never discover and accidentally attach to the user's running daemon.
    if not os.environ.get("IBUS_ADDRESS"):
        parser.error("IBUS_ADDRESS must be explicitly supplied; automatic session discovery is disabled")
    module, separator, factory_name = backend.partition(":")
    if not separator or not module or not factory_name:
        parser.error("--backend requires MODULE:FACTORY")
    factory = getattr(importlib.import_module(module), factory_name)
    from .ibus_adapter import ServerIME
    from .state_service import StateService
    from gi.repository import IBus, GLib
    IBus.init()
    bus = IBus.Bus.new()
    if not bus.is_connected():
        raise RuntimeError("Cannot connect to the explicitly selected IBus bus")
    loop = GLib.MainLoop()
    bus.connect("disconnected", lambda *_: loop.quit())
    ServerIME.backend_factory = staticmethod(factory)
    state = StateService(bus.get_connection())
    ServerIME.state_service = state
    engine_factory = IBus.Factory.new(bus.get_connection())
    engine_factory.add_engine(args.engine_name, ServerIME)
    if bus.request_name(COMPONENT, 4) != 1:  # DO_NOT_QUEUE, PRIMARY_OWNER
        raise RuntimeError("Another ServerIME component owns this IBus bus name")
    if args.register:
        component = IBus.Component.new(COMPONENT, "Server IME platform adapter", __version__,
                                      "MIT", "Server IME platform", "", "", "")
        component.add_engine(IBus.EngineDesc.new(args.engine_name,
            "服务器输入法（链路测试）" if args.test_backend else "服务器输入法",
            "Deterministic fixture" if args.test_backend else "Replaceable backend",
            "zh_CN", "MIT", "Server IME platform", "", "us"))
        if not bus.register_component(component):
            raise RuntimeError("IBus refused component registration")
    def stop(*_):
        loop.quit()
        return False
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, stop)
    print(json.dumps({"event": "ready", "employee_id": "platform", "engine": args.engine_name,
                      "backend_factory": backend, "registration": "dynamic" if args.register else "manifest"}), flush=True)
    try:
        loop.run()
    finally:
        engine_factory.destroy()
        state.close()
        bus.release_name(COMPONENT)
    return 0
