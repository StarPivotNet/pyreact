"""Font HTTP integration using generated atlases, never installed game assets."""

import http.client
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from pyreact import Component, Label, Panel, Style
from pyreact.browser.server import create_server


def write_atlas(path, cell, glyphs):
    """Write transparent RGBA cells containing simple opaque rectangles."""
    size = cell * 16
    pixels = bytearray(size * size * 4)
    for code, left, ink_width in glyphs:
        x0 = (code % 16) * cell + left
        y0 = ((code & 255) // 16) * cell
        for y in range(y0, y0 + cell):
            for x in range(x0, x0 + ink_width):
                offset = (y * size + x) * 4
                pixels[offset:offset + 4] = b'\xff\xff\xff\xff'

    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))

    rows = b''.join(b'\0' + pixels[y * size * 4:(y + 1) * size * 4]
                    for y in range(size))
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    path.write_bytes(png)
    return png


@Component
def FontSample():
    return Panel(style=Style(alignItems='flex-start'), children=[
        Label(content='A中', fontSize=10),
    ])


class BrowserFontServerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.font_root = self.root / 'font'
        self.font_root.mkdir()
        self.ascii_png = write_atlas(self.font_root / 'default8.png', 8,
                                    [(ord('A'), 1, 5), (ord('?'), 0, 5)])
        self.unicode_png = write_atlas(self.font_root / 'glyph_4E.png', 16,
                                      [(ord('中'), 2, 12)])
        (self.font_root / 'private.txt').write_text('private-font-data')
        (self.font_root / 'other.png').write_bytes(b'private-font-data')
        (self.root / 'default8.png').write_bytes(b'outside-font-data')
        self.server = self.start_server(font_root=self.font_root)

    def start_server(self, **kwargs):
        server = create_server(FontSample, port=0, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.addCleanup(stop)
        return server

    def request(self, path, payload=None, server=None):
        server = server or self.server
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port,
                                                timeout=5)
        try:
            headers = {'Content-Type': 'application/json'} if payload is not None else {}
            body = json.dumps(payload) if payload is not None else None
            connection.request('POST' if payload is not None else 'GET', path,
                               body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def snapshot(self, server=None):
        status, body, _ = self.request('/api/tree', server=server)
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_local_font_sheets_have_png_mime_and_exact_content(self):
        for name, expected in [('default8.png', self.ascii_png),
                               ('glyph_4E.png', self.unicode_png)]:
            with self.subTest(name=name):
                status, body, headers = self.request('/fonts/' + name)
                self.assertEqual(status, 200)
                self.assertEqual(headers['Content-Type'], 'image/png')
                self.assertEqual(body, expected)
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')

    def test_font_endpoint_rejects_traversal_and_non_atlas_files(self):
        for name in ('../default8.png', '%2e%2e/default8.png',
                     '%2e%2e%5cdefault8.png', '%252e%252e/default8.png',
                     '/default8.png', 'C:/Windows/default8.png',
                     'private.txt', 'other.png', 'default8.png/private.txt',
                     'default8.png%00', 'glyph_ZZ.png', 'glyph_000.png'):
            with self.subTest(name=name):
                status, body, _ = self.request('/fonts/' + name)
                self.assertEqual(status, 404)
                self.assertNotIn(b'private-font-data', body)
                self.assertNotIn(b'outside-font-data', body)

    def test_label_layout_and_snapshot_use_atlas_metrics(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot['font']['mode'], 'game-bitmap')
        self.assertEqual(Path(snapshot['font']['root']), self.font_root.resolve())
        label = snapshot['tree']['children'][0]
        bitmap = label['props']['fontBitmap']
        self.assertEqual(label['props']['content'], 'A中')
        self.assertEqual(label['props']['fontSizePixels'], 14)
        # A: 5/8 * 14 + 14/8, 中: 12/16 * 14 + 14/8.
        self.assertAlmostEqual(bitmap['width'], 22.75)
        self.assertAlmostEqual(bitmap['height'], 17.5)
        self.assertAlmostEqual(label['layout']['width'], bitmap['width'])
        self.assertAlmostEqual(label['layout']['height'], bitmap['height'])
        glyphs = bitmap['lines'][0]['glyphs']
        self.assertEqual([glyph['page'] for glyph in glyphs],
                         ['default8.png', 'glyph_4E.png'])
        self.assertEqual([glyph['sw'] for glyph in glyphs], [5, 12])
        self.assertAlmostEqual(glyphs[1]['x'], 10.5)

    def test_reset_preserves_font_selection_and_glyph_geometry(self):
        before = self.snapshot()
        selected_font = self.server.font
        status, body, _ = self.request('/api/reset', {})
        self.assertEqual(status, 200)
        after = json.loads(body)
        self.assertIs(self.server.font, selected_font)
        self.assertIs(self.server.runtime.font, selected_font)
        self.assertEqual(after['font'], before['font'])
        self.assertEqual(after['tree']['children'][0]['props']['fontBitmap'],
                         before['tree']['children'][0]['props']['fontBitmap'])

    def test_missing_local_fonts_reports_system_fallback(self):
        with patch('pyreact.browser.server.discover_font_root', return_value=None):
            server = self.start_server()
        snapshot = self.snapshot(server)
        self.assertEqual(snapshot['font'], {'mode': 'system-fallback', 'root': None})
        self.assertNotIn('fontBitmap', snapshot['tree']['children'][0]['props'])
        self.assertTrue(any('--font-root' in warning and '系统字体' in warning
                            for warning in snapshot['warnings']))
        self.assertEqual(self.request('/fonts/default8.png', server=server)[0], 404)

    def test_explicit_invalid_font_root_fails_instead_of_auto_discovering(self):
        empty_root = self.root / 'empty'
        empty_root.mkdir()
        for root in (empty_root, self.root / 'missing', self.font_root / 'private.txt'):
            with self.subTest(root=root):
                with self.assertRaisesRegex(ValueError, '--font-root'):
                    create_server(FontSample, port=0, font_root=root)


if __name__ == '__main__':
    unittest.main()
