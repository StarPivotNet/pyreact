"""Deterministic, explicitly injected application ports for offline UI testing.

This is a Python 3 development utility, not a NetEase SDK implementation.
All callbacks run on the caller's thread; virtual time advances explicitly.
"""

from collections import deque
import heapq

from .scenario_trace import json_value, milliseconds, name_value, dumps_trace


class OfflineSession:
    """One isolated event bus, local RPC registry, virtual clock and trace."""

    def __init__(self):
        self.now_ms = 0
        self._listeners = {}
        self._handlers = {}
        self._responses = {}
        self._pending = {}
        self._queue = []
        self._sequence = 0
        self._request_id = 0
        self._records = []
        self._closed = False
        self._advancing = False

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError('Offline scenario session is closed')

    def _record(self, kind, **fields):
        record = {'version': 1, 'time_ms': self.now_ms, 'kind': kind}
        record.update(fields)
        self._records.append(json_value(record))

    @property
    def records(self):
        return json_value(self._records)

    def to_jsonl(self):
        return dumps_trace(self._records)

    def subscribe(self, name, callback):
        """Deduplicate the same name/callback pair; return an idempotent disposer."""
        self._ensure_open()
        name_value(name)
        if not callable(callback):
            raise TypeError('Event callback must be callable')
        listeners = self._listeners.setdefault(name, {})
        token = listeners.setdefault(callback, object())

        def unsubscribe():
            current = self._listeners.get(name, {})
            if current.get(callback) is token:
                del current[callback]
                if not current:
                    self._listeners.pop(name, None)
        return unsubscribe

    def emit(self, name, payload=None):
        self._ensure_open()
        name_value(name)
        payload = json_value(payload)
        self._record('event', name=name, payload=payload)
        listeners = list(self._listeners.get(name, {}).items())
        for callback, token in listeners:
            if self._listeners.get(name, {}).get(callback) is token:
                callback(json_value(payload))

    def register_rpc(self, method, handler):
        """Install a pure local handler. Exceptions remain visible to the caller."""
        self._ensure_open()
        name_value(method)
        if not callable(handler):
            raise TypeError('RPC handler must be callable')
        self._handlers[method] = handler

    def queue_response(self, method, value=None, error=None, delay_ms=0, drop=False):
        """Override the next call: value, rejection, delay or a dropped response."""
        self._ensure_open()
        name_value(method)
        milliseconds(delay_ms)
        if type(drop) is not bool or (error is not None and type(error) is not str):
            raise ValueError('drop must be boolean and error must be a string or None')
        if error is not None and value is not None:
            raise ValueError('A response cannot have both value and error')
        response = (json_value(value), error, delay_ms, drop)
        self._responses.setdefault(method, deque()).append(response)

    def request(self, method, payload, callback, timeout_ms=1000):
        """Queue one result; even immediate responses need advance(0)."""
        self._ensure_open()
        name_value(method)
        milliseconds(timeout_ms)
        if not callable(callback):
            raise TypeError('RPC callback must be callable')
        payload = json_value(payload)
        responses = self._responses.get(method)
        if responses:
            value, error, delay, drop = responses.popleft()
        else:
            handler = self._handlers.get(method)
            if handler is None:
                raise LookupError('No offline RPC handler or response for %s' % method)
            value, error, delay, drop = json_value(handler(json_value(payload))), None, 0, False
        self._request_id += 1
        request_id = self._request_id
        self._record('request', id=request_id, method=method, payload=payload)
        self._pending[request_id] = (method, callback, value, error)
        if not drop:
            status = 'error' if error is not None else 'ok'
            self._schedule(delay, request_id, status)
        self._schedule(timeout_ms, request_id, 'timeout')
        return request_id

    def _schedule(self, delay, request_id, status):
        self._sequence += 1
        heapq.heappush(self._queue, (self.now_ms + delay, self._sequence,
                                   request_id, status))

    def _finish(self, request_id, status, notify=True):
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return False
        method, callback, value, error = pending
        if status in ('timeout', 'cancelled'):
            value = None
            error = 'RPC timed out' if status == 'timeout' else 'RPC cancelled'
        if len(self._queue) > 2 * len(self._pending) + 64:
            self._queue = [item for item in self._queue if item[2] in self._pending]
            heapq.heapify(self._queue)
        result = {'id': request_id, 'method': method, 'status': status,
                  'value': value, 'error': error}
        self._record('result', **result)
        if notify:
            callback(json_value(result))
        return True

    def cancel(self, request_id):
        """Cancel without invoking a callback (safe for component unmount)."""
        if type(request_id) is not int or request_id < 1:
            raise ValueError('RPC ids must be positive integers')
        if self._closed:
            return False
        return self._finish(request_id, 'cancelled', notify=False)

    def advance(self, milliseconds_to_advance=0):
        """Run due callbacks once in time/order sequence; response wins timeout ties."""
        self._ensure_open()
        milliseconds(milliseconds_to_advance)
        if self._advancing:
            raise RuntimeError('Recursive scenario advance is not supported')
        target = self.now_ms + milliseconds_to_advance
        self._advancing = True
        count = 0
        try:
            while self._queue and self._queue[0][0] <= target and not self._closed:
                if self._queue[0][2] not in self._pending:
                    heapq.heappop(self._queue)
                    continue
                if count >= 10000:
                    raise RuntimeError('Scenario exceeded 10000 scheduled steps per advance')
                due, _, request_id, status = heapq.heappop(self._queue)
                self.now_ms = due
                self._finish(request_id, status)
                count += 1
            self.now_ms = target
            self._record('clock')
        finally:
            self._advancing = False

    def close(self):
        if self._closed:
            return
        for request_id in list(self._pending):
            self.cancel(request_id)
        self._closed = True
        self._listeners.clear()
        self._handlers.clear()
        self._responses.clear()
        self._queue.clear()
