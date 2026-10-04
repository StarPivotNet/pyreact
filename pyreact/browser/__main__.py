"""Command-line entry point for the optional Python 3 preview server."""
import argparse
import importlib
import os
import sys

from . import serve


def main():
    parser = argparse.ArgumentParser(description="Preview real Pyreact components without Minecraft.")
    parser.add_argument("--app", default="pyreact.browser.demo:BrowserDemo",
                        help="Decorated component as importable.module:Component")
    parser.add_argument("--project", action="append", default=[],
                        help="Add a behavior-pack/project root to Python imports (repeatable)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=640)
    parser.add_argument("--resource-root", help="Optional resource-pack root containing textures/")
    parser.add_argument("--font-root", help="Game font atlas directory; auto-detect MC Studio by default")
    parser.add_argument("--no-open", action="store_true", help="Do not open the system browser")
    args = parser.parse_args()
    for directory in reversed(args.project):
        sys.path.insert(0, os.path.abspath(directory))
    module_name, separator, name = args.app.partition(":")
    if not separator or not module_name or not name:
        parser.error("--app must be importable.module:Component")
    try:
        root = getattr(importlib.import_module(module_name), name)
    except (ImportError, AttributeError) as error:
        parser.exit(1, "Cannot import %s: %s\nKeep game SDK imports outside the preview component.\n" %
                    (args.app, error))
    try:
        serve(root, port=args.port, width=args.width, height=args.height,
              resource_root=args.resource_root, open_browser=not args.no_open, font_root=args.font_root)
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, "Preview failed: %s\n" % error)


if __name__ == "__main__":
    main()
