"""Small browser control adapters; deliberately not a game SDK emulator."""

import math


def pair(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError('Control coordinates require a pair of finite numbers')
    if any(isinstance(item, bool) or not isinstance(item, (int, float))
           or not math.isfinite(item) for item in value):
        raise ValueError('Control coordinates require a pair of finite numbers')
    return tuple(float(item) for item in value)


class BrowserControl:
    def __init__(self, registry, node_id):
        self.registry, self.node_id = registry, node_id

    def _node(self):
        node = self.registry.nodes.get(self.node_id)
        if node is None:
            raise RuntimeError('Browser control has been unmounted')
        return node

    def GetGlobalPosition(self):
        layout = self._node()['layout']
        return layout['x'], layout['y']

    def GetPosition(self):
        x, y = self.GetGlobalPosition()
        parent = self.registry.parents.get(self.node_id)
        if parent is not None:
            layout = self.registry.nodes[parent]['layout']
            x, y = x - layout['x'], y - layout['y']
        return x, y

    def GetSize(self):
        layout = self._node()['layout']
        return layout['width'], layout['height']

    def SetPosition(self, value):
        x, y = pair(value)
        parent = self.registry.parents.get(self.node_id)
        if parent is not None:
            layout = self.registry.nodes[parent]['layout']
            x, y = x + layout['x'], y + layout['y']
        old_x, old_y = self.GetGlobalPosition()
        self.registry.translate(self.node_id, x - old_x, y - old_y)
        self.registry.changed()

    def SetSize(self, value, *args):
        width, height = pair(value)
        if width < 0 or height < 0:
            raise ValueError('Control dimensions cannot be negative')
        self._node()['layout'].update(width=width, height=height)
        self.registry.changed()

    def SetVisible(self, value):
        self._node()['props']['visible'] = bool(value)
        self.registry.changed()

    def SetAlpha(self, value):
        alpha, _ = pair((value, 0))
        self._node()['style']['opacity'] = max(0, min(1, alpha))
        self.registry.changed()


class ControlRegistry:
    def __init__(self, changed):
        self.changed = changed
        self.nodes, self.parents, self.controls, self.refs = {}, {}, {}, {}

    @staticmethod
    def _bind(ref, value):
        if callable(ref):
            ref(value)
        elif hasattr(ref, 'current'):
            ref.current = value
        else:
            raise TypeError('Control ref must be callable or have a current attribute')

    def update(self, tree, refs):
        nodes, parents = {}, {}

        def visit(node, parent=None):
            if node is None:
                return
            nodes[node['id']], parents[node['id']] = node, parent
            for child in node['children']:
                visit(child, node['id'])
            for child in node.get('states', {}).values():
                visit(child, node['id'])

        visit(tree)
        for node_id, ref in self.refs.items():
            if refs.get(node_id) is not ref:
                self._bind(ref, None)
        self.nodes, self.parents = nodes, parents
        self.controls = {node_id: self.controls.get(node_id) or BrowserControl(self, node_id)
                         for node_id in nodes}
        previous, self.refs = self.refs, refs
        for node_id, ref in refs.items():
            if previous.get(node_id) is not ref:
                self._bind(ref, self.controls[node_id])

    def translate(self, node_id, dx, dy):
        node = self.nodes[node_id]
        node['layout']['x'] += dx
        node['layout']['y'] += dy
        for child_id, parent in self.parents.items():
            if parent == node_id:
                self.translate(child_id, dx, dy)

    def close(self):
        self.update(None, {})
