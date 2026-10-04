"""Validate ordered pointer streams before invoking Python UI callbacks."""

import math


class TouchStreams:
    def __init__(self):
        self.streams = {}

    def validate(self, node_id, value):
        if not isinstance(value, dict):
            raise ValueError('Touch value must be an object')
        kind = value.get('TouchEvent')
        if type(kind) is not int or kind not in (0, 1, 3, 4, 6, 7):
            raise ValueError('Unsupported TouchEvent')
        for name in ('TouchPosX', 'TouchPosY'):
            coord = value.get(name)
            if isinstance(coord, bool) or not isinstance(coord, (int, float)) or not math.isfinite(coord):
                raise ValueError('Touch coordinates must be finite numbers')
        pointer = value.get('pointerId', 0)
        sequence = value.get('sequence')
        if type(pointer) is not int or (sequence is not None and
                                      (type(sequence) is not int or sequence < 0)):
            raise ValueError('Touch pointerId and sequence must be integers')
        token = (node_id, pointer)
        previous = self.streams.get(token)
        if previous is not None and previous >= 0 and sequence is None:
            raise ValueError('An ordered touch stream requires a sequence on every event')
        if previous is not None and sequence is not None and sequence <= previous:
            return None
        if kind == 1 and any(active[0] == node_id for active in self.streams):
            return None
        if kind != 1 and token not in self.streams:
            return None
        if kind in (0, 3, 7):
            self.streams.pop(token, None)
        else:
            self.streams[token] = sequence if sequence is not None else -1
        return dict(value)

    def retain(self, handlers):
        self.streams = {token: seq for token, seq in self.streams.items()
                        if 'onTouch' in handlers.get(token[0], {})}
