"""Item previews use synthetic packs and real HTTP, never installed assets."""

import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from pyreact import Component, Item, Panel, Style
from pyreact.browser.item_assets import ItemAssets
from pyreact.browser.server import create_server


PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8A'
    'AwMCAO+jRZkAAAAASUVORK5CYII=')


class ItemPackFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.pack, self.vanilla = self.root / 'custom', self.root / 'vanilla'
        self.pack.mkdir()
        self.vanilla.mkdir()
        self.write_json(self.vanilla, 'textures/item_texture.json', {'texture_data': {
            'apple': {'textures': 'textures/items/apple'},
            'palette': {'textures': ['textures/items/red', 'textures/items/blue']},
        }})
        self.write_json(self.vanilla, 'items/apple.json', {'minecraft:item': {
            'description': {'identifier': 'minecraft:apple'},
            'components': {'minecraft:icon': 'apple'},
        }})
        self.write_json(self.pack, 'textures/item_texture.json', {'texture_data': {
            'custom_icon': {'textures': 'textures/items/custom'},
            'bad_icon': {'textures': '../../private'},
        }})
        for name, icon in [('gem', {'texture': 'custom_icon'}),
                           ('variant', 'palette'), ('bad', 'bad_icon')]:
            self.write_json(self.pack, 'items/' + name + '.json', {'minecraft:item': {
                'description': {'identifier': 'example:' + name},
                'components': {'minecraft:icon': icon},
            }})
        self.write_json(self.vanilla, 'textures/terrain_texture.json', {'texture_data': {
            name: {'textures': 'textures/blocks/' + name}
            for name in ('rock', 'grass_top', 'grass_side', 'grass_carried')
        }})
        self.write_json(self.vanilla, 'blocks.json', {
            'stone': {'textures': 'rock'},
            'grass': {'textures': {'up': 'grass_top', 'side': 'grass_side'},
                      'carried_textures': {'up': 'grass_top', 'side': 'grass_carried'}},
        })
        for name in ('apple', 'red', 'blue'):
            self.write(self.vanilla, 'textures/items/' + name + '.png', PNG)
        self.write(self.pack, 'textures/items/custom.png', PNG)
        for name in ('rock', 'grass_top', 'grass_side', 'grass_carried'):
            self.write(self.vanilla, 'textures/blocks/' + name + '.png', PNG)
        self.write(self.root, 'private.png', b'private-image')
        self.assets = ItemAssets(resource_root=self.pack, vanilla_root=self.vanilla)

    @staticmethod
    def write(root, name, data):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def write_json(self, root, name, value):
        self.write(root, name, json.dumps(value).encode('utf-8'))


class ItemAssetsTests(ItemPackFixture):
    def test_vanilla_and_custom_icons_resolve_to_local_assets(self):
        for identifier, filename in [('minecraft:apple', 'apple.png'),
                                     ('example:gem', 'custom.png')]:
            with self.subTest(identifier=identifier):
                result = self.assets.resolve({'identifier': identifier})
                self.assertEqual(result['mode'], 'sprite')
                self.assertEqual(result['identifier'], identifier)
                self.assertTrue(result['src'].startswith('/items/'))
                asset = self.assets.asset(result['src'][len('/items/'):])
                self.assertEqual(asset.name, filename)
                self.assertEqual(asset.read_bytes(), PNG)

    def test_texture_array_uses_aux_from_modsdk_item_dict(self):
        result = self.assets.resolve({'itemDict': {
            'newItemName': 'example:variant', 'newAuxValue': 1,
            'enchantData': [(1, 1)],
        }})
        self.assertEqual(result['mode'], 'sprite')
        self.assertTrue(result['src'].endswith('/blue.png'))
        self.assertTrue(result['enchant'])

    def test_explicit_props_override_item_dict_including_false_and_zero(self):
        result = self.assets.resolve({
            'identifier': 'example:variant', 'aux': 0, 'enchant': False,
            'itemDict': {'newItemName': 'minecraft:apple', 'newAuxValue': 1,
                         'modEnchantData': [(1, 1)]},
        })
        self.assertEqual(result['identifier'], 'example:variant')
        self.assertTrue(result['src'].endswith('/red.png'))
        self.assertFalse(result['enchant'])

    def test_legacy_item_dict_names_remain_supported(self):
        result = self.assets.resolve({'itemDict': {
            'itemName': 'example:variant', 'auxValue': 1,
        }})
        self.assertTrue(result['src'].endswith('/blue.png'))

    def test_regular_blocks_have_three_faces_and_carried_textures_win(self):
        stone = self.assets.resolve({'identifier': 'minecraft:stone'})
        self.assertEqual(stone['mode'], 'cube')
        self.assertEqual(set(stone['faces']), {'top', 'left', 'right'})
        self.assertTrue(all(src.endswith('/rock.png') for src in stone['faces'].values()))
        grass = self.assets.resolve({'identifier': 'minecraft:grass'})
        self.assertTrue(grass['faces']['top'].endswith('/grass_top.png'))
        self.assertTrue(grass['faces']['left'].endswith('/grass_carried.png'))
        self.assertTrue(grass['faces']['right'].endswith('/grass_carried.png'))

    def test_missing_items_and_air_have_distinct_states(self):
        for props in ({}, {'identifier': 'minecraft:air'}):
            self.assertEqual(self.assets.resolve(props)['mode'], 'empty')
        missing = self.assets.resolve({'identifier': 'example:missing'})
        self.assertEqual(missing['mode'], 'missing')
        self.assertTrue(missing['reason'])
        self.assertNotIn('src', missing)

    def test_unknown_custom_namespace_does_not_borrow_vanilla_icon(self):
        result = self.assets.resolve({'identifier': 'example:apple'})
        self.assertEqual(result['mode'], 'missing')

    def test_json_comments_and_modern_default_icon_are_supported(self):
        self.write(self.pack, 'items/modern.json', b'''{
            // A pack may contain comments and trailing commas.
            "minecraft:item": {
                "description": {"identifier": "example:modern"},
                "components": {"minecraft:icon": {
                    "textures": {"default": "custom_icon"},
                }},
            },
        }''')
        assets = ItemAssets(resource_root=self.pack, vanilla_root=self.vanilla)
        result = assets.resolve({'identifier': 'example:modern'})
        self.assertEqual(result['mode'], 'sprite')
        self.assertTrue(result['src'].endswith('/custom.png'))

    def test_custom_geometry_does_not_render_as_an_incorrect_cube(self):
        self.write_json(self.pack, 'blocks.json', {
            'example:shape': {'textures': 'rock', 'geometry': 'geometry.custom_shape'},
            'example:cube': {'textures': 'rock', 'geometry': 'minecraft:geometry.full_block'},
        })
        assets = ItemAssets(resource_root=self.pack, vanilla_root=self.vanilla)
        self.assertEqual(assets.resolve({'identifier': 'example:shape'})['mode'], 'missing')
        self.assertEqual(assets.resolve({'identifier': 'example:cube'})['mode'], 'cube')

    def test_pack_texture_paths_cannot_read_outside_pack(self):
        self.assertEqual(self.assets.resolve({'identifier': 'example:bad'})['mode'], 'missing')
        for name in ('0/../../private.png', '0/../private.png',
                     '0/..\\..\\private.png', '0/C:/Windows/win.ini',
                     '0/textures/item_texture.json', '999/textures/items/apple.png',
                     '-1/textures/items/apple.png', '0/textures/items/apple.png\x00'):
            with self.subTest(name=name):
                self.assertIsNone(self.assets.asset(name))

    def test_extremely_long_package_index_is_rejected_without_conversion_error(self):
        self.assertIsNone(self.assets.asset('9' * 5000 + '/textures/items/apple.png'))

    def test_malformed_pack_metadata_does_not_break_unrelated_valid_assets(self):
        self.write_json(self.pack, 'textures/item_texture.json', {'texture_data': None})
        self.write_json(self.pack, 'textures/terrain_texture.json', {'texture_data': []})
        self.write_json(self.pack, 'items/malformed.json', {'minecraft:item': []})
        self.write_json(self.pack, 'items/no_description.json', {'minecraft:item': {
            'description': None, 'components': None,
        }})
        assets = ItemAssets(resource_root=self.pack, vanilla_root=self.vanilla)
        self.assertEqual(assets.resolve({'identifier': 'minecraft:apple'})['mode'], 'sprite')

    def test_custom_texture_override_takes_priority_over_vanilla(self):
        override = b'custom-pack-override'
        self.write(self.pack, 'textures/items/apple.png', override)
        assets = ItemAssets(resource_root=self.pack, vanilla_root=self.vanilla)
        result = assets.resolve({'identifier': 'minecraft:apple'})
        self.assertEqual(assets.asset(result['src'][len('/items/'):]).read_bytes(), override)


class BrowserItemServerTests(ItemPackFixture):
    def setUp(self):
        super().setUp()

        @Component
        def Sample():
            return Panel(children=[
                Item(identifier='minecraft:apple', style=Style(width=32, height=32)),
                Item(identifier='minecraft:stone', style=Style(width=32, height=32)),
                Item(identifier='example:missing', style=Style(width=32, height=32)),
            ])

        self.server = create_server(Sample, resource_root=self.pack, vanilla_root=self.vanilla)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()

        def close():
            self.server.shutdown()
            self.server.server_close()
            thread.join(timeout=3)

        self.addCleanup(close)

    def request(self, path, payload=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET' if payload is None else 'POST', path,
                               body=None if payload is None else json.dumps(payload),
                               headers={} if payload is None else {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def snapshot(self):
        status, body, _ = self.request('/api/tree')
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_snapshot_contains_renderable_items_and_serves_exact_textures(self):
        snapshot = self.snapshot()
        previews = [node['props']['itemPreview'] for node in snapshot['tree']['children']]
        self.assertEqual([preview['mode'] for preview in previews], ['sprite', 'cube', 'missing'])
        for path in [previews[0]['src'], *previews[1]['faces'].values()]:
            status, body, headers = self.request(path)
            self.assertEqual(status, 200)
            self.assertEqual(body, PNG)
            self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertFalse(any('Item 显示为占位' in warning for warning in snapshot['warnings']))

    def test_reset_preserves_item_resolver(self):
        before = self.snapshot()
        status, body, _ = self.request('/api/reset', {})
        self.assertEqual(status, 200)
        after = json.loads(body)
        self.assertEqual([node['props']['itemPreview'] for node in before['tree']['children']],
                         [node['props']['itemPreview'] for node in after['tree']['children']])

    def test_http_item_endpoint_rejects_traversal_and_non_image_files(self):
        for path in ('/items/0/../../private.png', '/items/0/%2e%2e/private.png',
                     '/items/0/%2e%2e%5cprivate.png', '/items/0/textures/item_texture.json',
                     '/items/-1/textures/items/apple.png', '/items/0/C:/Windows/win.ini',
                     '/items/0/textures/items/apple.png%00'):
            with self.subTest(path=path):
                status, body, _ = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b'private-image', body)


if __name__ == '__main__':
    unittest.main()
