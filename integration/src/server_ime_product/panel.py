"""Candidate UI wiring, cursor placement and live settings; employee_id=platform."""
import json
import os
from pathlib import Path
from ime_interface import config, keymap
from ime_interface.panel import CandidatePanel
from ime_interface.bridge import Client as StateClient
from gi.repository import Gtk, Gdk, Gio, GLib
from .rpc import Client


class ProductPanel(CandidatePanel):
    def __init__(self, view, client):
        self.settings = view['settings']
        self.config_revision = view['revision']
        super().__init__(config.panel_options(self.settings), client)
        self.window.connect('size-allocate', lambda *_: self.place())

    def update_settings(self, view):
        self.settings = view['settings']
        self.config_revision = view['revision']
        self.margin = self.settings['panel']['edge_margin']
        self.set_options(config.panel_options(self.settings))

    def render(self, state, feedback=''):
        # The badge/backend label alone is not a reason to keep a popup mapped.
        # Ignore another context's focus-out just as CandidatePanel does.
        if state and state.get('focused') and state.get('enabled'):
            useful = (not state.get('direct_input') and state.get('mode') == 'zh' and
                      (state.get('preedit', {}).get('visible') or
                       state.get('candidate_visible') or state.get('error')))
            if not useful:
                self.context_id = state.get('context_id')
                self.snapshot, self.rows = state, []
                self.window.hide()
                return
        super().render(state, feedback)
        if not state or not state.get('focused') or not state.get('enabled'):
            return
        self.status.set_text(('输入异常，可回车提交原文' if state['preedit']['visible'] else
                             '输入服务暂不可用') if state['error'] else '中文输入')
        bindings = keymap.validate_shortcuts(self.settings['shortcuts'])[2]
        self.badge_button.set_tooltip_text(bindings['toggle_mode'].describe() + '：中英切换')
        digit_hint = '数字输入 · ↑↓/单击选词' if state.get('literal_digits') else '数字/单击选词'
        self.hints.set_text(digit_hint + ' · ' + bindings['commit_raw'].describe() + ' 原文 · ' +
                            bindings['toggle_mode'].describe() + ' 中英')
        # Product labels replace the base panel's labels after its first fit.
        # Fit the final text too. The base viewport retains the complete logical
        # page and exposes its scrollbar when the row does not fit.
        self._fit_to_screen()
        GLib.idle_add(self.place)

    def _widget_geometry(self, widget):
        if not self.window.get_visible() or not widget or not widget.get_mapped():
            return None
        x, y = widget.translate_coordinates(self.window, 0, 0)
        _, origin_x, origin_y = self.window.get_window().get_origin()
        return dict(x=origin_x + x, y=origin_y + y,
                    w=widget.get_allocated_width(), h=widget.get_allocated_height())

    def metrics(self):
        metrics = super().metrics()
        # Read-only geometry uses the actual allocated viewport and scrollbar.
        # Offscreen rows keep their IDs and un-clipped coordinates; in_view
        # distinguishes them from clickable, fully visible candidates.
        metrics['viewport'] = self._widget_geometry(self.scroller.get_child())
        metrics['scrollbar'] = self._widget_geometry(self.scroller.get_hscrollbar())
        return metrics

    def _place(self):
        # CandidatePanel calls this during render. Use the caret anchor on that
        # first placement as well as on subsequent size allocations.
        return self.place()

    def place(self):
        rect = (self.snapshot or {}).get('cursor_rect')
        screen = self.window.get_screen()
        if rect:
            monitor = screen.get_monitor_at_point(rect['x'], rect['y'])
        else:
            monitor = screen.get_primary_monitor()
        area = screen.get_monitor_geometry(max(0, monitor))
        w, h = self.window.get_size()
        x = rect['x'] if rect else area.x + self.margin
        y = rect['y'] + rect['height'] + 4 if rect else area.y + self.margin
        if rect and y + h + self.margin > area.y + area.height:
            y = rect['y'] - h - 4
        x = max(area.x + self.margin, min(x, area.x + area.width - w - self.margin))
        y = max(area.y + self.margin, min(y, area.y + area.height - h - self.margin))
        self.window.move(x, y)
        return False


def run_panel(args):
    rpc, state = Client(), StateClient()
    panel = ProductPanel(rpc.call('get'), state)
    rpc.subscribe(panel.update_settings)
    state.subscribe(panel.render, lambda cid: panel.render(None) if cid == getattr(panel, 'context_id', None) else None)
    for cid in state.list_contexts():
        panel.render(state.get_state(cid))
    xml = '''<node><interface name="org.superpartner.ServerIME.Panel1">
      <method name="Geometry"><arg type="s" direction="out"/></method>
      </interface></node>'''
    conn = rpc.connection
    def geometry(c, s, p, i, m, args, invocation):
        rows = [{k: v for k, v in row.items() if k != 'text'} for row in panel.row_geometry()] if panel.geometry() else []
        result = dict(panel=panel.geometry(), rows=rows, settings_revision=panel.config_revision,
                      candidate_presentation='custom',
                      metrics=panel.metrics(),
                      revision=(panel.snapshot or {}).get('revision'),
                      page_start=(panel.snapshot or {}).get('page_start'),
                      page_size=(panel.snapshot or {}).get('page_size'),
                      cursor_rect=(panel.snapshot or {}).get('cursor_rect'),
                      context_id=(panel.snapshot or {}).get('context_id'),
                      anchored=bool((panel.snapshot or {}).get('cursor_rect')))
        invocation.return_value(GLib.Variant('(s)', (json.dumps(result),)))
    registration = conn.register_object('/org/freedesktop/IBus/ServerIME/Panel',
        Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0], geometry, None, None)
    if rpc.bus.request_name('org.freedesktop.IBus.ServerIME.Panel', 4) != 1:
        raise RuntimeError('Panel already running')
    rpc.bus.connect('disconnected', lambda *_: Gtk.main_quit())
    import signal
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (Gtk.main_quit(), False)[1])
    Path(args.ready).write_text(json.dumps(dict(pid=os.getpid(), ready=True)))
    try:
        Gtk.main()
    finally:
        conn.unregister_object(registration)
        state.close()
    return 0


def settings_window():
    from ime_interface.settings_ui import SettingsWindow
    client = Client()
    view = client.call('get')
    caps = config.Capabilities(view['capabilities'])
    def save(settings):
        try:
            return client.call('apply', settings=settings)['settings']
        except config.ConfigError:
            raise
        except Exception as exc:
            raise config.ConfigError([dict(code='service-unavailable', path='', message=str(exc))])
    window = SettingsWindow(view['settings'], caps, view['config_path'], save_handler=save,
                            user_data_dir=Path(view['data_dir']) / 'learning')
    window.window.show_all()
    return window
