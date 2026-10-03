"""HTTP boundary checks against an actual loopback preview server."""

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from pyreact.browser.server import create_server
from pyreact import Button, Component, Label, useState
from PyreactExampleScript.examples.CounterDemo import CounterDemo


class BrowserServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.resources = Path(self.temp.name) / "resources"
        self.resources.mkdir()
        (self.resources / "sample.png").write_bytes(b"preview resource")
        (Path(self.temp.name) / "private.png").write_bytes(b"private image")
        self.server = create_server(CounterDemo, port=0, resource_root=self.resources)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.host, self.port = self.server.server_address
        self.origin = "http://%s:%s" % (self.host, self.port)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, path, body=None, headers=None, method=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(method or ("POST" if body is not None else "GET"),
                               path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def post(self, path, payload, headers=None):
        request_headers = {"Content-Type": "application/json", "Origin": self.origin}
        request_headers.update(headers or {})
        return self.request(path, json.dumps(payload), request_headers)

    def test_tree_endpoint_and_viewport_update(self):
        status, body, headers = self.request("/api/tree")
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        self.assertEqual(snapshot["tree"]["type"], "Panel")
        self.assertIn("application/json", headers["Content-Type"])
        status, _, _ = self.post("/api/resize", {"width": 480, "height": 320})
        self.assertEqual(status, 200)
        snapshot = json.loads(self.request("/api/tree")[1])
        self.assertEqual((snapshot["width"], snapshot["height"]), (480, 320))

    def test_invalid_origin_cannot_mutate_state(self):
        for origin in ("https://evil.example", "null", "http://localhost:1"):
            with self.subTest(origin=origin):
                status, _, _ = self.post("/api/resize", {"width": 480, "height": 320},
                                         {"Origin": origin})
                self.assertEqual(status, 403)
        snapshot = json.loads(self.request("/api/tree")[1])
        self.assertEqual((snapshot["width"], snapshot["height"]), (960, 640))

    def test_invalid_host_is_rejected(self):
        status, _, _ = self.request("/api/tree", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_malformed_json_returns_client_error_and_server_recovers(self):
        status, _, _ = self.request("/api/event", "{not json",
                                    {"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertEqual(self.request("/api/tree")[0], 200)

    def test_non_json_body_is_rejected(self):
        status, _, _ = self.request("/api/event", "{}", {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)

    def test_missing_target_returns_client_error(self):
        status, _, _ = self.post("/api/event", {"id": "missing", "event": "click"})
        self.assertEqual(status, 400)

    def test_click_and_reset_run_component_lifecycle(self):
        def walk(node):
            yield node
            for child in node.get("children", []):
                yield from walk(child)

        snapshot = json.loads(self.request("/api/tree")[1])
        button = next(node for node in walk(snapshot["tree"]) if node["type"] == "Button")
        status, body, _ = self.post("/api/event", {"id": button["id"], "event": "click"})
        self.assertEqual(status, 200)
        labels = [node.get("props", {}).get("content") for node in walk(json.loads(body)["tree"])]
        self.assertIn("Count: 1", labels)
        status, body, _ = self.post("/api/reset", {})
        self.assertEqual(status, 200)
        labels = [node.get("props", {}).get("content") for node in walk(json.loads(body)["tree"])]
        self.assertIn("Count: 0", labels)

    def test_resource_inside_root_is_available_with_or_without_extension(self):
        for path in ("/assets/sample.png", "/assets/sample"):
            with self.subTest(path=path):
                status, body, headers = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(body, b"preview resource")
                self.assertIn("image/png", headers["Content-Type"])

    def test_export_downloads_current_tree_as_attachment(self):
        current = json.loads(self.request("/api/tree")[1])
        status, body, headers = self.request("/api/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("pyreact-layout.json", headers["Content-Disposition"])
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(json.loads(body), current)

    def test_reset_recovers_from_failed_render_without_reusing_stale_tree(self):
        @Component
        def FailingAfterClick():
            broken, set_broken = useState(False)
            if broken:
                raise RuntimeError("deliberate component failure")
            return Button(onClick=lambda: set_broken(True), children=Label(content="Ready"))

        self.server.root = FailingAfterClick
        status, body, _ = self.post("/api/reset", {})
        self.assertEqual(status, 200)
        button_id = json.loads(body)["tree"]["id"]
        status, body, _ = self.post("/api/event", {"id": button_id, "event": "click"})
        self.assertEqual(status, 500)
        self.assertIn("deliberate component failure", json.loads(body)["error"])
        for _ in range(2):
            status, body, _ = self.request("/api/tree")
            self.assertEqual(status, 500)
            self.assertIn("deliberate component failure", json.loads(body)["error"])
        status, body, _ = self.post("/api/reset", {})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["tree"]["children"][0]["props"]["content"], "Ready")

    def test_resources_cannot_escape_root(self):
        for path in ("/assets/../private.png", "/assets/%2e%2e/private.png",
                     "/assets/%2e%2e%5cprivate.png", "/assets/C:/Windows/win.ini"):
            with self.subTest(path=path):
                status, body, _ = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"private", body)


if __name__ == "__main__":
    unittest.main()
