"""lxc-tools remove: safely remove an unprivileged LXC container.

Removes the LXC container, its ZFS dataset and its host project directory.
Prompts for confirmation unless ``--force`` is given.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from lxc_tools import lxc as lxc_backend, prereq, zfs
from lxc_tools.commands import common_parser, guarded, validate
from lxc_tools.config import load_config
from lxc_tools.prereq import require_binaries, require_member_of

_BINARIES = ("lxc-stop", "lxc-destroy", "zfs")


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "remove",
        parents=[common_parser()],
        help="Remove an unprivileged LXC container.",
        description=(
            "Safely removes an unprivileged LXC container: stops and destroys "
            "it, destroys its ZFS dataset and deletes its host project folder."
        ),
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Skip the confirmation prompt. May be given before or after the name.",
    )
    parser.add_argument(
        "container_name", metavar="container_name", help="Name of the container to remove."
    )
    parser.set_defaults(func=run)


@guarded
def run(args) -> int:
    prereq.ensure_root_or_reexec()
    user = prereq.resolve_current_user()
    require_member_of(user)
    require_binaries(_BINARIES)
    cfg = load_config()
    name = args.container_name

    validate(name, "container_name")

    lxc_path = f"{cfg.unpriv_base}/{user}"
    zfs_root = f"{cfg.zfs_pool}/lxc/unprivileged/{user}"
    container_dir = Path(lxc_path) / name
    if not container_dir.is_dir():
        raise prereq.PrereqError(f"Error: Container '{name}' not found in {lxc_path}.")

    if not args.force:
        print("WARNING: This will permanently destroy:")
        print(f"  - Container:  {name}")
        print(f"  - Dataset:    {zfs_root}/{name}")
        print(f"  - Project:    {cfg.project_dir}/{name}")
        confirm = input("Are you absolutely sure you want to proceed? [y/N] ")
        if confirm.strip().lower() not in ("y", "yes"):
            print("Removal cancelled.")
            return 0

    print(f"--- Starting removal of container: {name} ---")

    # 1. Stop the container if running (best effort).
    print("[1/4] Stopping container (if running)...")
    try:
        lxc_backend.stop(name, lxc_path, user=user, kill=True, dry_run=args.dry_run)
    except lxc_backend.LXCError:
        pass

    # 2. Destroy the ZFS dataset first so the rootfs mountpoint is unmounted.
    dataset = f"{zfs_root}/{name}"
    print(f"[2/4] Destroying ZFS dataset: {dataset}")
    backend = zfs.ZFS()
    if backend.exists(dataset):

        def destroy_dataset() -> None:
            backend.destroy(dataset)

        prereq.dry_or(args.dry_run, "  Destroying ZFS dataset", destroy_dataset)
    else:
        print("Dataset not found. Skipping.")

    # 3. Destroy the LXC container.
    print(f"[3/4] Destroying LXC container '{name}'...")
    try:
        lxc_backend.destroy(name, lxc_path, user=user, dry_run=args.dry_run)
    except lxc_backend.LXCError:
        if container_dir.exists():
            shutil.rmtree(container_dir)


    # 4. Remove the project directory.
    subdir = Path(cfg.project_dir) / name
    print(f"[4/4] Removing project directory: {subdir}")
    if subdir.is_symlink():
        print(f"Error: {subdir} is a symlink. Manual removal required for safety.")
    elif subdir.exists():

        def remove_dir() -> None:
            shutil.rmtree(subdir)

        prereq.dry_or(args.dry_run, "  Removing project directory", remove_dir)
    else:
        print("Project directory not found. Skipping.")

    print("--- Removal complete! ---")
    return 0
