"""Resolve local Bedrock inventory assets without redistributing game files."""

import copy
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote


_JSON_COMMENTS = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*[\s\S]*?\*/')
_TRAILING_COMMA = re.compile(r',\s*([}\]])(?=(?:[^"\\]*"(?:\\.|[^"\\])*"|[^"\\])*\Z)')
_IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
_CUBES = {
    'stone', 'dirt', 'coarse_dirt', 'grass', 'grass_block', 'podzol', 'mycelium',
    'cobblestone', 'mossy_cobblestone', 'bedrock', 'sand', 'red_sand', 'gravel',
    'clay', 'glass', 'obsidian', 'crying_obsidian', 'netherrack', 'end_stone',
    'soul_sand', 'soul_soil', 'snow', 'snow_block', 'ice', 'packed_ice', 'blue_ice',
    'crafting_table', 'furnace', 'lit_furnace', 'bookshelf', 'bricks', 'brick_block',
    'stonebrick', 'stone_bricks', 'tnt', 'sponge', 'wet_sponge', 'melon_block',
    'pumpkin', 'lit_pumpkin', 'jack_o_lantern', 'hay_block', 'bone_block',
    'wool', 'planks', 'log', 'log2', 'concrete', 'concrete_powder', 'terracotta',
    'hardened_clay', 'stained_hardened_clay', 'sandstone', 'red_sandstone',
    'granite', 'diorite', 'andesite', 'deepslate', 'cobbled_deepslate', 'calcite',
    'tuff', 'basalt', 'smooth_basalt', 'blackstone', 'quartz_block',
}
_CUBE_SUFFIXES = ('_ore', '_planks', '_log', '_wood', '_wool', '_concrete',
                  '_concrete_powder', '_terracotta', '_bricks', '_nylium')
_SOLID_BLOCKS = {'coal', 'iron', 'gold', 'diamond', 'emerald', 'lapis', 'redstone',
                 'netherite', 'copper', 'raw_iron', 'raw_gold', 'raw_copper',
                 'amethyst', 'moss', 'slime', 'honey', 'dried_kelp'}
_ALIASES = {'wooden_sword': 'wood_sword', 'wooden_pickaxe': 'wood_pickaxe',
            'wooden_axe': 'wood_axe', 'wooden_shovel': 'wood_shovel',
            'wooden_hoe': 'wood_hoe', 'crossbow': 'crossbow_standby',
            'bow': 'bow_standby', 'grass_block': 'grass'}


def _read_json(path):
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding='utf-8-sig')
        text = _JSON_COMMENTS.sub(lambda match: match.group(1) or '', text)
        result = json.loads(_TRAILING_COMMA.sub(r'\1', text))
        return result if isinstance(result, dict) else {}
    except (OSError, UnicodeError, ValueError):
        return {}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _texture_path(value, aux):
    if isinstance(value, list):
        if not value or aux < 0 or aux >= len(value):
            return None
        value = value[aux]
    if isinstance(value, dict):
        value = value.get('path')
    return value if isinstance(value, str) else None


def _icon(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        texture = value.get('texture')
        textures = value.get('textures')
        if isinstance(texture, str):
            return texture
        if isinstance(textures, dict):
            return textures.get('default')
    return None


def _safe_path(root, name):
    if not isinstance(name, str) or '\\' in name or ':' in name or '\x00' in name:
        return None
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts:
        return None
    try:
        target = (root / relative).resolve()
        return target if target.is_relative_to(root) else None
    except (OSError, ValueError):
        return None


class ItemAssets:
    """A cached inventory view of an override pack and optional vanilla pack."""

    def __init__(self, resource_root=None, vanilla_root=None):
        self.roots = []
        for candidate in (resource_root, vanilla_root):
            if candidate:
                root = Path(candidate).resolve()
                if root.is_dir() and root not in self.roots:
                    self.roots.append(root)
        self.items = {}
        self.terrain = {}
        self.blocks = {}
        self.icons = {}
        self.basenames = {}
        self._cache = {}
        self._load()

    def _load(self):
        # Lower-priority definitions load first; image lookup uses reverse order.
        for root in reversed(self.roots):
            self.items.update(_mapping(_read_json(root / 'textures/item_texture.json').get('texture_data')))
            self.terrain.update(_mapping(_read_json(root / 'textures/terrain_texture.json').get('texture_data')))
            self.blocks.update(_read_json(root / 'blocks.json'))
            directory = root / 'items'
            if directory.is_dir():
                for path in sorted(directory.glob('*.json')):
                    item = _mapping(_read_json(path).get('minecraft:item'))
                    identifier = _mapping(item.get('description')).get('identifier')
                    icon = _icon(_mapping(item.get('components')).get('minecraft:icon'))
                    if isinstance(identifier, str) and isinstance(icon, str):
                        self.icons[identifier] = icon
        for value in self.items.values():
            textures = value.get('textures') if isinstance(value, dict) else None
            for entry in textures if isinstance(textures, list) else [textures]:
                path = _texture_path(entry, 0)
                if path:
                    self.basenames.setdefault(PurePosixPath(path).stem, path)

    def asset(self, name):
        """Return only an existing image confined to its indexed pack root."""
        if not isinstance(name, str):
            return None
        index, separator, relative = name.partition('/')
        if not separator or index not in tuple(str(i) for i in range(len(self.roots))):
            return None
        target = _safe_path(self.roots[int(index)], relative)
        if target and target.suffix.lower() in _IMAGE_SUFFIXES and target.is_file():
            return target
        return None

    def _url(self, path):
        if not path:
            return None
        for index, root in enumerate(self.roots):
            target = _safe_path(root, path)
            if target is None:
                continue
            candidates = [target] if target.suffix else [target.with_suffix(s) for s in _IMAGE_SUFFIXES]
            for candidate in candidates:
                candidate = candidate.resolve()
                if (candidate.is_relative_to(root) and candidate.suffix.lower() in _IMAGE_SUFFIXES
                        and candidate.is_file()):
                    relative = candidate.relative_to(root).as_posix()
                    return '/items/%s/%s' % (index, quote(relative, safe='/'))
        return None

    def _atlas(self, atlas, key, aux):
        if not isinstance(key, str):
            return None
        value = atlas.get(key, {})
        return _texture_path(value.get('textures'), aux) if isinstance(value, dict) else None

    def resolve(self, props):
        """Mirror native itemDict precedence and resolve browser render metadata."""
        props = props if isinstance(props, dict) else {}
        item = props.get('itemDict')
        item = item if isinstance(item, dict) else {}
        identifier = item.get('newItemName')
        if identifier is None:
            identifier = item.get('itemName')
        aux = item.get('newAuxValue')
        if aux is None:
            aux = item.get('auxValue', 0)
        enchant = bool(item.get('enchantData') or item.get('modEnchantData'))
        if props.get('identifier') is not None:
            identifier = props['identifier']
        if props.get('aux') is not None:
            aux = props['aux']
        if props.get('enchant') is not None:
            enchant = bool(props['enchant'])
        identifier = str(identifier or '').strip()
        try:
            aux = int(aux or 0)
        except (ValueError, TypeError, OverflowError):
            aux = 0
        key = (identifier, aux, enchant)
        if key not in self._cache:
            result = {'identifier': identifier, 'enchant': enchant}
            if identifier in ('', 'air', 'minecraft:air'):
                result['mode'] = 'empty'
            else:
                result.update(self._resolve(identifier, aux))
            self._cache[key] = result
        return copy.deepcopy(self._cache[key])

    def _resolve(self, identifier, aux):
        namespace, separator, name = identifier.partition(':')
        vanilla = not separator or namespace == 'minecraft'
        if not separator:
            name = namespace
        full_name = identifier if separator else 'minecraft:' + name
        icon = self.icons.get(full_name)
        keys = [icon, identifier]
        if vanilla:
            keys.append(name)
        for key in keys:
            if key is not None and key in self.items:
                return self._sprite(self._atlas(self.items, key, aux))
        if vanilla:
            texture_name = _ALIASES.get(name, name)
            if texture_name.startswith('golden_'):
                texture_name = 'gold_' + texture_name[len('golden_'):]
            if texture_name in self.basenames:
                return self._sprite(self.basenames[texture_name])
        block_key = full_name if full_name in self.blocks else name if vanilla else identifier
        block = self.blocks.get(block_key)
        if isinstance(block, dict):
            if not self._is_cube(name, block):
                return {'mode': 'missing', 'reason': 'This block needs game geometry; no inventory sprite is available'}
            return self._cube(block, name, aux)
        return {'mode': 'missing', 'reason': 'No local item texture or supported block definition was found'}

    def _sprite(self, path):
        url = self._url(path)
        if url:
            return {'mode': 'sprite', 'src': url}
        return {'mode': 'missing', 'reason': 'The referenced texture is unavailable or uses an unsupported format (for example TGA)'}

    @staticmethod
    def _is_cube(name, block):
        if block.get('geometry') == 'minecraft:geometry.full_block':
            return True
        if block.get('geometry') not in (None, 'minecraft:geometry.full_block'):
            return False
        return (name in _CUBES or name.endswith(_CUBE_SUFFIXES) or
                name.endswith('_block') and name[:-6] in _SOLID_BLOCKS)

    def _cube(self, block, name, aux):
        textures = block.get('carried_textures', block.get('textures'))
        if aux and name in self.terrain:
            textures = name
        if isinstance(textures, str):
            sides = dict.fromkeys(('top', 'left', 'right'), textures)
        elif isinstance(textures, dict):
            side = textures.get('side', textures.get('all'))
            sides = {'top': textures.get('up', textures.get('top', side)),
                     'left': textures.get('west', textures.get('north', side)),
                     'right': textures.get('south', textures.get('east', side))}
        else:
            sides = {}
        faces = {face: self._url(self._atlas(self.terrain, key, aux))
                 for face, key in sides.items()}
        if len(faces) == 3 and all(faces.values()):
            return {'mode': 'cube', 'faces': faces}
        return {'mode': 'missing', 'reason': 'Block face textures are unavailable or use an unsupported format (for example TGA)'}
