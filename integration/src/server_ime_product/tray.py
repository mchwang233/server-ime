"""Tray icon showing 中/英 for the current mode; employee_id=platform.

ibus-ui-gtk3 draws an engine's mode symbol itself, in a fixed "Monospace Bold
22" on a 48x48 canvas, so the glyph cannot be made larger from the engine side.
While server-ime is the active IBus engine this module shows its own tray icon
(same style, larger glyph) and turns IBus's systray icon off for this user; when
another engine is selected, or the panel exits, IBus's icon is turned back on.
"""
import subprocess

import cairo
import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo

ENGINE = 'server-ime'
IBUS_PANEL_SCHEMA = 'org.freedesktop.ibus.panel'
IBUS_ICON_KEY = 'show-icon-on-systray'
GLYPH_FILL = 0.88  # glyph height / icon height (IBus's own is about 0.6)


def ibus_panel_settings():
    source = Gio.SettingsSchemaSource.get_default()
    schema = source.lookup(IBUS_PANEL_SCHEMA, True) if source else None
    if schema is None or not schema.has_key(IBUS_ICON_KEY):
        return None
    return Gio.Settings.new(IBUS_PANEL_SCHEMA)


def symbol_color(settings):
    """IBus's own colour for tray symbols (xkb-icon-rgba), so the icon matches."""
    rgba = Gdk.RGBA()
    value = settings.get_string('xkb-icon-rgba') if settings is not None else ''
    if not value or not rgba.parse(value):
        rgba.parse('#415099')
    return rgba


def render_symbol(symbol, size, rgba, fill=GLYPH_FILL):
    """A size x size pixbuf with the symbol scaled so its ink fills `fill` of the height."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    layout = PangoCairo.create_layout(cr)
    desc = Pango.FontDescription.from_string('Sans Bold')
    desc.set_absolute_size(size * Pango.SCALE)
    layout.set_font_description(desc)
    layout.set_text(symbol, -1)
    ink, _ = layout.get_pixel_extents()
    if ink.width <= 0 or ink.height <= 0:
        return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)
    scale = min(size * fill / ink.height, size * 0.96 / ink.width)
    cr.translate((size - ink.width * scale) / 2 - ink.x * scale,
                 (size - ink.height * scale) / 2 - ink.y * scale)
    cr.scale(scale, scale)
    cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
    PangoCairo.show_layout(cr, layout)
    surface.flush()
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, size, size)


class ModeTray:
    def __init__(self, ibus, state_client, settings_command, marker):
        self.ibus, self.state, self.settings_command = ibus, state_client, settings_command
        self.panel_settings = ibus_panel_settings()
        self.rgba = symbol_color(self.panel_settings)
        # The marker outlives a crash, so the next panel still restores IBus's icon.
        self.marker = marker
        self.hid_ibus_icon = marker.exists()
        self.snapshot = None   # last focused, enabled context of this engine
        self.symbol = '中'
        self.size = 22
        self.icon = Gtk.StatusIcon()
        self.icon.set_title('服务器输入法')
        self.icon.set_visible(False)
        self.icon.connect('size-changed', self._size_changed)
        self.icon.connect('activate', lambda icon: self._popup(0, Gtk.get_current_event_time()))
        self.icon.connect('popup-menu', lambda icon, button, time: self._popup(button, time))
        self.ibus.set_watch_ibus_signal(True)
        self.ibus.connect('global-engine-changed', lambda bus, name: self._engine_changed(name))
        engine = self.ibus.get_global_engine()
        self._engine_changed(engine.get_name() if engine else '')

    # IBus engine and mode state

    def _engine_changed(self, name):
        active = name == ENGINE and self.panel_settings is not None
        if active:
            self._set_ibus_icon(False)
            self._draw()
        self.icon.set_visible(active)
        if not active:
            self._set_ibus_icon(True)

    def _set_ibus_icon(self, show):
        if self.panel_settings is None:
            return
        if not show and self.panel_settings.get_boolean(IBUS_ICON_KEY):
            self.marker.touch()
            self.panel_settings.set_boolean(IBUS_ICON_KEY, False)
            self.hid_ibus_icon = True
        elif show and self.hid_ibus_icon:
            self.panel_settings.set_boolean(IBUS_ICON_KEY, True)
            self.hid_ibus_icon = False
            self.marker.unlink(missing_ok=True)
        Gio.Settings.sync()

    def update(self, state):
        if not state or not state.get('focused') or not state.get('enabled'):
            return
        self.snapshot = state
        symbol = '中' if state.get('mode') == 'zh' and not state.get('direct_input') else '英'
        if symbol != self.symbol:
            self.symbol = symbol
            self._draw()

    # Drawing and menu

    def _size_changed(self, icon, size):
        self.size = max(16, size)
        self._draw()
        return True

    def _draw(self):
        self.icon.set_from_pixbuf(render_symbol(self.symbol, self.size, self.rgba))
        self.icon.set_tooltip_text('服务器输入法：%s文' % self.symbol)

    def _popup(self, button, time):
        menu = Gtk.Menu()
        target = 'en' if self.symbol == '中' else 'zh'
        toggle = Gtk.MenuItem(label='切换到%s' % ('英文' if target == 'en' else '中文'))
        toggle.set_sensitive(bool(self.snapshot))
        toggle.connect('activate', lambda item: self._set_mode(target))
        settings = Gtk.MenuItem(label='输入法设置…')
        settings.connect('activate', lambda item: self._spawn(self.settings_command))
        ibus_setup = Gtk.MenuItem(label='IBus 首选项…')
        ibus_setup.connect('activate', lambda item: self._spawn(['ibus-setup']))
        for item in (toggle, settings, Gtk.SeparatorMenuItem(), ibus_setup):
            menu.append(item)
        menu.show_all()
        self._menu = menu  # keep a reference while it is shown
        menu.popup(None, None, Gtk.StatusIcon.position_menu, self.icon, button, time)

    def _set_mode(self, mode):
        state = self.snapshot
        for _ in range(2):  # a stale revision is rejected once; retry on the fresh state
            if not state:
                return
            accepted, state = self.state.act(state, 'mode', mode)
            if accepted:
                return

    @staticmethod
    def _spawn(argv):
        try:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        except OSError:
            pass

    def close(self):
        self.icon.set_visible(False)
        self._set_ibus_icon(True)
