"""Data-only JSONL recording of an application's event/RPC boundary."""

import json
import math


def json_value(value):
    """Copy JSON data without silently coercing keys, tuples or nonfinite values."""
    def check(item, depth=0):
        if depth > 32:
            raise ValueError('Scenario data exceeds 32 nesting levels')
        if item is None or type(item) in (bool, int, str):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                check(child, depth + 1)
            return
        raise ValueError('Scenario data must contain only finite JSON values')
    check(value)
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def milliseconds(value):
    if type(value) is not int or value < 0:
        raise ValueError('Scenario time must be a nonnegative integer in milliseconds')
    return value


def name_value(value):
    if type(value) is not str or not value or len(value) > 256:
        raise ValueError('Scenario names must be nonempty strings of at most 256 characters')
    return value


_FIELDS = {
    'event': {'name', 'payload'},
    'request': {'id', 'method', 'payload'},
    'result': {'id', 'method', 'status', 'value', 'error'},
    'clock': set(),
}


def validate_trace(records):
    """Validate the entire trace before replay can invoke a callback."""
    records = json_value(records)
    if type(records) is not list or len(records) > 10000:
        raise ValueError('A trace must be a list with at most 10000 records')
    previous = 0
    requests, finished = {}, set()
    for record in records:
        if type(record) is not dict:
            raise ValueError('Each trace record must be an object')
        kind = record.get('kind')
        if type(kind) is not str or kind not in _FIELDS:
            raise ValueError('Unsupported scenario record kind')
        if set(record) != _FIELDS[kind] | {'version', 'time_ms', 'kind'}:
            raise ValueError('Unexpected or missing scenario record fields')
        if type(record['version']) is not int or record['version'] != 1:
            raise ValueError('Unsupported scenario trace version')
        timestamp = milliseconds(record['time_ms'])
        if timestamp < previous:
            raise ValueError('Scenario trace time must be nondecreasing')
        previous = timestamp
        if kind == 'event':
            name_value(record['name'])
        elif kind in ('request', 'result'):
            request_id = record['id']
            if type(request_id) is not int or request_id < 1:
                raise ValueError('RPC ids must be positive integers')
            name_value(record['method'])
            if kind == 'request':
                if request_id in requests:
                    raise ValueError('Duplicate RPC request id')
                requests[request_id] = record['method']
            else:
                _validate_result(record, requests, finished)
    return records


def _validate_result(record, requests, finished):
    request_id = record['id']
    if requests.get(request_id) != record['method'] or request_id in finished:
        raise ValueError('RPC result must match one unfinished request')
    status = record['status']
    if type(status) is not str or status not in ('ok', 'error', 'timeout', 'cancelled'):
        raise ValueError('Unsupported RPC result status')
    if status == 'ok':
        if record['error'] is not None:
            raise ValueError('Successful RPC result cannot contain an error')
    elif record['value'] is not None or type(record['error']) is not str:
        raise ValueError('Failed RPC result needs an error string and no value')
    finished.add(request_id)


def dumps_trace(records):
    records = validate_trace(records)
    return ''.join(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n'
                   for record in records)


def loads_trace(text):
    if type(text) is not str or len(text.encode('utf-8')) > 4 * 1024 * 1024:
        raise ValueError('Scenario trace must be UTF-8 text no larger than 4 MiB')
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 10000:
        raise ValueError('Scenario trace exceeds 10000 records')
    return validate_trace([json.loads(line) for line in lines])


def replay_trace(records, on_event, on_result):
    """Deliver recorded outputs in order, synchronously, without executing RPCs.

    Callbacks receive full record dictionaries, including virtual timestamps.
    Request/clock/cancellation records are validated but not dispatched. No imports, eval,
    filesystem paths or real network requests are interpreted from trace data.
    """
    records = validate_trace(records)
    if not callable(on_event) or not callable(on_result):
        raise TypeError('Replay callbacks must be callable')
    end_time = records[-1]['time_ms'] if records else 0
    for record in records:
        if record['kind'] == 'event':
            on_event(record)
        elif record['kind'] == 'result' and record['status'] != 'cancelled':
            on_result(record)
    return end_time
