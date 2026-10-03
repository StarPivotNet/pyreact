"""Loopback-only HTTP transport for local component acceptance testing."""
import json
import mimetypes
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .runtime import BrowserRuntime

STATIC_ROOT = Path(__file__).with_name("static")
MAX_BODY = 65536


class PreviewServer(ThreadingHTTPServer):
    def __init__(self, address, root, width, height, resource_root):
        self.root = root
        self.runtime = BrowserRuntime(root, width=width, height=height)
        self.resource_root = Path(resource_root).resolve() if resource_root else None
        self.lock = threading.RLock()
        super().__init__(address, PreviewHandler)

    def snapshot(self):
        result = self.runtime.snapshot()
        result["app"] = getattr(self.root, "__name__", "Component")
        return result

    def server_close(self):
        try:
            self.runtime.close()
        finally:
            super().server_close()


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "PyreactPreview/1.0"

    def _reply(self, status, data, content_type="application/json; charset=utf-8", attachment=False):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="pyreact-layout.json"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _trusted_request(self):
        port = self.server.server_port
        hosts = {"127.0.0.1:%s" % port, "localhost:%s" % port}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in hosts or (origin is not None and origin != "http://" + host):
            self._reply(403, {"error": "Only same-origin loopback requests are allowed"})
            return False
        return True

    def do_GET(self):
        if not self._trusted_request():
            return
        path = unquote(urlsplit(self.path).path)
        if path in ("/api/tree", "/api/export"):
            self._snapshot(attachment=path == "/api/export")
            return
        if path.startswith("/assets/"):
            self._asset(path[len("/assets/"):])
            return
        name = "index.html" if path == "/" else path.lstrip("/")
        if name not in {"index.html", "preview.css", "preview.js", "renderer.js"}:
            self._reply(404, {"error": "Not found"})
            return
        self._file(STATIC_ROOT / name)

    def _snapshot(self, attachment=False):
        try:
            with self.server.lock:
                self._reply(200, self.server.snapshot(), attachment=attachment)
        except Exception as error:
            self._runtime_error(error)

    def _asset(self, name):
        root = self.server.resource_root
        if root is None:
            self._reply(404, {"error": "No --resource-root configured"})
            return
        target = root / name
        if not target.suffix:
            target = target.with_suffix(".png")
        target = target.resolve()
        if not target.is_relative_to(root):
            self._reply(404, {"error": "Not found"})
            return
        if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            self._reply(404, {"error": "Unsupported preview asset"})
            return
        self._file(target)

    def _file(self, path):
        if not path.is_file():
            self._reply(404, {"error": "Not found"})
            return
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        try:
            self._reply(200, path.read_bytes(), mime)
        except OSError as error:
            self._reply(500, {"error": str(error)})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_BODY:
                raise ValueError("Body must contain 1..65536 bytes")
            body = self.rfile.read(length)
            if not self._trusted_request():
                return
            if self.headers.get_content_type() != "application/json":
                self._reply(415, {"error": "Expected application/json"})
                return
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
        except (ValueError, UnicodeError) as error:
            self._reply(400, {"error": str(error)})
            return
        try:
            with self.server.lock:
                self._action(urlsplit(self.path).path, data)
        except (KeyError, ValueError, TypeError) as error:
            self._reply(400, {"error": str(error)})
        except Exception as error:
            self._runtime_error(error)

    def _action(self, path, data):
        runtime = self.server.runtime
        if path == "/api/event":
            runtime.dispatch(data["id"], data["event"], data.get("value"))
        elif path == "/api/resize":
            runtime.resize(data["width"], data["height"])
        elif path == "/api/reset":
            width, height = runtime.width, runtime.height
            runtime.close()
            self.server.runtime = BrowserRuntime(self.server.root, width, height)
        else:
            self._reply(404, {"error": "Not found"})
            return
        self._reply(200, self.server.snapshot())

    def _runtime_error(self, error):
        traceback.print_exc()
        self._reply(500, {"error": "%s: %s" % (type(error).__name__, error)})

    def log_message(self, format_, *args):
        if args and str(args[1]) != "200":
            super().log_message(format_, *args)


def create_server(root, host="127.0.0.1", port=0, width=960, height=640, resource_root=None):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Browser preview only binds to localhost")
    if resource_root and not Path(resource_root).is_dir():
        raise ValueError("--resource-root must be an existing directory")
    return PreviewServer((host, port), root, width, height, resource_root)


def serve(root, host="127.0.0.1", port=8765, width=960, height=640,
          resource_root=None, open_browser=True):
    server = create_server(root, host, port, width, height, resource_root)
    url = "http://127.0.0.1:%s" % server.server_port
    print("Pyreact browser preview: %s\nPress Ctrl+C to stop." % url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPreview stopped.")
    finally:
        server.server_close()
