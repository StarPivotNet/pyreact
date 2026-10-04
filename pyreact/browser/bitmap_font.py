"""Game bitmap glyph metrics shared by browser drawing and layout."""

from pathlib import Path
import re

from .png_alpha import read_alpha


class BitmapFont:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._pages = {}
        self._glyphs = {}

    def asset(self, name):
        """Resolve only supported font page names, including symlink containment."""
        if not isinstance(name, str) or not re.fullmatch(
                r'(?:default8|glyph_[0-9A-Fa-f]{2})\.png', name):
            return None
        path = (self.root / name).resolve()
        if path.parent != self.root or not path.is_file():
            return None
        return path

    def _page(self, name):
        if name not in self._pages:
            path = self.asset(name)
            page = read_alpha(path) if path is not None else None
            if page is not None and (page[0] != page[1] or page[0] % 16):
                raise ValueError('Font atlas must contain a square 16 x 16 glyph grid: %s' % path)
            self._pages[name] = page
        return self._pages[name]

    def _glyph(self, char):
        if char in self._glyphs:
            return self._glyphs[char]
        code = ord(char)
        names = ['glyph_%02X.png' % (code >> 8)] if code <= 65535 else []
        if 32 <= code <= 126:
            names.insert(0, 'default8.png')
        glyph = None
        for name in names:
            page = self._page(name)
            if page is None:
                continue
            width, height, alpha = page
            cell = width // 16
            origin_x, origin_y = code % 16 * cell, (code % 256) // 16 * cell
            columns = [x for x in range(cell) if any(
                alpha[(origin_y + y) * width + origin_x + x] for y in range(cell))]
            if columns:
                left, right = columns[0], columns[-1]
                glyph = {'page': name, 'sx': origin_x + left, 'sy': origin_y,
                         'sw': right - left + 1, 'sh': cell}
                break
        if glyph is None and char != '?':
            glyph = self._glyph('?')
        if glyph is None:
            raise ValueError('Font atlas does not contain the fallback ? glyph: %s' % self.root)
        self._glyphs[char] = glyph
        return glyph

    def layout(self, content, style, max_width=None):
        """Return source rectangles and positions in a left-aligned text block."""
        from .serialization import font_pixels

        size = font_pixels(style.get('fontSize'))
        line_height = size * 1.25 + float(style.get('linePadding') or 0)
        limit = float(max_width) if max_width is not None else 0.0
        lines = []
        line = {'width': 0.0, 'glyphs': []}
        text = '' if content is None else str(content)
        for char in text.replace('\r\n', '\n').replace('\r', '\n'):
            if char == '\n':
                lines.append(line)
                line = {'width': 0.0, 'glyphs': []}
                continue
            glyph = None if char in (' ', '\t') else self._glyph(char)
            if glyph:
                draw_width = glyph['sw'] / float(glyph['sh']) * size
                advance = draw_width + size / 8.0
            else:
                advance = size * (2 if char == '\t' else 0.5)
            if limit > 0 and line['width'] > 0 and line['width'] + advance > limit:
                lines.append(line)
                line = {'width': 0.0, 'glyphs': []}
            if glyph:
                line['glyphs'].append(dict(glyph, x=line['width'], y=len(lines) * line_height,
                                           width=draw_width, height=size))
            line['width'] += advance
        lines.append(line)
        return {'width': max(1.0, max(line['width'] for line in lines)),
                'height': max(1.0, len(lines) * line_height),
                'lineHeight': line_height, 'lines': lines}

    def measure_text(self, content, style, max_width=None):
        layout = self.layout(content, style, max_width)
        return {'width': layout['width'], 'height': layout['height']}
