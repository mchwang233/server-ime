"""Small UI-side client for the version 1 candidate/status interface."""
import json
import os
import gi
gi.require_version("IBus", "1.0")
from gi.repository import IBus, Gio, GLib
from .state_service import BUS_NAME, OBJECT_PATH, INTERFACE


class StateClient:
    def __init__(self):
        if not os.environ.get("IBUS_ADDRESS"):
            raise RuntimeError("IBUS_ADDRESS must explicitly identify the target IBus bus")
        IBus.init()
        self.bus = IBus.Bus.new()
        if not self.bus.is_connected():
            raise RuntimeError("IBus connection unavailable")
        self.connection = self.bus.get_connection()
        self.subscriptions = []

    def _call(self, method, signature, *values):
        reply = self.connection.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, method,
            GLib.Variant(signature, values), None, Gio.DBusCallFlags.NONE, 3000, None)
        return reply.unpack()[0]

    def list_contexts(self):
        return self._call("ListContexts", "()")

    def get_state(self, context_id):
        return json.loads(self._call("GetState", "(s)", context_id))

    def select_candidate(self, snapshot, candidate_id):
        return self._call("SelectCandidate", "(sst)", snapshot["context_id"], candidate_id, snapshot["revision"])

    def page(self, snapshot, delta):
        return self._call("Page", "(sit)", snapshot["context_id"], delta, snapshot["revision"])

    def set_mode(self, snapshot, mode):
        return self._call("SetMode", "(sst)", snapshot["context_id"], mode, snapshot["revision"])

    def subscribe(self, on_state, on_removed=lambda context_id: None):
        for signal, callback in [
            ("StateChanged", lambda params: on_state(json.loads(params.unpack()[1]))),
            ("ContextRemoved", lambda params: on_removed(params.unpack()[0])),
        ]:
            self.subscriptions.append(self.connection.signal_subscribe(BUS_NAME, INTERFACE, signal,
                OBJECT_PATH, None, Gio.DBusSignalFlags.NONE,
                lambda conn, sender, path, iface, name, params, callback=callback: callback(params)))

    def close(self):
        for subscription in self.subscriptions:
            self.connection.signal_unsubscribe(subscription)
        self.subscriptions.clear()
