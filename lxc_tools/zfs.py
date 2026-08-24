"""ZFS backend backed by the OpenZFS Python bindings (``pyzfs``).

The ``python3-pyzfs`` package ships both the high-level ``pyzfs`` API and the
low-level CFFI ``libzfs_core`` module. This backend prefers the high-level API
and falls back to ``libzfs_core`` for the operations it exposes. Mounting is
only supported through the high-level API.

Install (strictly native -- there is no PyPI wheel for libzfs_core)::

    sudo apt install python3-pyzfs
    python3 -m venv --system-site-packages .venv   # venv must see system pkgs
"""

from __future__ import annotations

import os
from typing import Optional

INSTALL_HINT = (
    "ZFS Python bindings are required (strictly native). Install with:\n"
    "  sudo apt install python3-pyzfs\n"
    "and ensure the virtualenv can see system packages:\n"
    "  python3 -m venv --system-site-packages .venv"
)


class ZFSError(Exception):
    """Raised for ZFS backend failures."""


def _load_backend() -> str:
    """Return the backend kind ('pyzfs' or 'lzc') or raise with an install hint."""
    try:
        from pyzfs.zfs import Dataset, ZFS  # noqa: F401

        return "pyzfs"
    except ImportError:
        pass
    try:
        import libzfs_core  # noqa: F401

        return "lzc"
    except ImportError:
        raise ZFSError(INSTALL_HINT)


class ZFS:
    """Thin native wrapper around the OpenZFS Python bindings."""

    def __init__(self) -> None:
        self._kind = _load_backend()

    # -- dataset helpers ------------------------------------------------------

    def exists(self, dataset: str) -> bool:
        if self._kind == "pyzfs":
            from pyzfs.zfs import Dataset, ZFS

            return bool(Dataset(dataset, ZFS()).exists)
        import libzfs_core

        return bool(libzfs_core.lzc_exists(dataset))

    def create(self, dataset: str, mountpoint: Optional[str] = None) -> None:
        """Create a dataset, optionally with an explicit mountpoint."""
        self._create_with(dataset, mountpoint=mountpoint)

    def create_recursive(self, dataset: str) -> None:
        """Create a dataset and any missing parent datasets (``-p`` semantics).

        The leading pool component (e.g. ``rpool``) is never created -- pools
        cannot be created via ``zfs create`` and are assumed to exist.
        """
        parts = dataset.split("/")
        for i in range(2, len(parts) + 1):
            ancestor = "/".join(parts[:i])
            if not self.exists(ancestor):
                self._create_with(ancestor, mountpoint=None)

    def _create_with(self, dataset: str, mountpoint: Optional[str]) -> None:
        if self.exists(dataset):
            return
        if self._kind == "pyzfs":
            from pyzfs.zfs import Dataset, ZFS

            ds = Dataset(dataset, ZFS())
            # Setting mountpoint at creation (mirrors `zfs create -o
            # mountpoint=...`) avoids an intermediate mount at the inherited
            # mountpoint.
            if mountpoint:
                ds.create(properties={"mountpoint": str(mountpoint)})
            else:
                ds.create()
            return
        import libzfs_core

        props = {"mountpoint": str(mountpoint).encode()} if mountpoint else None
        libzfs_core.lzc_create(
            dataset, libzfs_core.DATASET_TYPE_FILESYSTEM, props, None
        )

    def set_property(self, dataset: str, prop: str, value: str) -> None:
        if self._kind == "pyzfs":
            from pyzfs.zfs import Dataset, ZFS

            Dataset(dataset, ZFS()).properties[prop].value = value
            return
        import libzfs_core

        libzfs_core.lzc_set_props(dataset, {prop: str(value).encode()})

    def set_quota(self, dataset: str, quota: str) -> None:
        self.set_property(dataset, "quota", quota)

    def mount(self, dataset: str) -> None:
        """Mount the dataset at its mountpoint (pyzfs API only)."""
        if self._kind != "pyzfs":
            raise ZFSError(
                "Mounting requires the high-level pyzfs API. Install with "
                "sudo apt install python3-pyzfs."
            )
        from pyzfs.zfs import Dataset, ZFS

        ds = Dataset(dataset, ZFS())
        mountpoint = ds.mountpoint or ""
        if os.path.ismount(mountpoint):
            return
        try:
            ds.mount()
        except Exception as exc:
            if not os.path.ismount(mountpoint):
                raise ZFSError(
                    f"Failed to mount dataset {dataset}: {exc}"
                ) from exc

    def destroy(self, dataset: str) -> None:
        if not self.exists(dataset):
            return
        if self._kind == "pyzfs":
            from pyzfs.zfs import Dataset, ZFS

            Dataset(dataset, ZFS()).destroy()
            return
        import libzfs_core

        libzfs_core.lzc_destroy(dataset, False, False)
