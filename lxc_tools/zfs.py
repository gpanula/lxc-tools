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
import shutil
import subprocess
from typing import Optional

INSTALL_HINT = (
    "ZFS Python bindings or zfs CLI are required. Install with:\n"
    "  sudo apt install zfsutils-linux python3-pyzfs\n"
    "and ensure the virtualenv can see system packages:\n"
    "  python3 -m venv --system-site-packages .venv"
)


class ZFSError(Exception):
    """Raised for ZFS backend failures."""


def _load_backend() -> str:
    """Return the backend kind ('pyzfs', 'lzc', or 'cli') or raise with an install hint."""
    try:
        from pyzfs.zfs import Dataset, ZFS  # noqa: F401

        return "pyzfs"
    except ImportError:
        pass
    try:
        import libzfs_core  # noqa: F401

        return "lzc"
    except ImportError:
        pass
    if shutil.which("zfs"):
        return "cli"
    raise ZFSError(INSTALL_HINT)


class ZFS:
    """Thin native wrapper around the OpenZFS Python bindings with CLI fallback."""

    def __init__(self) -> None:
        self._kind = _load_backend()

    # -- dataset helpers ------------------------------------------------------

    def exists(self, dataset: str) -> bool:
        if self._kind == "pyzfs":
            try:
                from pyzfs.zfs import Dataset, ZFS

                return bool(Dataset(dataset, ZFS()).exists)
            except Exception:
                pass
        if self._kind == "lzc":
            try:
                import libzfs_core

                return bool(libzfs_core.lzc_exists(dataset.encode()))
            except Exception:
                pass
        proc = subprocess.run(["zfs", "list", dataset], capture_output=True, text=True)
        return proc.returncode == 0

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
            try:
                from pyzfs.zfs import Dataset, ZFS

                ds = Dataset(dataset, ZFS())
                if mountpoint:
                    ds.create(properties={"mountpoint": str(mountpoint)})
                else:
                    ds.create()
                return
            except Exception:
                pass
        if self._kind == "lzc":
            try:
                import libzfs_core

                props = {"mountpoint": str(mountpoint).encode()} if mountpoint else None
                ost = getattr(
                    libzfs_core,
                    "LZC_DATSET_TYPE_ZFS",
                    getattr(libzfs_core, "DATASET_TYPE_FILESYSTEM", 0),
                )
                libzfs_core.lzc_create(dataset.encode(), ost, props, None)
                return
            except Exception:
                pass

        cmd = ["zfs", "create"]
        if mountpoint:
            cmd.extend(["-o", f"mountpoint={mountpoint}"])
        cmd.append(dataset)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ZFSError(f"Failed to create dataset {dataset}: {proc.stderr.strip()}")

    def set_property(self, dataset: str, prop: str, value: str) -> None:
        if self._kind == "pyzfs":
            try:
                from pyzfs.zfs import Dataset, ZFS

                Dataset(dataset, ZFS()).properties[prop].value = value
                return
            except Exception:
                pass
        if self._kind == "lzc":
            try:
                import libzfs_core

                libzfs_core.lzc_set_props(
                    dataset.encode(), {prop.encode(): str(value).encode()}
                )
                return
            except Exception:
                pass
        proc = subprocess.run(
            ["zfs", "set", f"{prop}={value}", dataset],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise ZFSError(
                f"Failed to set property {prop}={value} on {dataset}: {proc.stderr.strip()}"
            )

    def set_quota(self, dataset: str, quota: str) -> None:
        self.set_property(dataset, "quota", quota)

    def mount(self, dataset: str) -> None:
        """Mount the dataset at its mountpoint."""
        if self._kind == "pyzfs":
            try:
                from pyzfs.zfs import Dataset, ZFS

                ds = Dataset(dataset, ZFS())
                mountpoint = ds.mountpoint or ""
                if os.path.ismount(mountpoint):
                    return
                ds.mount()
                return
            except Exception:
                pass
        proc = subprocess.run(["zfs", "mount", dataset], capture_output=True, text=True)
        if proc.returncode != 0 and "already mounted" not in proc.stderr:
            raise ZFSError(f"Failed to mount dataset {dataset}: {proc.stderr.strip()}")

    def destroy(self, dataset: str) -> None:
        if not self.exists(dataset):
            return
        if self._kind == "pyzfs":
            try:
                from pyzfs.zfs import Dataset, ZFS

                Dataset(dataset, ZFS()).destroy()
                return
            except Exception:
                pass
        if self._kind == "lzc":
            try:
                import libzfs_core

                libzfs_core.lzc_destroy(dataset.encode(), True, False)
                return
            except Exception:
                pass
        proc = subprocess.run(
            ["zfs", "destroy", "-r", dataset], capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise ZFSError(f"Failed to destroy dataset {dataset}: {proc.stderr.strip()}")


    # -- snapshot helpers -----------------------------------------------------

    def snapshot(self, dataset: str, snap_name: str) -> str:
        """Create a snapshot of ``dataset`` named ``snap_name``."""
        full_snap = f"{dataset}@{snap_name}"
        if self._kind == "lzc":
            try:
                import libzfs_core

                libzfs_core.lzc_snapshot([full_snap.encode()])
                return full_snap
            except Exception:
                pass
        proc = subprocess.run(
            ["zfs", "snapshot", full_snap], capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise ZFSError(
                f"Failed to create snapshot {full_snap}: {proc.stderr.strip()}"
            )
        return full_snap

    def rollback(
        self, dataset: str, snap_name: str, destroy_newer: bool = True
    ) -> None:
        """Roll back ``dataset`` to ``snap_name``.

        When ``destroy_newer`` is True (default), intermediate snapshots are
        destroyed (matching ``zfs rollback -r``).
        """
        full_snap = f"{dataset}@{snap_name}"
        cmd = ["zfs", "rollback"]
        if destroy_newer:
            cmd.append("-r")
        cmd.append(full_snap)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ZFSError(
                f"Failed to roll back to {full_snap}: {proc.stderr.strip()}"
            )

    def list_snapshots(self, dataset: str) -> list[dict[str, str]]:
        """Return list of snapshots for ``dataset``."""
        proc = subprocess.run(
            [
                "zfs",
                "list",
                "-t",
                "snapshot",
                "-r",
                "-H",
                "-o",
                "name,used,referenced,creation",
                "-s",
                "creation",
                dataset,
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return []
        results: list[dict[str, str]] = []
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                parts = line.split()
            if len(parts) >= 4:
                name = parts[0]
                snap_tag = name.split("@")[-1] if "@" in name else name
                results.append(
                    {
                        "name": name,
                        "tag": snap_tag,
                        "used": parts[1],
                        "referenced": parts[2],
                        "creation": parts[3] if len(parts) == 4 else " ".join(parts[3:]),
                    }
                )
        return results

    def destroy_snapshot(self, dataset: str, snap_name: str) -> None:
        """Destroy a snapshot of ``dataset``."""
        full_snap = f"{dataset}@{snap_name}"
        if self._kind == "lzc":
            try:
                import libzfs_core

                libzfs_core.lzc_destroy_snaps([full_snap.encode()], False)
                return
            except Exception:
                pass
        proc = subprocess.run(
            ["zfs", "destroy", full_snap], capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise ZFSError(
                f"Failed to destroy snapshot {full_snap}: {proc.stderr.strip()}"
            )

