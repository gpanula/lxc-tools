#!/usr/bin/env python3
"""Helper script to invoke lxc_tools.mcp_server tools directly from the CLI."""

from __future__ import annotations

import argparse
import sys
from lxc_tools import mcp_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Call MCP server tools directly.")
    subparsers = parser.add_subparsers(dest="tool", required=True)

    # create
    p_create = subparsers.add_parser("create_container")
    p_create.add_argument("name")
    p_create.add_argument("--distro", default="ubuntu")
    p_create.add_argument("--release", default="lts")
    p_create.add_argument("--arch", default="amd64")
    p_create.add_argument("--quota", default=None)
    p_create.add_argument("--dry-run", action="store_true")

    # start
    p_start = subparsers.add_parser("start_container")
    p_start.add_argument("name")
    p_start.add_argument("--dry-run", action="store_true")

    # stop
    p_stop = subparsers.add_parser("stop_container")
    p_stop.add_argument("name")
    p_stop.add_argument("--kill", action="store_true")
    p_stop.add_argument("--dry-run", action="store_true")

    # restart
    p_restart = subparsers.add_parser("restart_container")
    p_restart.add_argument("name")
    p_restart.add_argument("--dry-run", action="store_true")

    # list
    p_list = subparsers.add_parser("list_containers")
    p_list.add_argument("--active", action="store_true")
    p_list.add_argument("--stopped", action="store_true")

    # remove
    p_remove = subparsers.add_parser("remove_container")
    p_remove.add_argument("name")
    p_remove.add_argument("--force", action="store_true")
    p_remove.add_argument("--dry-run", action="store_true")

    # info
    p_info = subparsers.add_parser("container_info")
    p_info.add_argument("name")

    # config
    subparsers.add_parser("config_dump")

    # snapshot
    p_snap = subparsers.add_parser("snapshot_container")
    p_snap.add_argument("name")
    p_snap.add_argument("--tag", default=None)
    p_snap.add_argument("--dry-run", action="store_true")

    # rollback
    p_roll = subparsers.add_parser("rollback_container")
    p_roll.add_argument("name")
    p_roll.add_argument("--tag", required=True)
    p_roll.add_argument("--no-restart", action="store_true")
    p_roll.add_argument("--force", action="store_true")
    p_roll.add_argument("--dry-run", action="store_true")

    # snapshots
    p_snaps = subparsers.add_parser("list_snapshots")
    p_snaps.add_argument("name")

    # exec
    p_exec = subparsers.add_parser("exec_container")
    p_exec.add_argument("name")
    p_exec.add_argument("--command", required=True)
    p_exec.add_argument("--snapshot", default=None)
    p_exec.add_argument("--no-snapshot", action="store_true")
    p_exec.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.tool == "create_container":
        res = mcp_server.create_container(
            name=args.name,
            distro=args.distro,
            release=args.release,
            arch=args.arch,
            quota=args.quota,
            dry_run=args.dry_run,
        )
    elif args.tool == "start_container":
        res = mcp_server.start_container(name=args.name, dry_run=args.dry_run)
    elif args.tool == "stop_container":
        res = mcp_server.stop_container(name=args.name, kill=args.kill, dry_run=args.dry_run)
    elif args.tool == "restart_container":
        res = mcp_server.restart_container(name=args.name, dry_run=args.dry_run)
    elif args.tool == "list_containers":
        res = mcp_server.list_containers(active=args.active, stopped=args.stopped)
    elif args.tool == "remove_container":
        res = mcp_server.remove_container(name=args.name, force=args.force, dry_run=args.dry_run)
    elif args.tool == "container_info":
        res = mcp_server.container_info(name=args.name)
    elif args.tool == "config_dump":
        res = mcp_server.config_dump()
    elif args.tool == "list_templates":
        res = mcp_server.list_templates(distro=args.distro)
    elif args.tool == "snapshot_container":
        res = mcp_server.snapshot_container(name=args.name, tag=args.tag, dry_run=args.dry_run)
    elif args.tool == "rollback_container":
        res = mcp_server.rollback_container(
            name=args.name,
            tag=args.tag,
            no_restart=args.no_restart,
            force=args.force,
            dry_run=args.dry_run,
        )
    elif args.tool == "list_snapshots":
        res = mcp_server.list_snapshots(name=args.name)
    elif args.tool == "exec_container":
        res = mcp_server.exec_container(
            name=args.name,
            command=args.command,
            snapshot=args.snapshot,
            no_snapshot=args.no_snapshot,
            dry_run=args.dry_run,
        )



    else:
        print(f"Unknown tool: {args.tool}", file=sys.stderr)
        return 1

    print(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
