"""Shared exceptions for remora core."""

from __future__ import annotations


class IncompatibleBundleError(Exception):
    """Raised when a bundle's externals version exceeds the runtime's."""

    def __init__(self, bundle_version: int, runtime_version: int) -> None:
        self.bundle_version = bundle_version
        self.runtime_version = runtime_version
        super().__init__(
            f"Bundle requires externals version {bundle_version}, "
            f"but runtime supports version {runtime_version}"
        )


__all__ = ["IncompatibleBundleError"]
