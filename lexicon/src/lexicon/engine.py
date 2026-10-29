"""Read a lexicon-owned libpinyin user directory through the real engine.

SPDX-License-Identifier: GPL-3.0-or-later

Engine 0.1.0 calls ``pinyin_init(system_dir, NULL)``: it has no parameter for a
user directory, so a personal word table cannot be loaded through its public
API yet.  This adapter injects the documented libpinyin user directory into the
engine's native context at construction time by substituting the ``Native``
class for that single call.  It does not edit ``engine/`` or any engine file,
and it stops patching before the engine is returned.  When the engine grows a
``user_dir`` keyword the adapter uses it directly and no patch is needed.
"""
import hashlib
import inspect
import sys
import threading
from pathlib import Path

from .errors import LexiconError
from .native import USER_FILES

_BRIDGE_LOCK = threading.RLock()


def repo_root():
    return Path(__file__).resolve().parents[3]


def engine_paths(data_dir=None, runtime_dir=None):
    root = repo_root()
    runtime = Path(runtime_dir or root / "engine/vendor/runtime").resolve()
    data = Path(data_dir or runtime / "data").resolve()
    return runtime, data


def _engine_modules():
    runtime, _ = engine_paths()
    src = runtime.parent.parent / "src" if (runtime.parent.parent / "src").is_dir() else repo_root() / "engine/src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    try:
        import server_ime_engine
        from server_ime_engine import core
    except ImportError as exc:
        raise LexiconError("engine_unavailable", f"conversion engine is not importable: {exc}")
    return server_ime_engine, core


def open_engine(user_dir=None, data_dir=None, runtime_dir=None, require_user_data=True):
    """Return an engine instance, optionally with a lexicon user dictionary."""
    package, core = _engine_modules()
    runtime, data = engine_paths(data_dir, runtime_dir)
    if core.API_VERSION != "1.0":
        raise LexiconError("engine_incompatible", f"unsupported engine API {core.API_VERSION!r}")
    if user_dir is None:
        return core.Engine(runtime_dir=str(runtime), data_dir=str(data))
    user_dir = Path(user_dir).resolve()
    missing = [name for name in USER_FILES if not (user_dir / name).is_file()]
    if missing and require_user_data:
        raise LexiconError("user_data_missing", "user dictionary is incomplete", {"missing": missing, "path": str(user_dir)})
    if "user_dir" in inspect.signature(core.Engine.__init__).parameters:
        engine = core.Engine(runtime_dir=str(runtime), data_dir=str(data), user_dir=str(user_dir))
        bridge = "engine-user_dir"
    else:
        original = core.Native

        class _NativeWithUser(original):
            def __init__(self, runtime_dir_arg):
                super().__init__(runtime_dir_arg)
                inner = self.init
                self.init = lambda system_dir, _ignored=None: inner(system_dir, str(user_dir).encode())

        with _BRIDGE_LOCK:
            core.Native = _NativeWithUser
            try:
                engine = core.Engine(runtime_dir=str(runtime), data_dir=str(data))
            finally:
                core.Native = original
        bridge = "native-init-patch"
    try:
        capabilities = engine.capabilities()
    except Exception as exc:  # pragma: no cover - defensive against a changed engine
        engine.close()
        raise LexiconError("engine_incompatible", f"cannot read engine capabilities: {exc}")
    if capabilities.get("api_version") != "1.0":
        engine.close()
        raise LexiconError("engine_incompatible", "engine capabilities do not announce API 1.0")
    engine.lexicon_bridge = {
        "bridge": bridge,
        "engine_component_version": package.COMPONENT_VERSION,
        "backend": capabilities.get("backend"),
        "backend_version": capabilities.get("backend_version"),
        "user_dir": str(user_dir),
        "data_dir": str(data),
        "learning": capabilities.get("features", {}).get("learning"),
        "dictionary_import": capabilities.get("features", {}).get("dictionary_import"),
    }
    return engine


def fingerprint_data(data_dir=None):
    """Hashes of every file in the engine data directory (read-only proof)."""
    _, data = engine_paths(data_dir=data_dir)
    rows = {}
    for path in sorted(data.iterdir()):
        if path.is_file():
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            rows[path.name] = {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}
    return rows


def fingerprint_dir(directory):
    directory = Path(directory)
    rows = {}
    for path in sorted(directory.iterdir()):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows[path.name] = {"sha256": digest, "bytes": path.stat().st_size}
    return rows


def probe(engine, pinyin, page_size=10, session=None):
    owns = session is None
    session = session or engine.create_session()
    try:
        result = session.set_input(pinyin)
        return {
            "pinyin": pinyin,
            "texts": [item["text"] for item in result["candidates"]["items"]],
            "total": result["candidates"]["total"],
        }
    finally:
        if owns:
            session.close()


def probe_entries(engine, entries, limit=None):
    chosen = entries[:limit] if limit else entries
    rows = []
    session = engine.create_session()
    try:
        for entry in chosen:
            result = session.set_input(entry["pinyin"])
            texts = [item["text"] for item in result["candidates"]["items"]]
            rows.append({
                "text": entry["text"],
                "pinyin": entry["pinyin"],
                "top1": bool(texts) and texts[0] == entry["text"],
                "top5": entry["text"] in texts[:5],
                "top": texts[:5],
                "total": result["candidates"]["total"],
            })
    finally:
        session.close()
    return rows
