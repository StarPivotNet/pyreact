"""Exercise browser refs and touch streams through actual component callbacks."""

import unittest

from pyreact import Button, Component, Label, Panel, Slider, Style, useEffect, useRef, useState
from pyreact.browser.runtime import BrowserRuntime


def walk(tree):
    yield tree
    for child in tree['children']:
        yield from walk(child)


class BrowserControlsTests(unittest.TestCase):
    def runtime(self, component):
        runtime = BrowserRuntime(component)
        self.addCleanup(runtime.close)
        return runtime

    def test_refs_bound_before_effects_and_unbound_on_close(self):
        refs, positions = [], []

        @Component
        def App():
            ref = useRef(None)
            refs[:] = [ref]
            useEffect(lambda: positions.append(ref.current.GetSize()), [])
            return Panel(children=Panel(ref=ref, style=Style(width=120, height=30)))

        runtime = self.runtime(App)
        runtime.snapshot()
        self.assertEqual(positions, [(120, 30)])
        control = refs[0].current
        control.SetPosition((5, 8))
        control.SetSize((150, 40))
        node = runtime.snapshot()['tree']['children'][0]
        self.assertEqual((node['layout']['x'], node['layout']['y']), (5, 8))
        self.assertEqual(control.GetSize(), (150, 40))
        runtime.close()
        self.assertIsNone(refs[0].current)
        with self.assertRaises(RuntimeError):
            control.GetSize()

    def test_callback_ref_replacement_and_unmount(self):
        refs, updates = [], {}

        @Component
        def App():
            shown, set_shown = useState(True)
            updates['show'] = set_shown
            return Panel(children=[Panel(key='child', ref=refs.append)] if shown else [])

        runtime = self.runtime(App)
        runtime.snapshot()
        self.assertEqual(len(refs), 1)
        updates['show'](False)
        runtime.snapshot()
        self.assertEqual(refs[-1], None)

    def test_ref_replacement_detaches_old_ref_without_replacing_control(self):
        first, second, updates = [], [], {}
        callbacks = (first.append, second.append)

        @Component
        def App():
            index, set_index = useState(0)
            updates['index'] = set_index
            return Panel(ref=callbacks[index])

        runtime = self.runtime(App)
        runtime.snapshot()
        control = first[0]
        updates['index'](1)
        runtime.snapshot()
        self.assertEqual(first, [control, None])
        self.assertEqual(second, [control])
        runtime.close()
        self.assertEqual(second, [control, None])

    def test_parent_scoped_key_and_reorder_and_remount_identity(self):
        updates = {}

        @Component
        def App():
            keys, set_keys = useState(['a', 'b'])
            updates['keys'] = set_keys
            return Panel(children=[
                Panel(key='left', children=[Label(key=key, content=key) for key in keys]),
                Panel(key='right', children=Label(key='a', content='other')),
            ])

        runtime = self.runtime(App)

        def ids():
            return {node['props']['content']: node['id'] for node in walk(runtime.snapshot()['tree'])
                    if node['type'] == 'Label'}

        initial = ids()
        self.assertNotEqual(initial['a'], initial['other'])
        updates['keys'](['b', 'a'])
        self.assertEqual(initial, ids())
        updates['keys'](['b'])
        ids()
        updates['keys'](['a', 'b'])
        self.assertNotEqual(initial['a'], ids()['a'])

    def test_slider_drag_uses_refs_steps_and_ordered_coordinates(self):
        values, starts, ends = [], [], []

        @Component
        def App():
            return Panel(style=Style(padding=20), children=Slider(
                defaultValue=0, step=10, onChange=values.append,
                onDragStart=starts.append, onDragEnd=ends.append))

        runtime = self.runtime(App)
        snapshot = runtime.snapshot()
        button = next(node for node in walk(snapshot['tree']) if node['props'].get('onTouch'))
        node_id = button['id']
        x = button['layout']['x']

        def touch(kind, pos, seq):
            return runtime.dispatch(node_id, 'touch', {'TouchEvent': kind, 'TouchPosX': pos,
                                    'TouchPosY': 25, 'pointerId': 1, 'sequence': seq})

        touch(1, x, 1)
        touch(4, x + 95, 3)
        touch(4, x + 20, 2)
        touch(0, x + 180, 4)
        self.assertEqual(values, [0, 50, 100])
        self.assertEqual(starts, [0])
        self.assertEqual(ends, [100])
        self.assertEqual(button['id'], next(node['id'] for node in walk(runtime.snapshot()['tree'])
                                          if node['props'].get('onTouch')))

    def test_invalid_touch_cannot_invoke_handler(self):
        seen = []

        @Component
        def App():
            return Button(onTouch=seen.append)

        runtime = self.runtime(App)
        node_id = runtime.snapshot()['tree']['id']
        for value in (None, {}, {'TouchEvent': 1, 'TouchPosX': float('nan'), 'TouchPosY': 0},
                      {'TouchEvent': True, 'TouchPosX': 0, 'TouchPosY': 0}):
            with self.assertRaises(ValueError):
                runtime.dispatch(node_id, 'touch', value)
        runtime.dispatch(node_id, 'touch', {'TouchEvent': 4, 'TouchPosX': 0, 'TouchPosY': 0})
        self.assertEqual(seen, [])

    def test_touch_rejects_duplicate_press_second_pointer_and_missing_sequence(self):
        seen = []

        @Component
        def App():
            return Button(onTouch=seen.append)

        runtime = self.runtime(App)
        node_id = runtime.snapshot()['tree']['id']

        def touch(kind, pointer=1, sequence=1):
            return runtime.dispatch(node_id, 'touch', {'TouchEvent': kind, 'TouchPosX': 10,
                                    'TouchPosY': 10, 'pointerId': pointer, 'sequence': sequence})

        touch(1)
        touch(1, sequence=2)
        touch(1, pointer=2, sequence=3)
        with self.assertRaises(ValueError):
            touch(4, sequence=None)
        touch(0, sequence=4)
        touch(4, sequence=5)
        self.assertEqual([event['TouchEvent'] for event in seen], [1, 0])

    def test_removing_touch_handler_cancels_stream_even_when_click_remains(self):
        seen, updates = [], {}

        @Component
        def App():
            enabled, set_enabled = useState(True)
            updates['enabled'] = set_enabled
            return Button(onTouch=seen.append if enabled else None, onClick=lambda: None)

        runtime = self.runtime(App)
        node_id = runtime.snapshot()['tree']['id']

        def touch(kind):
            return runtime.dispatch(node_id, 'touch', {'TouchEvent': kind, 'TouchPosX': 0, 'TouchPosY': 0})

        touch(1)
        updates['enabled'](False)
        runtime.snapshot()
        updates['enabled'](True)
        runtime.snapshot()
        touch(4)
        self.assertEqual([event['TouchEvent'] for event in seen], [1])


if __name__ == '__main__':
    unittest.main()
