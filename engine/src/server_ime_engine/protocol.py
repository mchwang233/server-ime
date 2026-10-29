"""Bounded UTF-8 JSON Lines transport, API 1.0. GPL-3.0-or-later."""
import argparse
import inspect
import json
import sys

from .core import API_VERSION, Engine, EngineError

MAX_LINE_BYTES = 65536


class Service:
    def __init__(self, **engine_options):
        self.engine_options = engine_options
        self.engine = None

    def handle(self, request):
        request_id = request.get("id") if isinstance(request, dict) else None
        invalid_id = type(request_id) not in (str, int, type(None))
        if invalid_id:
            request_id = None
        try:
            if not isinstance(request, dict):
                raise EngineError("invalid_request", "request must be an object")
            if request.get("api_version") != API_VERSION:
                raise EngineError("unsupported_version", "expected api_version 1.0")
            if invalid_id:
                raise EngineError("invalid_request", "id must be a string, integer or null")
            op = request.get("op")
            if not isinstance(op, str):
                raise EngineError("invalid_request", "op must be a string")
            args = request.get("args", {})
            if not isinstance(args, dict):
                raise EngineError("invalid_request", "args must be an object")
            if op == "capabilities":
                method = Engine.capabilities
            else:
                supported = {"create", "destroy", "state", "configure", "input", "set_input",
                             "edit", "key", "candidates", "select", "commit", "reset", "set_context", "set_composition", "input_text",
                             "add_phrase", "remove_phrase", "import_dictionary", "reload_lexicon", "learning_status"}
                if op not in supported:
                    raise EngineError("unknown_operation", op)
                if self.engine is None:
                    self.engine = Engine(**self.engine_options)
                if op == "create":
                    method = self.engine.create_session
                elif op in {"add_phrase", "remove_phrase", "import_dictionary", "reload_lexicon", "learning_status"}:
                    method = getattr(self.engine, op)
                elif op == "destroy":
                    sid = request.get("session_id")
                    method = lambda: self.engine.destroy_session(sid)
                else:
                    method = getattr(self.engine.session(request.get("session_id")), op)
            try:
                inspect.signature(method).bind(**args)
            except TypeError as exc:
                raise EngineError("invalid_argument", str(exc)) from exc
            result = method(**args)
            if op == "create":
                result = result.state()
            response = {"api_version": API_VERSION, "id": request_id, "ok": True, "result": result}
        except EngineError as exc:
            response = {"api_version": API_VERSION, "id": request_id, "ok": False,
                        "error": {"code": exc.code, "message": str(exc)}}
        return response

    def close(self):
        if self.engine:
            self.engine.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local libpinyin conversion service; UTF-8 JSON Lines API 1.0")
    parser.add_argument("--runtime-dir")
    parser.add_argument("--data-dir")
    parser.add_argument("--user-dir", help="trusted matching native table, read from a private snapshot")
    parser.add_argument("--user-data-dir", help="explicit lexicon UserStore directory; created disabled")
    parser.add_argument("--base-lexicon")
    parser.add_argument("--capabilities", action="store_true")
    args = parser.parse_args(argv)
    if args.capabilities:
        print(json.dumps(Engine.capabilities(), ensure_ascii=False))
        return 0
    service = Service(runtime_dir=args.runtime_dir, data_dir=args.data_dir, user_dir=args.user_dir,
                      user_data_dir=args.user_data_dir, base_lexicon=args.base_lexicon)
    source = sys.stdin.buffer
    try:
        while True:
            line = source.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            try:
                if len(line) > MAX_LINE_BYTES:
                    while line and not line.endswith(b"\n"):
                        line = source.readline(MAX_LINE_BYTES + 1)
                    raise ValueError("request exceeds 65536 bytes")
                def no_constant(value):
                    raise ValueError("non-finite JSON numbers are not accepted")
                request = json.loads(line.decode("utf-8"), parse_constant=no_constant)
                response = service.handle(request)
            except (ValueError, UnicodeError, RecursionError) as exc:
                response = {"api_version": API_VERSION, "id": None, "ok": False,
                            "error": {"code": "invalid_json", "message": str(exc)}}
            # ASCII escapes also preserve malformed surrogate strings in error
            # responses without crashing the UTF-8 output stream.
            print(json.dumps(response, ensure_ascii=True, allow_nan=False), flush=True)
    except BrokenPipeError:
        return 0
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
