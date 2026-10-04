"""Run existing Pyreact components locally without the NetEase client."""

import math
import threading

from ..core.component import ComponentInstance
from ..core.hooks import cleanup_effects, run_effects, with_current_fiber
from ..core.reconciler import Reconciler
from ..core.tree_builder import TreeBuilder
from ..layout.layout_engine import LayoutEngine
from ..renderer.text_measurer import TextMeasurer
from .serialization import TreeSerializer, measure_text
from .identity import NodeIdentities
from .controls import ControlRegistry
from .touch import TouchStreams
from .animation_protocol import AnimationRegistry


class BrowserRuntime:
    """A synchronous component session backed by the existing core and layout."""

    def __init__(self, root, width=960, height=640):
        if not callable(root) or not getattr(root, '__pyreact_component__', False):
            raise TypeError('Browser root must be a callable decorated with @Component')
        self.width, self.height = self._size(width, height)
        self._lock = threading.RLock()
        self._dirty = True
        self._closed = False
        self._revision = 0
        self._tree = None
        self._snapshot = None
        self._handlers = {}
        self._identities = NodeIdentities()
        self._controls = ControlRegistry(self._control_changed)
        self._touch = TouchStreams()
        self._animations = AnimationRegistry()
        self._builder = TreeBuilder()
        self._reconciler = Reconciler()
        self._layout = LayoutEngine(TextMeasurer(native_measure=measure_text))
        self._component = ComponentInstance(root, rerender_callback=self._invalidate)

    @staticmethod
    def _size(width, height):
        sizes = []
        for value in (width, height):
            if isinstance(value, bool):
                raise ValueError('Viewport dimensions must be numbers between 1 and 4096')
            number = float(value)
            if not math.isfinite(number) or not 1 <= number <= 4096:
                raise ValueError('Viewport dimensions must be between 1 and 4096')
            sizes.append(number)
        return tuple(sizes)

    def _invalidate(self):
        self._dirty = True

    def _control_changed(self):
        self._revision += 1
        if self._snapshot is not None:
            self._snapshot['revision'] = self._revision

    def _render(self):
        # Commit refs before effects, without changing the shared game renderer.
        component = self._component
        fiber = component.fiber
        fiber.begin_render()
        with with_current_fiber(fiber):
            output = component.component_fn(component.props)
        fiber.finish_render()
        fiber.pending_state_update = False
        component.latest_output = output
        return output

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError('Browser runtime is closed')

    def snapshot(self):
        with self._lock:
            self._ensure_open()
            for _ in range(25):
                if not self._dirty:
                    return self._snapshot
                self._dirty = False
                try:
                    output = self._render()
                    tree = self._builder.build_tree(output)
                    mutations = self._reconciler.reconcile(self._tree, tree)
                    self._identities.begin()
                    self._identities.assign(tree)
                    handlers = {}
                    warnings = [
                        '文字尺寸采用估算；游戏字体、纹理和原生渲染效果仍需在游戏中确认。',
                    ]
                    serialized = None
                    serializer = TreeSerializer(self._builder, self._layout, handlers, warnings,
                                                self._identities)
                    if tree is not None:
                        shadow = self._layout.calculate(tree, self.width, self.height)
                        serialized = serializer.serialize(shadow)
                    self._animations.update(serialized, serializer.animations)
                    self._controls.update(serialized, serializer.refs)
                    self._identities.finish()
                except Exception:
                    self._dirty = True
                    raise
                self._tree = tree
                self._handlers = handlers
                self._touch.retain(handlers)
                self._revision += 1
                self._snapshot = {
                    'tree': serialized, 'width': self.width, 'height': self.height,
                    'revision': self._revision, 'warnings': warnings,
                    'mutationCount': len(mutations),
                    'exits': list(self._animations.exits.values()),
                }
                run_effects(self._component.fiber)
            raise RuntimeError('Component did not settle after 25 renders; check effect state updates')

    def dispatch(self, node_id, event, value=None):
        with self._lock:
            self._ensure_open()
            self.snapshot()
            if event == 'animation_complete':
                if self._animations.complete(node_id, value):
                    self._snapshot['exits'] = list(self._animations.exits.values())
                    self._control_changed()
                return self.snapshot()
            event_key = {'click': 'onClick', 'input': 'onChange', 'touch': 'onTouch'}.get(event)
            if event_key is None:
                raise ValueError('Unsupported browser event: %s' % event)
            handler = self._handlers.get(node_id, {}).get(event_key)
            if handler is None:
                raise ValueError('Node %s has no %s handler' % (node_id, event))
            if event == 'touch':
                args = self._touch.validate(node_id, value)
                if args is not None:
                    handler(args)
            elif event == 'input':
                if not isinstance(value, str):
                    raise ValueError('Input value must be a string')
                handler(value)
            else:
                handler()
            return self.snapshot()

    def resize(self, width, height):
        dimensions = self._size(width, height)
        with self._lock:
            self._ensure_open()
            self.width, self.height = dimensions
            self._dirty = True
            return self.snapshot()

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                cleanup_effects(self._component.fiber)
                self._controls.close()
                self._animations.close()
                self._touch.streams.clear()
                self._handlers.clear()
