"""Product control on the explicitly selected IBus connection, never input logs."""
import json
import os
import gi
gi.require_version('IBus', '1.0')
from gi.repository import Gio, GLib, IBus
from ime_interface.config import ConfigError

NAME = 'org.freedesktop.IBus.ServerIME'
PATH = '/org/freedesktop/IBus/ServerIME/Product'
IFACE = 'org.superpartner.ServerIME.Product1'
XML = '''<node><interface name="org.superpartner.ServerIME.Product1">
<method name="Call"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
<signal name="SettingsChanged"><arg type="s"/></signal>
</interface></node>'''


class Client:
    def __init__(self):
        if not os.environ.get('IBUS_ADDRESS'):
            raise RuntimeError('IBUS_ADDRESS is required')
        IBus.init()
        self.bus = IBus.Bus.new()
        if not self.bus.is_connected():
            raise RuntimeError('Explicit IBus bus is unavailable')
        self.connection = self.bus.get_connection()

    def call(self, op, **args):
        request = json.dumps(dict(op=op, **args), ensure_ascii=False)
        reply = self.connection.call_sync(NAME, PATH, IFACE, 'Call',
            GLib.Variant('(s)', (request,)), None, Gio.DBusCallFlags.NONE, 8000, None)
        result = json.loads(reply.unpack()[0])
        if not result['ok']:
            raise ConfigError(result['errors'])
        return result['result']

    def subscribe(self, callback):
        return self.connection.signal_subscribe(NAME, IFACE, 'SettingsChanged', PATH,
            None, Gio.DBusSignalFlags.NONE,
            lambda c, s, p, i, n, params: callback(json.loads(params.unpack()[0])))


class Service:
    def __init__(self, connection, manager):
        self.connection, self.manager = connection, manager
        self.registration = connection.register_object(PATH,
            Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], self.call, None, None)

    def call(self, connection, sender, path, interface, method, params, invocation):
        try:
            raw = params.unpack()[0]
            if len(raw) > 65536:
                raise ValueError('Request exceeds 65536 characters')
            result = self.manager.dispatch(json.loads(raw))
            payload = dict(ok=True, result=result)
        except Exception as exc:
            errors = getattr(exc, 'errors', [dict(code=getattr(exc, 'code', 'product-error'),
                                                path='', message=str(exc))])
            payload = dict(ok=False, errors=errors)
        invocation.return_value(GLib.Variant('(s)', (json.dumps(payload, ensure_ascii=False),)))

    def changed(self):
        self.connection.emit_signal(None, PATH, IFACE, 'SettingsChanged',
            GLib.Variant('(s)', (json.dumps(self.manager.view(), ensure_ascii=False),)))

    def close(self):
        self.connection.unregister_object(self.registration)
