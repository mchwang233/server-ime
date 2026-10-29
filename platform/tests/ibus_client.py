"""Separate-process, real IBus InputContext client. No engine vfunc calls."""
import json
import os
from pathlib import Path
import statistics
import time

import gi
gi.require_version("IBus", "1.0")
from gi.repository import IBus, Gio, GLib
from server_ime.controller import CONTROL, RELEASE, PAGE_DOWN, RETURN, ESCAPE
from server_ime.state_service import BUS_NAME, OBJECT_PATH, INTERFACE
from server_ime.ui_client import StateClient


def spin(seconds=0.08):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(0.002)


def main():
    IBus.init()
    bus = IBus.Bus.new()
    assert bus.is_connected(), "not connected to isolated IBus"
    observations, checks, latencies = [], [], []
    ctx = bus.create_input_context("server-ime-platform-client-a")
    caps = int(IBus.Capabilite.FOCUS | IBus.Capabilite.PREEDIT_TEXT | IBus.Capabilite.LOOKUP_TABLE |
               IBus.Capabilite.AUXILIARY_TEXT | IBus.Capabilite.PROPERTY)
    ctx.set_capabilities(caps)
    commits, preedits, lookups = [], [], []
    def preedit(_ctx, text, cursor, visible):
        item = {"signal": "preedit", "text": text.get_text(), "cursor": cursor, "visible": visible}
        preedits.append(item); observations.append(item)
    def commit(_ctx, text):
        commits.append(text.get_text()); observations.append({"signal": "commit", "text": text.get_text()})
    def lookup(_ctx, table, visible):
        item = {"signal": "lookup", "visible": visible, "selected": table.get_cursor_pos(),
                "candidates": [table.get_candidate(i).get_text() for i in range(table.get_number_of_candidates())]}
        lookups.append(item); observations.append(item)
    ctx.connect("update-preedit-text", preedit)
    ctx.connect("commit-text", commit)
    ctx.connect("update-lookup-table", lookup)
    states = []
    bus.get_connection().signal_subscribe(BUS_NAME, INTERFACE, "StateChanged", OBJECT_PATH, None,
        Gio.DBusSignalFlags.NONE, lambda conn, sender, path, iface, signal, params: states.append(json.loads(params.unpack()[1])))

    def api(method, signature, *args):
        result = bus.get_connection().call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, method,
            GLib.Variant(signature, args), None, Gio.DBusCallFlags.NONE, 3000, None)
        return result.unpack()[0]

    def state():
        ids = api("ListContexts", "()")
        snapshots = [json.loads(api("GetState", "(s)", cid)) for cid in ids]
        return next((s for s in snapshots if s["focused"]), snapshots[-1])

    def key(value, modifiers=0, expected=True):
        start = time.perf_counter()
        result = ctx.process_key_event(value, 0, modifiers)
        latencies.append((time.perf_counter()-start)*1000)
        assert result == expected, (hex(value), modifiers, result, expected)
        spin()

    def type_text(text):
        for c in text:
            key(ord(c))

    ctx.focus_in()
    ctx.set_engine("server-ime-test")
    spin(.2)
    desc = ctx.get_engine()
    assert desc and desc.get_name() == "server-ime-test", "component not selectable"
    checks.append("component-registered-and-selected")
    ctx.set_content_type(0, 0); spin()
    type_text("nihao")
    assert any(p["text"] == "nihao" and p["visible"] for p in preedits)
    assert lookups[-1]["candidates"][0] == "你好"
    key(32)
    assert commits == ["你好"]
    assert preedits[-1]["text"] == "" and not preedits[-1]["visible"]
    assert not lookups[-1]["visible"]
    checks.append("client-observed-preedit-candidates-commit-and-clear")
    type_text("ni")
    key(PAGE_DOWN)
    assert state()["page_start"] == 5
    key(ord('2'))
    assert commits[-1] == "妮"
    checks.append("page-relative-numeric-selection")
    type_text("ni")
    old = state()
    key(ord('n'), RELEASE, False)
    assert state()["preedit"]["text"] == "ni"
    key(ord('c'), CONTROL, False)
    assert not api("SelectCandidate", "(sst)", old["context_id"], "ni:0", old["revision"])
    assert state()["preedit"]["text"] == ""
    checks.append("release-shortcut-passthrough-and-stale-action-rejection")
    type_text("ni")
    fresh = state()
    assert api("SelectCandidate", "(sst)", fresh["context_id"], "ni:1", fresh["revision"])
    spin()
    assert commits[-1] == "呢"
    checks.append("ui-dbus-candidate-selection-commits-to-client")
    type_text("ni")
    commit_count = len(commits)
    ctx.focus_out(); spin()
    assert state()["preedit"]["text"] == ""
    ctx2 = bus.create_input_context("server-ime-platform-client-b")
    ctx2.set_capabilities(caps)
    other_commits = []
    ctx2.connect("commit-text", lambda c, t: other_commits.append(t.get_text()))
    ctx2.focus_in(); ctx2.set_engine("server-ime-test"); spin(.2)
    assert state()["preedit"]["text"] == ""
    assert len(commits) == commit_count and other_commits == []
    assert not ctx2.process_key_event(32, 0, 0)
    ctx2.focus_out(); spin(); ctx.focus_in(); spin()
    assert state()["preedit"]["text"] == ""
    checks.append("two-client-focus-transfer-no-stale-commit")
    type_text("ni")
    ctx.set_content_type(int(IBus.InputPurpose.PASSWORD), int(IBus.InputHints.NO_SPELLCHECK)); spin()
    key(ord('x'), expected=False)
    key(32, CONTROL, False)
    st = state()
    assert st["private"] and st["purpose"] == 8 and st["hints"] == 2
    assert st["candidates"] == [] and st["preedit"]["text"] == ""
    assert len(commits) == commit_count
    checks.append("password-purpose-clears-and-passes-keys")
    ctx.set_content_type(0, 8); spin()
    assert state()["hints"] == 8
    key(32, CONTROL)
    key(ord('x'), expected=False)
    assert state()["mode"] == "en"
    key(32, CONTROL)
    type_text("ni")
    ctx.reset(); spin()
    assert state()["preedit"]["text"] == ""
    assert states and states[-1]["schema_version"] == 1
    checks.append("mode-toggle-hints-and-reset")
    ui = StateClient()
    ui_states, removed = [], []
    ui.subscribe(ui_states.append, removed.append)
    assert state()["context_id"] in ui.list_contexts()
    type_text("ni")
    st = ui.get_state(state()["context_id"])
    assert ui.page(st, 1)
    spin()
    st = ui.get_state(st["context_id"])
    assert st["page_start"] == 5
    assert ui.select_candidate(st, "ni:5")
    spin()
    assert commits[-1] == "倪" and ui_states
    st = ui.get_state(st["context_id"])
    assert ui.set_mode(st, "en")
    spin()
    st = ui.get_state(st["context_id"])
    assert st["mode"] == "en" and ui.set_mode(st, "zh")
    spin()
    ui.close()
    checks.append("public-ui-client-page-select-mode-and-state-subscription")
    # Same IBus key path, no spin time included in the round-trip samples.
    for _ in range(20):
        key(ord('n')); key(ESCAPE)
    data = {"employee_id": "platform", "result": "PASS", "backend": "deterministic-fixture-v1",
            "checks": checks, "commits": commits, "observations": observations,
            "state_signal_count": len(states), "key_roundtrip_ms": latencies,
            "latency": {"count": len(latencies), "median_ms": statistics.median(latencies),
                        "p95_ms": sorted(latencies)[int(.95*(len(latencies)-1))], "max_ms": max(latencies)}}
    Path(os.environ["SERVER_IME_EVIDENCE"], "ibus-client.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
    ctx.focus_out(); ctx.destroy(); ctx2.destroy()
    print(json.dumps({k: data[k] for k in ("result", "checks", "commits", "latency")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
