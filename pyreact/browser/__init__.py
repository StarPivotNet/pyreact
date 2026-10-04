"""Optional desktop browser preview; never imported by the game runtime."""


def serve(root, host="127.0.0.1", port=8765, width=960, height=640,
          resource_root=None, open_browser=True, font_root=None, vanilla_root=None):
    """Preview a decorated component using Python 3 and a local browser."""
    from .server import serve as run_server
    return run_server(root, host, port, width, height, resource_root, open_browser,
                      font_root, vanilla_root)
