"""把平台 D-Bus 候选/状态接口接到界面。

唯一依赖是 platform/server_ime/ui_client.py 的 `StateClient`（v1 协议）。平台包路径可由
环境变量 SERVER_IME_PLATFORM_PATH 指定；缺省用工程内 ../platform。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PLATFORM_PACKAGE = "server_ime.ui_client"


def _ensure_platform_importable():
    try:
        __import__(PLATFORM_PACKAGE)
        return
    except ImportError:
        pass
    candidates = []
    explicit = os.environ.get("SERVER_IME_PLATFORM_PATH")
    if explicit:
        candidates.append(Path(explicit))
    here = Path(__file__).resolve()
    candidates += [here.parents[3] / "platform", here.parents[2] / "platform"]
    for path in candidates:
        if (path / "server_ime" / "ui_client.py").exists():
            sys.path.insert(0, str(path))
            os.environ.setdefault("SERVER_IME_PLATFORM_RESOLVED", str(path))
            return
    raise RuntimeError("找不到 platform/server_ime/ui_client.py；请设置 SERVER_IME_PLATFORM_PATH")


def state_client_class():
    _ensure_platform_importable()
    from server_ime.ui_client import StateClient
    return StateClient


class Client:
    """薄封装：为界面提供 subscribe/get_state/select/page/set_mode 与版本安全的动作。"""

    def __init__(self, state_client=None):
        if state_client is None:
            state_client = state_client_class()()
        self._client = state_client

    def __getattr__(self, name):
        return getattr(self._client, name)

    def act(self, snapshot, kind, value):
        """按当前快照发动作；返回 (accepted, 新快照)。旧 revision 被拒时自动重读。"""
        if snapshot is None:
            return False, None
        if kind == "select":
            accepted = self._client.select_candidate(snapshot, value)
        elif kind == "page":
            accepted = self._client.page(snapshot, value)
        elif kind == "mode":
            accepted = self._client.set_mode(snapshot, value)
        else:
            raise ValueError(kind)
        fresh = self._client.get_state(snapshot["context_id"])
        return bool(accepted), fresh
