"""安装状态与事务日志的读写（全部位于 <prefix>/ime/state/）。"""

from __future__ import annotations

from .util import ImeError, load_json, write_json_atomic

STATE_SCHEMA = "ime.install-state/1"
JOURNAL_SCHEMA = "ime.install-journal/1"


def load_state(lay):
    data = load_json(lay.statefile, default=None)
    if data is None:
        return None
    if not isinstance(data, dict) or data.get("schema") != STATE_SCHEMA:
        raise ImeError(
            "state",
            "无法识别的安装状态文件: %s（期望 schema=%s）" % (lay.statefile, STATE_SCHEMA),
            5,
        )
    state = {
        "schema": STATE_SCHEMA,
        "tool_version": data.get("tool_version", "unknown"),
        "prefix": data.get("prefix"),
        "data_dir": data.get("data_dir"),
        "link_dir": data.get("link_dir", "bin"),
        "current": data.get("current"),
        "previous": data.get("previous"),
        "versions": data.get("versions") or {},
        "links": data.get("links") or [],
        "created_dirs": data.get("created_dirs") or [],
        "history": data.get("history") or [],
    }
    if state["prefix"] and state["prefix"] != lay.prefix:
        # 前缀目录被整体移动过：记录事实但不拒绝，便于诊断。
        state["prefix_mismatch"] = True
    return state


def save_state(lay, state):
    write_json_atomic(lay.statefile, state)


def load_journal(lay):
    return load_json(lay.journal, default=None)


def write_journal(lay, journal):
    journal["schema"] = JOURNAL_SCHEMA
    write_json_atomic(lay.journal, journal)


def clear_journal(lay):
    try:
        import os

        os.unlink(lay.journal)
    except FileNotFoundError:
        pass


def has_journal(lay):
    import os

    return os.path.exists(lay.journal)
