"""Deterministic font atlas checks using generated images, not game assets."""

from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from pyreact.browser.bitmap_font import BitmapFont
from pyreact.browser.png_alpha import read_alpha


def chunk(kind, payload):
    return (struct.pack('>I', len(payload)) + kind + payload +
            struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))


def write_png(path, width, height, color, rows, modes=None, transparency=b'', depth=8):
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    previous = bytes(width * channels)
    filtered = bytearray()
    for y, row in enumerate(rows):
        mode = modes[y] if modes else 0
        filtered.append(mode)
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            corner = previous[index - channels] if index >= channels else 0
            predicted = left + up - corner
            distances = (abs(predicted - left), abs(predicted - up), abs(predicted - corner))
            paeth = (left, up, corner)[distances.index(min(distances))]
            predictor = (0, left, up, (left + up) // 2, paeth)[mode]
            filtered.append((value - predictor) & 255)
        previous = row
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack(
        '>IIBBBBB', width, height, depth, color, 0, 0, 0))
    if color == 3:
        data += chunk(b'PLTE', b'\x00\x00\x00\xff\xff\xff')
    if transparency:
        data += chunk(b'tRNS', transparency)
    data += chunk(b'IDAT', zlib.compress(filtered)) + chunk(b'IEND', b'')
    path.write_bytes(data)


def atlas(path, cell, glyphs, indexed=False):
    width = cell * 16
    rows = [bytearray(width * (1 if indexed else 4)) for _ in range(width)]
    for code, left, right in glyphs:
        origin_x, origin_y = code % 16 * cell, (code % 256) // 16 * cell
        for y in range(1, cell - 1):
            for x in range(left, right + 1):
                index = (origin_x + x) * (1 if indexed else 4)
                if indexed:
                    rows[origin_y + y][index] = 1
                else:
                    rows[origin_y + y][index:index + 4] = b'\xff\xff\xff\xff'
    write_png(path, width, width, 3 if indexed else 6, rows,
              transparency=b'\x00\xff' if indexed else b'')


class BitmapFontTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        atlas(self.root / 'default8.png', 8, [(ord('A'), 1, 5), (ord('?'), 0, 3)])
        atlas(self.root / 'glyph_4E.png', 16, [(ord('中'), 1, 14)], indexed=True)
        self.font = BitmapFont(self.root)

    def test_actual_glyph_coverage_and_full_vertical_cell(self):
        result = self.font.layout('A中', {'fontSize': 10})
        latin, chinese = result['lines'][0]['glyphs']
        self.assertEqual((latin['sx'], latin['sy'], latin['sw'], latin['sh']), (9, 32, 5, 8))
        self.assertEqual((chinese['sx'], chinese['sy'], chinese['sw'], chinese['sh']), (209, 32, 14, 16))
        self.assertEqual(latin['height'], 14)
        self.assertEqual(chinese['height'], 14)
        self.assertEqual(chinese['x'], 10.5)
        self.assertEqual(result['width'], 24.5)
        self.assertEqual(result['height'], 17.5)

    def test_wrapping_newlines_and_shared_measurement(self):
        result = self.font.layout('AAA\n中', {'linePadding': 2}, max_width=21)
        self.assertEqual([line['width'] for line in result['lines']], [21, 10.5, 14])
        self.assertEqual(result['lines'][2]['glyphs'][0]['y'], 39)
        self.assertEqual(self.font.measure_text('AAA\n中', {'linePadding': 2}, 21),
                         {'width': result['width'], 'height': result['height']})
        self.assertEqual(len(self.font.layout('AA', {}, 1)['lines']), 2)

    def test_empty_none_spaces_and_line_endings(self):
        self.assertEqual(self.font.layout(None, {}), self.font.layout('', {}))
        self.assertEqual(self.font.layout(' \t', {})['width'], 35)
        self.assertEqual(len(self.font.layout('A\r\nA\r', {})['lines']), 3)
        self.assertEqual(len(self.font.layout('\n', {})['lines']), 2)

    def test_missing_glyph_uses_bitmap_question_mark(self):
        expected = self.font.layout('?', {})['lines'][0]['glyphs'][0]
        for content in ('乙', '\U0001f600'):
            self.assertEqual(self.font.layout(content, {})['lines'][0]['glyphs'][0], expected)

    def test_missing_ascii_atlas_uses_unicode_page(self):
        (self.root / 'default8.png').unlink()
        atlas(self.root / 'glyph_00.png', 16, [(ord('A'), 2, 11), (ord('?'), 0, 7)])
        self.assertEqual(self.font.layout('A', {})['lines'][0]['glyphs'][0]['page'], 'glyph_00.png')

    def test_missing_fallback_is_explicit(self):
        (self.root / 'default8.png').unlink()
        with self.assertRaisesRegex(ValueError, 'fallback'):
            self.font.layout('unknown', {})

    def test_pages_are_lazy_and_cached(self):
        with patch('pyreact.browser.bitmap_font.read_alpha', wraps=read_alpha) as reader:
            self.font.layout('AAA', {})
            self.font.layout('AAA', {})
            self.assertEqual(reader.call_count, 1)
            self.font.layout('中', {})
            self.assertEqual(reader.call_count, 2)

    def test_asset_whitelist_and_symlink_boundary(self):
        self.assertEqual(self.font.asset('default8.png'), self.root / 'default8.png')
        for name in ('../default8.png', 'glyph_000.png', 'glyph_ZZ.png', '/default8.png',
                     'glyph_4E.png/../default8.png', 'secret.txt', None):
            self.assertIsNone(self.font.asset(name))
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'font.png'
            target.write_bytes(b'x')
            with patch('pyreact.browser.bitmap_font.Path.resolve', return_value=target):
                self.assertIsNone(self.font.asset('glyph_01.png'))


class PngAlphaTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'atlas.png'

    def test_all_filters_preserve_rgba_alpha(self):
        rows = [bytes((20 + y, 30, 40, 0, 70, 80, 90, 127, 110, 120, 130, 255))
                for y in range(5)]
        write_png(self.path, 3, 5, 6, rows, modes=list(range(5)))
        self.assertEqual(read_alpha(self.path), (3, 5, bytes((0, 127, 255)) * 5))

    def test_supported_colors_and_transparency(self):
        cases = [(0, b'\x03\x07', struct.pack('>H', 3), b'\x00\xff'),
                 (2, b'\x01\x02\x03\x04\x05\x06', struct.pack('>HHH', 1, 2, 3), b'\x00\xff'),
                 (3, b'\x00\x01', b'\x00\x7f', b'\x00\x7f'),
                 (4, b'\xff\x7f\xff\xff', b'', b'\x7f\xff')]
        for color, row, transparency, expected in cases:
            with self.subTest(color=color):
                write_png(self.path, 2, 1, color, [row], transparency=transparency)
                self.assertEqual(read_alpha(self.path)[2], expected)

    def test_bad_checksums_truncated_files_and_unsupported_depth(self):
        write_png(self.path, 1, 1, 6, [b'\xff' * 4])
        original = self.path.read_bytes()
        for invalid in (b'bad', original[:-5], original[:30] + b'\xff' + original[31:]):
            self.path.write_bytes(invalid)
            with self.assertRaisesRegex(ValueError, 'Invalid font PNG'):
                read_alpha(self.path)
        write_png(self.path, 1, 1, 6, [b'\xff' * 4], depth=4)
        with self.assertRaisesRegex(ValueError, '8-bit'):
            read_alpha(self.path)


if __name__ == '__main__':
    unittest.main()
