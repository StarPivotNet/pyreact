"""Behavior checks for the browser adapter using actual Python components."""

import unittest

from pyreact import Button, Component, Input, Label, Panel, useEffect, useState
from pyreact.browser.runtime import BrowserRuntime
from PyreactExampleScript.examples.CounterDemo import CounterDemo


def nodes(tree):
    yield tree
    for child in tree.get("children", []):
        for node in nodes(child):
            yield node


def find_node(snapshot, node_type):
    return next(node for node in nodes(snapshot["tree"])
                if node["type"] == node_type)


def text_content(snapshot):
    return [node.get("props", {}).get("content")
            for node in nodes(snapshot["tree"]) if node["type"] == "Label"]


class BrowserRuntimeTests(unittest.TestCase):
    def make_runtime(self, root=CounterDemo, **kwargs):
        runtime = BrowserRuntime(root, **kwargs)
        self.addCleanup(runtime.close)
        return runtime

    def test_existing_counter_runs_real_callback_repeatedly(self):
        runtime = self.make_runtime()
        snapshot = runtime.snapshot()
        self.assertIn("Count: 0", text_content(snapshot))
        first_revision = snapshot["revision"]
        for count in range(1, 4):
            button = find_node(snapshot, "Button")
            runtime.dispatch(button["id"], "click")
            snapshot = runtime.snapshot()
            self.assertIn("Count: %d" % count, text_content(snapshot))
        self.assertGreater(snapshot["revision"], first_revision)

    def test_controlled_input_updates_python_state(self):
        @Component
        def Editor():
            value, set_value = useState("")
            return Panel(children=[
                Input(value=value, onChange=set_value, placeholder="Search"),
                Label(content="Value: " + value),
            ])

        runtime = self.make_runtime(Editor)
        for value in ("night", "中文输入", ""):
            field = find_node(runtime.snapshot(), "Input")
            runtime.dispatch(field["id"], "input", value)
            snapshot = runtime.snapshot()
            self.assertEqual(find_node(snapshot, "Input")["props"]["value"], value)
            self.assertIn("Value: " + value, text_content(snapshot))

    def test_close_cleans_effect_once(self):
        calls = []

        @Component
        def WithEffect():
            def effect():
                calls.append("mounted")
                return lambda: calls.append("cleaned")
            useEffect(effect, [])
            return Label(content="Effect")

        runtime = self.make_runtime(WithEffect)
        runtime.snapshot()
        self.assertEqual(calls, ["mounted"])
        runtime.close()
        runtime.close()
        self.assertEqual(calls, ["mounted", "cleaned"])

    def test_resize_recalculates_root_dimensions_and_keeps_state(self):
        runtime = self.make_runtime()
        runtime.dispatch(find_node(runtime.snapshot(), "Button")["id"], "click")
        runtime.resize(480, 320)
        snapshot = runtime.snapshot()
        self.assertEqual((snapshot["width"], snapshot["height"]), (480, 320))
        self.assertEqual(snapshot["tree"]["layout"]["width"], 480)
        self.assertEqual(snapshot["tree"]["layout"]["height"], 320)
        self.assertIn("Count: 1", text_content(snapshot))

    def test_unknown_target_or_event_cannot_invoke_callback(self):
        runtime = self.make_runtime()
        with self.assertRaises((KeyError, ValueError)):
            runtime.dispatch("missing", "click")
        button = find_node(runtime.snapshot(), "Button")
        with self.assertRaises((KeyError, ValueError)):
            runtime.dispatch(button["id"], "execute")
        self.assertIn("Count: 0", text_content(runtime.snapshot()))

    def test_invalid_sizes_do_not_replace_current_viewport(self):
        runtime = self.make_runtime(width=640, height=480)
        for width, height in ((0, 480), (-1, 480), (640, 0),
                              (float("nan"), 480), (640, float("inf"))):
            with self.subTest(width=width, height=height):
                with self.assertRaises((TypeError, ValueError, OverflowError)):
                    runtime.resize(width, height)
                snapshot = runtime.snapshot()
                self.assertEqual((snapshot["width"], snapshot["height"]), (640, 480))

    def test_failed_render_never_exposes_previous_successful_snapshot(self):
        @Component
        def FailingAfterClick():
            broken, set_broken = useState(False)
            if broken:
                raise RuntimeError("deliberate component failure")
            return Button(onClick=lambda: set_broken(True), children=Label(content="Ready"))

        runtime = self.make_runtime(FailingAfterClick)
        button = find_node(runtime.snapshot(), "Button")
        with self.assertRaisesRegex(RuntimeError, "deliberate component failure"):
            runtime.dispatch(button["id"], "click")
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "deliberate component failure"):
                runtime.snapshot()


if __name__ == "__main__":
    unittest.main()
