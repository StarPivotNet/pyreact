"""Run existing Pyreact components locally without the NetEase client."""

import math
import threading

from ..core.component import ComponentInstance
from ..core.hooks import cleanup_effects
from ..core.reconciler import Reconciler
from ..core.tree_builder import TreeBuilder
from ..layout.layout_engine import LayoutEngine
from ..renderer.text_measurer import TextMeasurer
from .serialization import TreeSerializer, measure_text


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
                    output = self._component.render()
                    tree = self._builder.build_tree(output)
                    mutations = self._reconciler.reconcile(self._tree, tree)
                    handlers = {}
                    warnings = [
                        '文字尺寸采用估算；游戏字体、纹理和原生渲染效果仍需在游戏中确认。',
                    ]
                    serialized = None
                    if tree is not None:
                        shadow = self._layout.calculate(tree, self.width, self.height)
                        serializer = TreeSerializer(self._builder, self._layout, handlers, warnings)
                        serialized = serializer.serialize(shadow)
                except Exception:
                    self._dirty = True
                    raise
                self._tree = tree
                self._handlers = handlers
                self._revision += 1
                self._snapshot = {
                    'tree': serialized, 'width': self.width, 'height': self.height,
                    'revision': self._revision, 'warnings': warnings,
                    'mutationCount': len(mutations),
                }
            raise RuntimeError('Component did not settle after 25 renders; check effect state updates')

    def dispatch(self, node_id, event, value=None):
        with self._lock:
            self._ensure_open()
            self.snapshot()
            event_key = {'click': 'onClick', 'input': 'onChange'}.get(event)
            if event_key is None:
                raise ValueError('Unsupported browser event: %s' % event)
            handler = self._handlers.get(node_id, {}).get(event_key)
            if handler is None:
                raise ValueError('Node %s has no %s handler' % (node_id, event))
            if event == 'input':
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
                self._handlers.clear()
