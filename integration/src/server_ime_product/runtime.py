"""Real engine + UserStore + platform + settings composition root."""
import json
import os
from pathlib import Path
import signal
from ime_interface import config
from server_ime_engine import Engine
from server_ime_engine.platform_adapter import PlatformSession
from . import __version__


class Manager:
    def __init__(self, path, data_dir):
        self.path, self.data_dir = Path(path), Path(data_dir)
        self.caps = config.Capabilities(Engine.capabilities())
        self.settings, errors, _ = config.load(self.path, self.caps)
        if errors:
            raise config.ConfigError(errors)  # Never silently overwrite corrupt settings.
        self.revision = 1
        self.state_service = self.rpc = None
        self.probe = self.create_session()

    def create_session(self):
        session = PlatformSession(config=config.engine_patch(self.settings, self.caps),
                                  user_data_dir=self.data_dir / 'learning')
        if session.deterministic:
            session.close()
            raise RuntimeError('Product requires the real conversion engine')
        return session

    def create_controller(self, *args):
        from server_ime.product_controller import ProductController
        return ProductController(*args, settings=self.settings, config_revision=self.revision)

    def controllers(self):
        return list(self.state_service.controllers.values()) if self.state_service else []

    def view(self):
        return dict(settings=self.settings, revision=self.revision,
                    engine_config=self.probe._session.state()['config'],
                    capabilities=Engine.capabilities(), config_path=str(self.path),
                    data_dir=str(self.data_dir), backend=self.probe.backend_id,
                    deterministic=False, candidate_presentation='custom')

    def apply(self, settings):
        new, errors = config.validate(settings, self.caps)
        if errors:
            raise config.ConfigError(errors)
        old = self.settings
        sessions = [self.probe] + [c.session for c in self.controllers()]
        try:
            for session in sessions:
                session.configure(config.engine_patch(new, self.caps))
            # GLib serializes this entire transaction with key events. The file
            # is the restart authority if killed before live notification.
            config.save(new, self.path, self.caps)
        except Exception:
            for session in sessions:
                session.configure(config.engine_patch(old, self.caps))
            for controller in self.controllers():
                controller.reset()
            raise
        self.settings = new
        self.revision += 1
        for controller in self.controllers():
            controller.configure_platform(new, self.revision)
        if self.rpc:
            self.rpc.changed()
        return self.view()

    def dispatch(self, request):
        op = request['op']
        if op == 'get':
            return self.view()
        if op == 'apply':
            return self.apply(request['settings'])
        if op == 'reset':
            return self.apply(config.defaults())
        if op == 'learning-status':
            return self.probe._engine.learning_status()
        if op == 'reload-lexicon':
            for c in self.controllers():
                c.reset()
                c.session._engine.reload_lexicon()
            return self.probe._engine.reload_lexicon()
        raise ValueError('Unknown operation')


def run_service(args):
    import gi
    gi.require_version('IBus', '1.0')
    from gi.repository import IBus, GLib
    from server_ime.ibus_adapter import ServerIME
    from server_ime.state_service import StateService
    from .rpc import Service, NAME
    if not os.environ.get('IBUS_ADDRESS'):
        raise RuntimeError('IBUS_ADDRESS must be explicit')
    manager = Manager(args.config, args.data_dir)
    IBus.init()
    bus = IBus.Bus.new()
    if not bus.is_connected() or bus.request_name(NAME, 4) != 1:
        manager.probe.close()
        raise RuntimeError('IBus unavailable or product already registered')
    loop = GLib.MainLoop()
    bus.connect('disconnected', lambda *_: loop.quit())
    state = manager.state_service = StateService(bus.get_connection())
    manager.rpc = Service(bus.get_connection(), manager)
    ServerIME.backend_factory = staticmethod(manager.create_session)
    ServerIME.controller_factory = staticmethod(manager.create_controller)
    ServerIME.state_service = state
    # Supervisor always owns a ProductPanel. Suppress ONLY this engine's native
    # lookup/auxiliary emissions even when attaching to an existing IBus daemon.
    ServerIME.candidate_presentation = 'custom'
    factory = IBus.Factory.new(bus.get_connection())
    factory.add_engine('server-ime', ServerIME)
    component = IBus.Component.new(NAME, 'Server IME', __version__, 'GPL-3.0-or-later',
                                  'Server IME', '', '', '')
    component.add_engine(IBus.EngineDesc.new('server-ime', '服务器输入法', '本地中文拼音',
                                           'zh_CN', 'GPL-3.0-or-later', 'Server IME', '', 'us'))
    if not bus.register_component(component):
        raise RuntimeError('IBus registration failed')
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
    # Selection must happen after the main loop can service CreateEngine.
    def select_engine():
        bus.set_global_engine_async('server-ime', 5000, None, selected, None)
        return False
    def selected(b, result, unused):
        if not b.set_global_engine_async_finish(result):
            loop.quit()
            return
        Path(args.ready).write_text(json.dumps(dict(pid=os.getpid(), backend=manager.probe.backend_id)))
        print(json.dumps(dict(event='ready', backend=manager.probe.backend_id)), flush=True)
    GLib.idle_add(select_engine)
    try:
        loop.run()
    finally:
        factory.destroy()
        for c in list(state.controllers.values()):
            if not c.closed:
                c.close()
        manager.rpc.close()
        state.close()
        manager.probe.close()
        if bus.is_connected():
            bus.release_name(NAME)
    return 0
