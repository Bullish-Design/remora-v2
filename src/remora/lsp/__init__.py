"""LSP adapter package."""


def create_lsp_server(*args, **kwargs):
    """Create the LSP server, raising a clear error if pygls is missing."""
    try:
        from remora.lsp.server import create_lsp_server as _create
    except ImportError as exc:
        raise ImportError(
            "LSP support requires pygls. Install with: pip install remora[lsp]"
        ) from exc
    return _create(*args, **kwargs)


def create_lsp_server_standalone(*args, **kwargs):
    """Create standalone LSP server, raising a clear error if pygls is missing."""
    try:
        from remora.lsp.server import create_lsp_server_standalone as _create
    except ImportError as exc:
        raise ImportError(
            "LSP support requires pygls. Install with: pip install remora[lsp]"
        ) from exc
    return _create(*args, **kwargs)


__all__ = ["create_lsp_server", "create_lsp_server_standalone"]
