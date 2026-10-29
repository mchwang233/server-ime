"""IBus 1.5 adapter; owns framework calls, not conversion or personal data."""
import uuid
import gi
gi.require_version("IBus", "1.0")
from gi.repository import IBus
from .controller import Controller

ENGINE_NAME = "server-ime-test"


class ServerIME(IBus.Engine):
    __gtype_name__ = "ServerIMEPlatformEngine"
    backend_factory = None
    controller_factory = Controller
    state_service = None
    # Standalone adapter users retain the native channel. The product explicitly
    # selects custom before creating ANY engines, on managed and existing buses.
    candidate_presentation = "native"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # GObject's C factory sets construct properties after Python __init__;
        # the object path is not available here. IDs are intentionally opaque.
        self.controller = type(self).controller_factory(type(self).backend_factory(),
            "engine-" + uuid.uuid4().hex, self.render, self.commit)
        self.state_service.add(self.controller)

    def commit(self, text):
        IBus.Engine.commit_text(self, IBus.Text.new_from_string(text))

    def properties(self, state):
        items = IBus.PropList.new()
        label = "中" if state["mode"] == "zh" else "英"
        if state["direct_input"]:
            label = "直接输入"
        items.append(IBus.Property.new("InputMode", IBus.PropType.TOGGLE,
            IBus.Text.new_from_string(label), "", IBus.Text.new_from_string("Ctrl+空格：中英切换"),
            not state["direct_input"], True,
            IBus.PropState.CHECKED if state["mode"] == "zh" else IBus.PropState.UNCHECKED, None))
        items.append(IBus.Property.new("Backend", IBus.PropType.NORMAL,
            IBus.Text.new_from_string(state["status"]), "",
            IBus.Text.new_from_string(state["backend"]), False, True, IBus.PropState.UNCHECKED, None))
        return items

    def render(self, state):
        connection = self.get_connection()
        if connection is not None and connection.is_closed():
            return
        # A client reports its caret after laying out our preedit. Re-sending
        # the preedit for that report causes another layout/caret notification
        # and can queue stale preedits ahead of editing keys in GTK clients.
        # Geometry belongs to the panel/state channel, not the input channel.
        if getattr(self, '_cursor_report', False):
            self.state_service.publish(state)
            return
        preedit = state["preedit"]
        text = IBus.Text.new_from_string(preedit["text"])
        if preedit["text"]:
            text.append_attribute(IBus.AttrType.UNDERLINE, IBus.AttrUnderline.SINGLE, 0, len(preedit["text"]))
        # CLEAR prevents the client committing stale preedit on focus transfer.
        self.update_preedit_text_with_mode(text, preedit["cursor"], preedit["visible"], IBus.PreeditFocusMode.CLEAR)
        native = self.candidate_presentation == "native"
        table = IBus.LookupTable.new(state["page_size"], state["selected_index"] if native else 0, True, False)
        table.set_orientation(IBus.Orientation.VERTICAL)
        for index in range(state["page_size"]):
            table.append_label(IBus.Text.new_from_string(str(index + 1)))
        for candidate in state["candidates"] if native else ():
            table.append_candidate(IBus.Text.new_from_string(candidate["text"]))
        self.update_lookup_table(table, bool(native and state["candidate_visible"]))
        self.update_auxiliary_text(IBus.Text.new_from_string(state["status"] if native else ""),
                                   bool(native and state["candidate_visible"]))
        if not native:
            # Hide only this engine's native surfaces. The system panel remains
            # available to other engines; never stop or configure that panel.
            self.hide_lookup_table()
            self.hide_auxiliary_text()
        self.register_properties(self.properties(state))
        self.state_service.publish(state)

    def do_process_key_event(self, keyval, keycode, state):
        return self.controller.key(keyval, keycode, state)

    def do_focus_in(self):
        self.controller.focus_in()

    def do_focus_out(self):
        self.controller.focus_out()

    def do_enable(self):
        self.controller.enable()

    def do_disable(self):
        self.controller.disable()

    def do_reset(self):
        self.controller.reset()

    def do_set_content_type(self, purpose, hints):
        self.controller.set_content_type(purpose, hints)

    def do_set_cursor_location(self, x, y, width, height):
        self._cursor_report = True
        try:
            self.controller.set_cursor_location(x, y, width, height)
        finally:
            self._cursor_report = False

    def do_candidate_clicked(self, index, button, state):
        if self.candidate_presentation == "native" and button == 1 and 0 <= index < self.controller.page_size:
            # IBus panels send the position within the CURRENT page.
            position = self.controller.selected // self.controller.page_size * self.controller.page_size + index
            candidates = self.controller.conversion.candidates
            if position < len(candidates):
                self.controller.select(candidates[position].id)

    def do_page_up(self):
        self.controller.move(-1, page=True)

    def do_page_down(self):
        self.controller.move(1, page=True)

    def do_cursor_up(self):
        self.controller.move(-1)

    def do_cursor_down(self):
        self.controller.move(1)

    def do_property_activate(self, prop_name, prop_state):
        if prop_name == "InputMode":
            self.controller.set_mode("zh" if prop_state == IBus.PropState.CHECKED else "en")

    def do_destroy(self):
        if hasattr(self, "controller"):
            self.controller.close()
            self.state_service.remove(self.controller.context_id)
        IBus.Engine.do_destroy(self)
