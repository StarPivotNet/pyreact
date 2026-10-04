"""Animation identity, transition interruption and exit callback regressions."""

import unittest

from pyreact import Animated, Animation, Button, Component, Panel, Transition, useState
from pyreact.browser.runtime import BrowserRuntime


class BrowserAnimationTests(unittest.TestCase):
    def runtime(self, component):
        runtime = BrowserRuntime(component)
        self.addCleanup(runtime.close)
        return runtime

    def complete(self, runtime, node):
        return runtime.dispatch(node['id'], 'animation_complete', {'runId': node['animation']['runId']})

    def test_enter_completion_runs_once(self):
        seen = []

        @Component
        def App():
            return Animated(children=Panel(), enter=Animation(from_={'opacity': 0},
                            to={'opacity': 1}, onComplete=lambda: seen.append('enter')))

        runtime = self.runtime(App)
        node = runtime.snapshot()['tree']
        node_id, run_id = node['id'], node['animation']['runId']
        self.assertEqual(node['animation']['phase'], 'enter')
        self.complete(runtime, node)
        runtime.dispatch(node_id, 'animation_complete', {'runId': run_id})
        self.assertEqual(seen, ['enter'])

    def test_first_animate_is_immediate_and_same_target_does_not_restart(self):
        setters = {}

        @Component
        def App():
            timing, set_timing = useState(300)
            setters['timing'] = set_timing
            return Animated(children=Panel(), animate=Transition({'width': 40}, duration=timing, delay=timing))

        runtime = self.runtime(App)
        first = runtime.snapshot()['tree']['animation']
        self.assertEqual(first['from'], {'width': 40})
        self.assertEqual((first['duration'], first['delay']), (0, 0))
        setters['timing'](500)
        self.assertEqual(runtime.snapshot()['tree']['animation']['runId'], first['runId'])

    def test_animate_interrupts_enter_in_same_commit(self):
        seen = []

        @Component
        def App():
            return Animated(children=Panel(), enter=Animation(from_={'opacity': 0},
                            to={'opacity': 1}, onComplete=lambda: seen.append('enter')),
                            animate=Transition({'opacity': .5}, duration=200))

        runtime = self.runtime(App)
        node = runtime.snapshot()['tree']
        self.assertEqual(node['animation']['phase'], 'animate')
        self.assertEqual(node['animation']['from'], {'opacity': 0})
        self.assertEqual(node['animation']['duration'], 200)
        self.complete(runtime, node)
        self.assertEqual(seen, [])

    def test_running_transition_timing_update_does_not_restart(self):
        setters = {}

        @Component
        def App():
            target, set_target = useState(10)
            timing, set_timing = useState(200)
            setters.update(target=set_target, timing=set_timing)
            return Animated(children=Panel(), animate=Transition({'width': target}, duration=timing))

        runtime = self.runtime(App)
        runtime.snapshot()
        setters['target'](20)
        run = runtime.snapshot()['tree']['animation']
        setters['timing'](700)
        current = runtime.snapshot()['tree']['animation']
        self.assertEqual(current['runId'], run['runId'])
        self.assertEqual(current['duration'], 200)

    def test_exit_has_no_active_handlers_and_remount_is_distinct(self):
        setters, seen = {}, []

        @Component
        def App():
            visible, set_visible = useState(True)
            setters['show'] = set_visible
            return Panel(children=[Animated(key='child', children=Button(onClick=lambda: seen.append('click')),
                         exit=Animation(to={'opacity': 0}, onComplete=lambda: seen.append('exit')))]
                         if visible else [])

        runtime = self.runtime(App)
        old_node = runtime.snapshot()['tree']['children'][0]
        setters['show'](False)
        snapshot = runtime.snapshot()
        exit_node = snapshot['exits'][0]
        with self.assertRaises(ValueError):
            runtime.dispatch(old_node['id'], 'click')
        setters['show'](True)
        fresh = runtime.snapshot()['tree']['children'][0]
        self.assertNotEqual(fresh['id'], old_node['id'])
        self.complete(runtime, exit_node)
        self.complete(runtime, exit_node)
        self.assertEqual(seen, ['exit'])
        self.assertEqual(runtime.snapshot()['exits'], [])

    def test_transition_changes_interrupt_previous_run(self):
        setters = {}

        @Component
        def App():
            target, set_target = useState(10)
            setters['target'] = set_target
            return Animated(children=Panel(), animate=Transition({'width': target}))

        runtime = self.runtime(App)
        node = runtime.snapshot()['tree']
        old_run = node['animation']['runId']
        setters['target'](20)
        current = runtime.snapshot()['tree']
        self.assertNotEqual(current['animation']['runId'], old_run)
        runtime.dispatch(node['id'], 'animation_complete', {'runId': old_run})
        self.assertEqual(runtime.snapshot()['tree']['animation']['to'], {'width': 20})

    def test_same_animation_does_not_restart_on_unrelated_state_update(self):
        setters = {}

        @Component
        def App():
            _, set_count = useState(0)
            setters['count'] = set_count
            return Animated(children=Panel(), enter=Animation(to={'opacity': 1}))

        runtime = self.runtime(App)
        first = runtime.snapshot()['tree']['animation']['runId']
        setters['count'](1)
        self.assertEqual(runtime.snapshot()['tree']['animation']['runId'], first)

    def test_reset_runtime_rejects_previous_session_completion(self):
        seen = []

        @Component
        def App():
            return Animated(children=Panel(), enter=Animation(to={'opacity': 1},
                            onComplete=lambda: seen.append('done')))

        before = self.runtime(App)
        old = before.snapshot()['tree']
        before.close()
        after = self.runtime(App)
        current = after.snapshot()['tree']
        self.assertNotEqual(old['id'], current['id'])
        self.complete(after, old)
        self.assertEqual(seen, [])
        self.complete(after, current)
        self.assertEqual(seen, ['done'])


if __name__ == '__main__':
    unittest.main()
