#!/usr/bin/env python3
"""Run with Python 3.9+, from any working directory."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from server_ime_engine import Engine

with Engine() as engine:
    session = engine.create_session()
    state = session.input("nihao")
    print("预编辑:", state["preedit"]["text"])
    print("候选:", [c["text"] for c in state["candidates"]["items"]])
    selected = session.select(state["candidates"]["items"][0]["id"])
    print("提交:", selected["commits"][0]["text"])
    assert selected["commits"][0]["text"] == "你好"
    assert session.state()["commits"] == []
