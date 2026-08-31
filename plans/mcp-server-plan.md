# Plan: FastMCP Server for LXC Container Management

## Goal

Expose the existing `lxc-tools` functionality as a Model Context Protocol (MCP)
server using [FastMCP](https://github.com/punkpeye/fastmcp), so an AI agent can
interact with and manage LXC containers on localhost.

## Decisions (confirmed with user)

| Decision | Choice |
|---|---|
| Privilege strategy | Run as a normal user; shell out to the existing `lxc-tools` CLI (which auto-sudoes). No root daemon. |
| Transport | stdio (FastMCP default), run via `fastmcp run` or `python -m`. |
| Tool surface | All six lifecycle ops (`create`, `start`, `stop`, `restart`, `list`, `remove`) plus read-only helpers (`container_info`, `config_dump`). |

## Architecture

The MCP server is a thin adapter over the existing CLI. It does **not** import
the `lxc_tools` backends directly; instead it invokes the installed `lxc-tools`
console script via `subprocess`, capturing stdout/stderr and mapping exit codes
to structured tool results. This preserves the existing sudoers trust model
(`/etc/sudoers.d/lxc-automation` grants `NOPASSWD` on `/usr/local/bin/lxc-tools`)
and avoids duplicating privilege logic.

```mermaid
flowchart LR
    AI[AI Client] -->|stdio JSON-RPC| MCP[FastMCP Server]
    MCP -->|subprocess| CLI[lxc-tools CLI]
    CLI -->|auto-sudo re-exec| SUDO[sudo root]
    SUDO -->|sudo -u user| LXC[LXC / ZFS / ACL backends]
    LXC --> C[Containers]
```

## Files to create / modify

### 1. `pyproject.toml` (modify)

- Add `fastmcp` to `dependencies` (or a new `mcp` optional extra).
- Add a console script entry point, e.g. `lxc-tools-mcp = "lxc_tools.mcp_server:main"`.

### 2. `lxc_tools/mcp_server.py` (new)

FastMCP application exposing tools. Key implementation details:

- `from fastmcp import FastMCP` and `mcp = FastMCP("lxc-tools")`.
- A shared `_run_cli(*args)` helper that:
  - Resolves the CLI binary via `shutil.which("lxc-tools")` (fallback to
    `python -m lxc_tools`).
  - Runs with `subprocess.run(..., capture_output=True, text=True)`.
  - Returns `(returncode, stdout, stderr)`.
  - Maps non-zero exit to a structured error string.
- Tools (each decorated with `@mcp.tool`):
  - `create_container(name, distro="ubuntu", release="lts", arch="amd64", quota=None, dry_run=False)`
  - `start_container(name, dry_run=False)`
  - `stop_container(name, kill=False, dry_run=False)`
  - `restart_container(name, dry_run=False)`
  - `list_containers(active=False, stopped=False)`
  - `remove_container(name, force=False, dry_run=False)`
  - `container_info(name)` — read-only, wraps `lxc-info` / `lxc-ls -f`.
  - `config_dump()` — read-only, prints resolved config (via `load_config`).
- `main()` entry point that calls `mcp.run()` (stdio transport).

### 3. `tests/test_mcp_server.py` (new)

- Unit tests for `_run_cli` argument construction (mock `subprocess.run`).
- Tests that each tool maps CLI args correctly and surfaces stderr on failure.
- Tests for `container_info` / `config_dump` read-only paths.

### 4. `README.md` + `AGENT_SETUP.md` (modify)

- Document the MCP server: install, run (`fastmcp run lxc_tools.mcp_server` or
  `python -m lxc_tools.mcp_server`), and a sample MCP client config block.

## Tool → CLI mapping

| Tool | CLI invocation |
|---|---|
| `create_container` | `lxc-tools create <name> [distro] [release] [arch] [quota] [--dry-run]` |
| `start_container` | `lxc-tools start <name> [--dry-run]` |
| `stop_container` | `lxc-tools stop <name> [--kill] [--dry-run]` |
| `restart_container` | `lxc-tools restart <name> [--dry-run]` |
| `list_containers` | `lxc-tools list [--active|--stopped]` |
| `remove_container` | `lxc-tools remove <name> [--force] [--dry-run]` |
| `container_info` | `lxc-info -n <name> -P <path>` (read-only) |
| `config_dump` | in-process `load_config()` (read-only) |

## Security notes

- The server inherits the CLI's input validation (`validate()` in
  `lxc_tools/commands/__init__.py`) because it shells out to the CLI, which
  rejects shell metacharacters and path traversal.
- Destructive ops (`remove`) still require `--force` to skip the CLI's
  confirmation prompt; the MCP tool exposes `force` explicitly rather than
  defaulting to it.
- `dry_run` is exposed on every mutating tool so agents can preview actions.

## Out of scope (for this iteration)

- HTTP/SSE transport (stdio only, per decision).
- Authentication/authorization beyond the existing sudoers model.
- Streaming container logs or interactive `lxc-attach`/`lxc-console`.
