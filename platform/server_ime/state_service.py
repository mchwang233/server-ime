"""Versioned candidate/status interface on the SAME private IBus connection."""
import json
from gi.repository import Gio, GLib

BUS_NAME = "org.freedesktop.IBus.ServerIME"
OBJECT_PATH = "/org/freedesktop/IBus/ServerIME/State"
INTERFACE = "org.superpartner.ServerIME1"
XML = """<node><interface name="org.superpartner.ServerIME1">
<method name="ListContexts"><arg name="contexts" type="as" direction="out"/></method>
<method name="GetState"><arg name="context" type="s" direction="in"/><arg name="json" type="s" direction="out"/></method>
<method name="SelectCandidate"><arg name="context" type="s" direction="in"/><arg name="id" type="s" direction="in"/><arg name="revision" type="t" direction="in"/><arg name="accepted" type="b" direction="out"/></method>
<method name="Page"><arg name="context" type="s" direction="in"/><arg name="delta" type="i" direction="in"/><arg name="revision" type="t" direction="in"/><arg name="accepted" type="b" direction="out"/></method>
<method name="SetMode"><arg name="context" type="s" direction="in"/><arg name="mode" type="s" direction="in"/><arg name="revision" type="t" direction="in"/><arg name="accepted" type="b" direction="out"/></method>
<signal name="StateChanged"><arg name="context" type="s"/><arg name="json" type="s"/></signal>
<signal name="ContextRemoved"><arg name="context" type="s"/></signal>
</interface></node>"""


class StateService:
    def __init__(self, connection):
        self.connection = connection
        self.controllers = {}
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        self.registration = connection.register_object(OBJECT_PATH, info.interfaces[0], self.call, None, None)

    def add(self, controller):
        self.controllers[controller.context_id] = controller

    def publish(self, state):
        if self.connection.is_closed():
            return
        self.connection.emit_signal(None, OBJECT_PATH, INTERFACE, "StateChanged",
                                    GLib.Variant("(ss)", (state["context_id"], json.dumps(state, ensure_ascii=False))))

    def remove(self, context_id):
        self.controllers.pop(context_id, None)
        if self.connection.is_closed():
            return
        self.connection.emit_signal(None, OBJECT_PATH, INTERFACE, "ContextRemoved",
                                    GLib.Variant("(s)", (context_id,)))

    def call(self, connection, sender, path, interface, method, parameters, invocation):
        args = parameters.unpack()
        if method == "ListContexts":
            invocation.return_value(GLib.Variant("(as)", (sorted(self.controllers),)))
            return
        controller = self.controllers.get(args[0])
        if controller is None:
            invocation.return_dbus_error(INTERFACE + ".UnknownContext", "The input context no longer exists")
            return
        if method == "GetState":
            invocation.return_value(GLib.Variant("(s)", (json.dumps(controller.snapshot(), ensure_ascii=False),)))
            return
        if method == "SelectCandidate":
            accepted = controller.select(args[1], args[2])
        elif method == "Page":
            accepted = args[1] in {-1, 1} and controller.move(args[1], page=True, revision=args[2])
        elif method == "SetMode":
            accepted = controller.set_mode(args[1], args[2])
        else:
            invocation.return_dbus_error(INTERFACE + ".UnknownMethod", "Unknown method")
            return
        invocation.return_value(GLib.Variant("(b)", (accepted,)))

    def close(self):
        self.connection.unregister_object(self.registration)
