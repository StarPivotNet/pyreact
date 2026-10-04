"""Deterministic offline application boundary behavior and safe trace replay."""

import json
import unittest
from unittest.mock import patch

from pyreact.browser.scenarios import OfflineSession
from pyreact.browser.scenario_trace import dumps_trace, loads_trace, replay_trace


class OfflineScenarioTests(unittest.TestCase):
    def setUp(self):
        self.port = OfflineSession()
        self.addCleanup(self.port.close)

    def test_duplicate_subscription_and_disposer_lifetime(self):
        received = []
        unsubscribe = self.port.subscribe('stock', received.append)
        duplicate = self.port.subscribe('stock', received.append)
        self.port.emit('stock', 1)
        self.assertEqual(received, [1])
        unsubscribe()
        self.port.subscribe('stock', received.append)
        duplicate()  # A stale disposer must not remove a later registration.
        self.port.emit('stock', 2)
        self.assertEqual(received, [1, 2])

    def test_unsubscribe_during_dispatch_and_payload_isolation(self):
        received = []
        dispose = None

        def first(payload):
            payload['stock'] = 99
            dispose()
        self.port.subscribe('stock', first)
        dispose = self.port.subscribe('stock', received.append)
        payload = {'stock': 1}
        self.port.emit('stock', payload)
        self.assertEqual(received, [])
        self.assertEqual(payload, {'stock': 1})
        self.assertEqual(self.port.records[0]['payload'], payload)

    def test_local_handler_and_scripted_rejection(self):
        results = []
        self.port.register_rpc('double', lambda payload: payload['value'] * 2)
        self.port.request('double', {'value': 3}, results.append)
        self.assertEqual(results, [])
        self.port.advance()
        self.assertEqual(results[-1]['value'], 6)
        self.port.queue_response('double', error='denied')
        self.port.request('double', {}, results.append)
        self.port.advance()
        self.assertEqual((results[-1]['status'], results[-1]['error']), ('error', 'denied'))

    def test_delay_timeout_and_late_response_do_not_double_complete(self):
        results = []
        self.port.queue_response('save', value='late', delay_ms=1500)
        self.port.request('save', {}, results.append, timeout_ms=1000)
        self.port.advance(999)
        self.assertEqual(results, [])
        self.port.advance(1)
        self.assertEqual(results[0]['status'], 'timeout')
        self.port.advance(1000)
        self.assertEqual(len(results), 1)
        self.port.queue_response('save', value='delayed', delay_ms=500)
        self.port.request('save', {}, results.append)
        self.port.advance(499)
        self.assertEqual(len(results), 1)
        self.port.advance(1)
        self.assertEqual(results[-1]['value'], 'delayed')

    def test_response_wins_exact_timeout_tie_and_drop_times_out(self):
        results = []
        self.port.queue_response('save', value=True, delay_ms=100)
        self.port.request('save', {}, results.append, timeout_ms=100)
        self.port.advance(100)
        self.assertEqual(results[0]['status'], 'ok')
        self.port.queue_response('save', drop=True)
        self.port.request('save', {}, results.append, timeout_ms=100)
        self.port.advance(100)
        self.assertEqual(results[1]['status'], 'timeout')

    def test_cancel_and_close_never_invoke_pending_callbacks(self):
        results = []
        self.port.queue_response('save', value=True, delay_ms=10)
        request_id = self.port.request('save', {}, results.append)
        self.assertTrue(self.port.cancel(request_id))
        self.assertFalse(self.port.cancel(request_id))
        self.port.advance(1000)
        self.assertEqual(results, [])
        self.port.queue_response('save', value=True)
        self.port.request('save', {}, results.append)
        self.port.close()
        self.port.close()
        self.assertEqual(results, [])
        self.assertEqual(self.port.records[-1]['status'], 'cancelled')
        replay_trace(self.port.records, results.append, results.append)
        self.assertEqual(results, [])
        with self.assertRaises(RuntimeError):
            self.port.advance(0)

    def test_roundtrip_replay_preserves_messages_timestamps_and_order(self):
        delivered = []
        self.port.subscribe('stock', lambda value: delivered.append(('event', value)))
        self.port.emit('stock', {'stock': 2})
        self.port.queue_response('save', value={'saved': True}, delay_ms=10)
        self.port.request('save', {}, lambda value: delivered.append(('result', value)))
        self.port.advance(10)
        self.port.emit('stock', {'stock': 3})
        records = loads_trace(self.port.to_jsonl())
        replayed = []

        def result(row):
            replayed.append(('result', {key: row[key] for key in
                             ('id', 'method', 'status', 'value', 'error')}))
        end = replay_trace(records, lambda row: replayed.append(('event', row['payload'])), result)
        self.assertEqual(delivered, replayed)
        self.assertEqual(end, 10)
        self.assertEqual(records, loads_trace(dumps_trace(records)))

    def test_replay_callback_can_mutate_last_record_without_losing_end_time(self):
        self.port.advance(30)
        self.port.emit('stock', {'stock': 1})
        records = self.port.records
        self.assertEqual(replay_trace(records, lambda row: row.clear(), lambda row: None), 30)
        self.assertEqual(records[-1]['payload'], {'stock': 1})
        self.port.queue_response('save', value=True)
        self.port.request('save', {}, lambda result: None)
        self.port.advance()
        records = self.port.records[:-1]  # Result is now the final record.
        self.assertEqual(replay_trace(records, lambda row: None, lambda row: row.clear()), 30)

    def test_cancelled_requests_release_scheduled_values_and_do_not_hit_step_limit(self):
        for _ in range(5001):
            self.port.queue_response('save', value={'large': 'x' * 100}, delay_ms=10)
            request_id = self.port.request('save', {}, lambda result: self.fail('cancelled'))
            self.port.cancel(request_id)
        self.assertEqual(self.port._pending, {})
        self.assertLessEqual(len(self.port._queue), 64)
        self.assertTrue(all(len(item) == 4 for item in self.port._queue))
        self.port.advance(1000)
        self.assertEqual(self.port._queue, [])

    def test_callback_can_schedule_another_immediate_request(self):
        results = []
        self.port.register_rpc('save', lambda payload: payload)

        def first(result):
            results.append(result['value'])
            self.port.request('save', 2, lambda row: results.append(row['value']))
        self.port.request('save', 1, first)
        self.port.advance()
        self.assertEqual(results, [1, 2])
        self.assertEqual(self.port._pending, {})

    def test_callback_exception_leaves_other_requests_available(self):
        results = []
        self.port.register_rpc('save', lambda payload: payload)

        def broken(result):
            raise ValueError('visible failure')
        self.port.request('save', 1, broken)
        self.port.request('save', 2, lambda row: results.append(row['value']))
        with self.assertRaisesRegex(ValueError, 'visible failure'):
            self.port.advance()
        self.port.advance()
        self.assertEqual(results, [2])
        self.assertEqual(self.port._pending, {})

    def test_trace_is_data_and_validated_before_any_callback(self):
        attack = "__import__('os').system('echo unexpected')"
        self.port.emit('stock', {'text': attack})
        records = loads_trace(self.port.to_jsonl())
        seen = []
        with patch('os.system') as system:
            replay_trace(records, seen.append, seen.append)
            system.assert_not_called()
        self.assertEqual(seen[0]['payload']['text'], attack)
        records.append({'version': 1, 'time_ms': 0, 'kind': 'execute', 'code': attack})
        seen.clear()
        with self.assertRaises(ValueError):
            replay_trace(records, seen.append, seen.append)
        self.assertEqual(seen, [])

    def test_reject_malformed_rpc_pairs_time_and_data(self):
        self.port.queue_response('save', value=True)
        self.port.request('save', {}, lambda result: None)
        self.port.advance()
        records = self.port.records
        records[1]['id'] = 123
        with self.assertRaises(ValueError):
            dumps_trace(records)
        for invalid in (float('nan'), object(), {1: 'key'}, (1, 2)):
            with self.assertRaises(ValueError):
                self.port.emit('stock', invalid)
        for invalid in (-1, True, 0.5):
            with self.assertRaises(ValueError):
                self.port.advance(invalid)
        with self.assertRaises(ValueError):
            loads_trace(json.dumps({'version': 1, 'time_ms': 0, 'kind': []}))

    def test_unknown_handler_and_handler_exception_are_visible(self):
        with self.assertRaises(LookupError):
            self.port.request('missing', {}, lambda result: None)
        self.port.register_rpc('broken', lambda payload: 1 / 0)
        with self.assertRaises(ZeroDivisionError):
            self.port.request('broken', {}, lambda result: None)
        self.assertEqual(self.port.records, [])

    def test_scenario_demo_runs_component_state_and_effect_cleanup(self):
        from pyreact import Component
        from pyreact.browser.runtime import BrowserRuntime
        from pyreact.browser.scenario_demo import ScenarioPanel

        @Component
        def App():
            return ScenarioPanel(port=self.port)

        runtime = BrowserRuntime(App)
        self.addCleanup(runtime.close)

        def nodes(tree):
            yield tree
            for child in tree.get('children', []):
                for node in nodes(child):
                    yield node

        def labels():
            return [node.get('props', {}).get('content', '')
                    for node in nodes(runtime.snapshot()['tree']) if node['type'] == 'Label']

        runtime.snapshot()
        self.port.emit('inventory.changed', {'stock': 7})
        self.assertTrue(any('库存：7' in text for text in labels()))
        buttons = [node for node in nodes(runtime.snapshot()['tree']) if node['type'] == 'Button']
        runtime.dispatch(buttons[1]['id'], 'click')
        self.assertTrue(any('订单已接受' in text for text in labels()))
        runtime.dispatch(buttons[3]['id'], 'click')
        self.assertTrue(any('等待响应' in text for text in labels()))
        runtime.dispatch(buttons[5]['id'], 'click')
        self.assertTrue(any('延迟订单已接受' in text for text in labels()))
        runtime.dispatch(buttons[4]['id'], 'click')
        runtime.dispatch(buttons[5]['id'], 'click')
        self.assertTrue(any('等待响应' in text for text in labels()))
        runtime.dispatch(buttons[5]['id'], 'click')
        self.assertTrue(any('timeout' in text for text in labels()))
        runtime.dispatch(buttons[6]['id'], 'click')
        self.assertTrue(any('已回放' in text for text in labels()))
        runtime.dispatch(buttons[3]['id'], 'click')
        runtime.close()
        self.assertEqual(self.port._listeners, {})
        self.assertEqual(self.port._pending, {})


if __name__ == '__main__':
    unittest.main()
