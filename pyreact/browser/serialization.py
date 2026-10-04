"""JSON snapshots of Pyreact shadow trees for the browser renderer."""

import math
import unicodedata

from ..components.color import Color


def font_pixels(value=None):
    """Mirror native fontSize / 10 scaling against its approximate 14px base."""
    if value is None:
        return 14.0
    size = float(value)
    return size * 1.4 if math.isfinite(size) and size > 0 else 14.0


def measure_text(content, style, max_width=None):
    """Approximate browser text metrics without importing the game SDK."""
    size = font_pixels(style.get('fontSize'))
    limit = float(max_width) if max_width is not None else 0.0
    widths = []
    for line in str(content).split('\n'):
        width = 0.0
        for char in line:
            advance = size if unicodedata.east_asian_width(char) in ('W', 'F') else size * 0.58
            if limit > 0 and width > 0 and width + advance > limit:
                widths.append(width)
                width = 0.0
            width += advance
        widths.append(width)
    line_height = size * 1.25 + float(style.get('linePadding') or 0)
    return {'width': max(1.0, max(widths)), 'height': max(1.0, len(widths) * line_height)}


def json_value(value):
    if isinstance(value, Color):
        return 'rgba(%s,%s,%s,%.4f)' % (value.red, value.green, value.blue, value.alpha)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items() if not callable(item)}
    if hasattr(value, 'to_dict'):
        return json_value(value.to_dict())
    return str(value)


class TreeSerializer:
    def __init__(self, builder, layout_engine, handlers, warnings, identities=None, font=None):
        self.builder = builder
        self.layout_engine = layout_engine
        self.handlers = handlers
        self.warnings = warnings
        self.identities = identities
        self.font = font
        self.refs = {}
        self.animations = {}

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def serialize(self, node, node_id='root', offset=(0.0, 0.0), state_depth=0):
        node_id = node.props.get('__browser_id__', node_id)
        props = {}
        for key, value in node.props.items():
            if key == '__browser_id__':
                continue
            if key in ('onClick', 'onChange', 'onTouch') and callable(value):
                props[key] = True
                self.handlers.setdefault(node_id, {})[key] = value
            elif key == 'ref':
                if value is not None:
                    self.refs[node_id] = value
            elif key == '__animation__':
                if isinstance(value, dict):
                    self.animations[node_id] = value
            elif not callable(value):
                props[key] = json_value(value)
        if node.node_type == 'Label':
            props['fontSizePixels'] = font_pixels(node.props.get('fontSize'))
        if node.node_type in ('Item', 'PaperDoll'):
            self.warn('%s 显示为占位；原生渲染需要在游戏中验收。' % node.node_type)
        layout = json_value(vars(node.layout)) if node.layout is not None else {}
        layout['x'] = layout.get('x', 0.0) + offset[0]
        layout['y'] = layout.get('y', 0.0) + offset[1]
        if node.node_type == 'Label' and self.font is not None:
            props['fontBitmap'] = self.font.layout(
                node.props.get('content'), node.props, max_width=layout.get('width'))
        result = {
            'id': node_id, 'type': node.node_type, 'props': props,
            'style': json_value(node.style), 'layout': layout,
            'children': [self.serialize(child, '%s/%s' % (node_id, index), offset, state_depth)
                         for index, child in enumerate(node.children)],
        }
        button_builder = node.props.get('buttonBuilder')
        if callable(button_builder) and state_depth < 4:
            result['states'] = {}
            for state in ('default', 'hover', 'pressed'):
                element = button_builder(state)
                if element is None:
                    continue
                tree = self.builder.build_tree(element)
                if self.identities is not None:
                    self.identities.assign(tree, node_id + '/states/' + state)
                shadow = self.layout_engine.calculate(tree, layout.get('width', 0), layout.get('height', 0))
                result['states'][state] = self.serialize(
                    shadow, node_id + '/states/' + state,
                    (layout['x'], layout['y']), state_depth + 1)
        elif callable(button_builder):
            self.warn('Nested buttonBuilder depth exceeds the browser preview limit of 4.')
        return result
