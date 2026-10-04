"""Locate local game font sheets without bundling proprietary assets."""

import re
import sys
from pathlib import Path


def discover_font_root(font_root=None, resource_root=None):
    """Prefer an explicit atlas directory, then the pack, then MC Studio."""
    if font_root:
        root = Path(font_root).resolve()
        if not (root / 'default8.png').is_file():
            raise ValueError('--font-root must contain default8.png and glyph_XX.png sheets')
        return root
    candidates = []
    if resource_root:
        candidates.append(Path(resource_root) / 'font')
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Netease\MCStudio') as key:
                download, _ = winreg.QueryValueEx(key, 'DownloadPath')
            engines = Path(download) / 'game' / 'MinecraftPE_Netease'
            if engines.is_dir():
                versions = [p for p in engines.iterdir() if p.is_dir()
                            and re.fullmatch(r'\d+(?:\.\d+)*', p.name)]
                versions.sort(key=lambda p: tuple(map(int, p.name.split('.'))), reverse=True)
                candidates.extend(p / 'data/resource_packs/vanilla/font' for p in versions)
        except OSError:
            pass  # MC Studio is optional; previews remain available without it.
    for root in candidates:
        if (root / 'default8.png').is_file():
            return root.resolve()
    return None
