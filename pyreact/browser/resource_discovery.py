"""Discover the local vanilla item pack without distributing game resources."""
from pathlib import Path

from .font_discovery import discover_font_root


def discover_vanilla_root(vanilla_root=None, font_root=None):
    if vanilla_root is not None:
        root = Path(vanilla_root).resolve()
        if not root.is_dir():
            raise ValueError('--vanilla-root must be an existing resource-pack directory')
        return root
    candidates = [Path(font_root).parent] if font_root else []
    installed_font = discover_font_root()
    if installed_font:
        candidates.append(installed_font.parent)
    for root in candidates:
        if (root / 'textures/item_texture.json').is_file():
            return root.resolve()
    return None
