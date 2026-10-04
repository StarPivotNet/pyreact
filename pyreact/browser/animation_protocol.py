"""Animation descriptions and per-instance completion bookkeeping."""

import copy
import math

from ..animation.animation import Animation
from ..animation.transition import normalize_animate


def numbers(values):
    return {key: value for key, value in values.items() if math.isfinite(value)}


def description(value, phase):
    if phase == 'animate':
        target, duration, delay, easing = normalize_animate(value)
        if not target:
            return None
        origin, callback = {}, None
    elif isinstance(value, Animation):
        origin, target = value.from_, value.to
        duration, delay, easing, callback = value.duration, value.delay, value.easing, value.onComplete
        if not target:
            return None
    else:
        return None
    easing_name = getattr(easing, '__name__', 'linear')
    known = ('linear', 'easeInQuad', 'easeOutQuad', 'easeInOutQuad', 'easeInCubic',
             'easeOutCubic', 'easeInOutCubic', 'easeInBack', 'easeOutBack')
    result = {'phase': phase, 'from': numbers(origin), 'to': numbers(target),
              'duration': duration, 'delay': delay, 'easing': easing_name if easing_name in known else 'linear'}
    if easing_name not in known and callable(easing):
        samples = [float(easing(index / 100.0)) for index in range(101)]
        if all(math.isfinite(value) for value in samples):
            result['easingSamples'] = samples
    return result, callback


def walk(tree):
    if tree is None:
        return
    yield tree
    for child in tree['children']:
        yield from walk(child)
    for child in tree.get('states', {}).values():
        yield from walk(child)


class AnimationRegistry:
    def __init__(self):
        self.active, self.configs, self.runs, self.exits = {}, {}, {}, {}
        self.targets = {}
        self.serial = 0

    def _start(self, node, parsed):
        node_id = node['id']
        spec, callback = parsed
        self.serial += 1
        animation = dict(spec, runId='animation-%s' % self.serial)
        node['animation'] = animation
        self.runs[node_id] = {'animation': animation, 'callback': callback, 'completed': False}

    def update(self, tree, configs):
        nodes = {node['id']: node for node in walk(tree)}
        for node_id, node in nodes.items():
            config = configs.get(node_id, {})
            is_new = node_id not in self.active
            enter = description(config.get('enter'), 'enter') if is_new else None
            animate = description(config.get('animate'), 'animate')
            if enter is not None:
                self._start(node, enter)
            if animate is not None and animate[0]['to'] != self.targets.get(node_id):
                spec = dict(animate[0])
                previous = self.runs.get(node_id)
                if node_id not in self.targets and (previous is None or previous['completed']):
                    # Native animate applies its first target immediately.
                    spec.update({'from': dict(spec['to']), 'duration': 0, 'delay': 0})
                elif enter is not None:
                    # Native animate interrupts enter in the same commit.
                    spec['from'] = dict(enter[0]['from'])
                self.targets[node_id] = dict(spec['to'])
                self._start(node, (spec, None))
            elif node_id in self.runs:
                node['animation'] = self.runs[node_id]['animation']
        removed = set(self.active) - set(nodes)
        exiting = {}
        for node_id in removed:
            parsed = description(self.configs.get(node_id, {}).get('exit'), 'exit')
            self.runs.pop(node_id, None)
            self.targets.pop(node_id, None)
            if parsed is not None:
                exiting[node_id] = parsed
        for node_id, parsed in exiting.items():
            node = copy.deepcopy(self.active[node_id])

            def strip(subtree):
                subtree.pop('animation', None)
                subtree['exiting'] = True
                subtree['props'] = {key: value for key, value in subtree['props'].items()
                                    if key not in ('onClick', 'onChange', 'onTouch')}
                subtree['children'] = [child for child in subtree['children'] if child['id'] not in exiting]
                for child in subtree['children']:
                    strip(child)
                for child in subtree.get('states', {}).values():
                    strip(child)

            strip(node)
            self._start(node, parsed)
            self.exits[node_id] = node
        self.active, self.configs = nodes, configs

    def complete(self, node_id, value):
        if not isinstance(value, dict) or not isinstance(value.get('runId'), str):
            raise ValueError('Animation completion requires a runId')
        run = self.runs.get(node_id)
        if run is None or run['completed'] or run['animation']['runId'] != value['runId']:
            return False
        run['completed'] = True
        callback = run['callback']
        if node_id in self.exits:
            self.exits.pop(node_id)
            self.runs.pop(node_id)
        if callable(callback):
            callback()
        return True

    def close(self):
        self.active.clear()
        self.configs.clear()
        self.runs.clear()
        self.exits.clear()
        self.targets.clear()
