# LXC Tools — Agent Setup, Install & Configuration Guide

This runbook is written for an AI agent operating on a Debian/Ubuntu host. It
describes how to install, configure, and verify **lxc-tools**, a Python CLI that
manages unprivileged LXC containers with ZFS backing and secure bind mounts.

The tool is a single executable, [`lxc-tools`](pyproject.toml), exposing six
subcommands:

```
lxc-tools create <name> [distro] [release] [arch] [quota]
lxc-tools start  <name>
lxc-tools stop   <name> [--kill]
lxc-tools list   [--active|--stopped]
lxc-tools remove <name> [--force]
lxc-tools restart <name>
```

A global `--dry-run` flag is supported before or after the subcommand and prints
actions without executing destructive changes.

> **Invocation note for auto-sudo**: subcommands that elevate to root re-exec
> via `sudo` using the invoked executable. Use the installed `lxc-tools`
> console script (not `python -m lxc_tools`) for any subcommand that
> auto-elevates, so the `sudo` re-exec resolves to an executable entry point
> that matches the sudoers rule.

---

## 1. Prerequisites & assumptions

- Debian/Ubuntu host with `apt`.
- A running ZFS pool already exists (the setup creates datasets under it).
- The operator knows the ZFS pool name (default assumed: `rpool`).
- Python 3.10+.

System packages required (installed in one of the tracks below):

```
lxc lxc-utils zfsutils-linux acl uidmap distro-info \
python3-pyzfs python3-lxc python3-distro-info liblxc-dev libacl1-dev
```

Native Python bindings used by the tool:

| Concern | Binding | Source |
|---|---|---|
| ZFS | `pyzfs` / `libzfs_core` | `python3-pyzfs` (apt — **no PyPI wheel**) |
| LXC | `lxc` | `python3-lxc` (apt) or `pip install lxc-python3` |
| POSIX ACLs | `posix1e` | `pylibacl` (pip, needs `libacl1-dev`) |
| LTS resolution | `distro_info` | `python3-distro-info` (apt) |

> Because `libzfs_core` has no PyPI package, the virtualenv **must** be created
> with `--system-site-packages` so the apt-installed bindings are visible.
> `pylibacl` additionally requires the `libacl1-dev` system package.

---

## 2. Environment detection (agent must run first)

Run these checks before choosing a track.

```bash
# 1. Operating system
. /etc/os-release && echo "$ID $VERSION_ID"

# 2. ZFS pools (there may be more than one; note the one you will use)
zfs list -o name -H 2>/dev/null | grep -v '/' || echo "NO_ZFS_OR_NO_POOL"

# 3. Passwordless sudo availability
sudo -n true 2>/dev/null && echo "HAVE_SUDO" || echo "NO_SUDO"

# 4. Python version
python3 --version
```

Record the results:

- **ZFS pool name** — required for the system setup. If step 2 printed
  `NO_ZFS_OR_NO_POOL` or listed multiple pools, ask the operator for the pool
  name before proceeding.
- **Sudo** — determines the track.

---

## 3. Decision tree

```
Have passwordless sudo (sudo -n true succeeds)?
 ├── YES ──► Track A (Section 4): agent performs everything directly.
 └── NO  ──► Track B (Section 5): agent performs non-privileged steps and
             emits a sysadmin script for the human operator.
```

---

## 4. Track A — agent has sudo

Perform every step directly.

### A.1 Install system packages

```bash
sudo apt-get update
sudo apt-get install -y \
  lxc lxc-utils zfsutils-linux acl uidmap distro-info \
  python3-pyzfs python3-lxc python3-distro-info liblxc-dev libacl1-dev
```

### A.2 Create virtualenv and install the package

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ".[test]"
pip install pylibacl        # libacl1-dev was installed in A.1
```

### A.3 Install the CLI at the sudoers path

```bash
sudo ln -sf "$PWD/.venv/bin/lxc-tools" /usr/local/bin/lxc-tools
```

### A.4 One-time system setup

Replace `<pool>` with the detected/confirmed pool name and `<user>` with the
username(s) that should manage containers (repeat the subuid/subgid and group
steps per user).

```bash
# Groups
sudo groupadd -f lxc-admin
sudo groupadd -f lxc-users

# Project directory
sudo mkdir -p /opt/project
sudo chown root:lxc-users /opt/project
sudo chmod 2775 /opt/project

# ZFS datasets (create only if missing)
if ! sudo zfs list <pool>/lxc/privileged >/dev/null 2>&1; then
    sudo zfs create <pool>/lxc/privileged
fi
if ! sudo zfs list <pool>/lxc/unprivileged >/dev/null 2>&1; then
    sudo zfs create <pool>/lxc/unprivileged
fi

# ZFS delegation
sudo zfs allow -g lxc-users create,destroy,mount,snapshot,quota,promote,rename,rollback,clone,mountpoint,canmount,userprop <pool>/lxc/unprivileged

# UID/GID mapping — use DEDICATED subordinate ranges, distinct per user:
#   1st user: 100000   2nd: 165536   3rd: 231072   ... (increment by 65536).
# Do NOT use $(id -u <user>) here: mapping container root onto the host user's
# own UID breaks unprivileged isolation.
echo "<user>:100000:65536" | sudo tee -a /etc/subuid
echo "<user>:100000:65536" | sudo tee -a /etc/subgid
sudo usermod -aG lxc-users <user>

# Sudoers — validate before installing
TMP_SUDOERS="$(mktemp)"
printf '%%lxc-users ALL=(ALL) NOPASSWD: /usr/local/bin/lxc-tools\n' | sudo tee "$TMP_SUDOERS" >/dev/null
sudo visudo -cf "$TMP_SUDOERS"
sudo install -m 440 "$TMP_SUDOERS" /etc/sudoers.d/lxc-automation
rm -f "$TMP_SUDOERS"
```

### A.5 Configure (INI)

Create a config file (system-wide or per-user). See
[`lxc-tools.conf.example`](lxc-tools.conf.example) for the template.

```bash
sudo mkdir -p /etc/lxc-tools
sudo cp lxc-tools.conf.example /etc/lxc-tools/lxc-tools.conf
# Edit /etc/lxc-tools/lxc-tools.conf to set the pool/bridge/project paths.
```

Minimum config (`/etc/lxc-tools/lxc-tools.conf`):

```ini
[zfs]
pool = <pool>

[paths]
project_dir = /opt/project

[network]
bridge = lxcbr0
```

### A.6 Verify

```bash
pytest
python -m lxc_tools --help
lxc-tools --dry-run create smoke-test
lxc-tools --dry-run remove smoke-test
```

> The dry-run subcommands elevate to root, so they use the `lxc-tools` console
> script (the symlink from A.3), not `python -m lxc_tools`.

---

## 5. Track B — agent does NOT have sudo

The agent performs all non-privileged steps, then emits a complete sysadmin
script for the human operator.

### B.1 Agent-performed steps (no privilege required)

```bash
# 1. Install Python tooling into a local virtualenv (no root needed)
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ".[test]"

# 2. Run the unit tests (pure-logic, no root needed)
pytest

# 3. Create a user-level config (does not require root)
mkdir -p ~/.config/lxc-tools
cp lxc-tools.conf.example ~/.config/lxc-tools/lxc-tools.conf
# Edit the file to set `pool = <pool>` and any overrides.
```

> **pylibacl ordering**: the ACL backend (`posix1e`) requires `libacl1-dev`,
> which only the operator can install. The `[test]` extra installs pytest only.
> Do **not** run `pip install pylibacl` yet — it will fail without
> `libacl1-dev`. After the operator has run the sysadmin script, run:
>
> ```bash
> pip install pylibacl
> ```

### B.2 Emit the sysadmin script

The agent must write the script in [Section 6](#6-sysadmin-script) to
`./setup-lxc-tools-root.sh`, make it executable, and tell the operator:

> "Please review and run `sudo ./setup-lxc-tools-root.sh`. It will install the
> system packages, create the groups and ZFS datasets, delegate ZFS
> permissions, configure UID/GID mappings, link the lxc-tools CLI, and install
> the sudoers entry."

The agent must substitute these variables at the top of the script before
handing it over:

| Variable | Meaning | Default |
|---|---|---|
| `LXC_TOOLS_SOURCE` | Path to the installed `lxc-tools` executable. In this track, the venv entry point (e.g. `$PWD/.venv/bin/lxc-tools`). | `/usr/local/bin/lxc-tools` |
| `LXC_TOOLS_LINK` | Canonical path the sudoers NOPASSWD rule uses. | `/usr/local/bin/lxc-tools` |
| `SUBUID_BASE` | Starting subordinate range for the first mapped user. | `100000` |
| `IDMAP_RANGE` | Size of each user's subuid/subgid range. | `65536` |
| `TARGET_USERS` | Space-separated users to map into containers. | *(empty)* |

> The script creates `LXC_TOOLS_LINK` as a symlink to `LXC_TOOLS_SOURCE` and
> grants NOPASSWD for `LXC_TOOLS_LINK`. Users must invoke `lxc-tools` (on PATH,
> resolving to the link) so the auto-sudo re-exec matches the NOPASSWD rule.

---

## 6. Sysadmin script

Full script for the human operator (also used by the agent in Track A.4 as a
reference for the exact privileged steps).

```bash
#!/usr/bin/env bash
# ============================================================================
# lxc-tools system setup — run as root:  sudo ./setup-lxc-tools-root.sh
# Idempotent: safe to re-run.
# ============================================================================
set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO} executing: ${BASH_COMMAND}" >&2; exit 1' ERR
trap 'rm -rf "${TMP_DIR:-}"' EXIT
TMP_DIR="$(mktemp -d -p /tmp lxctools.XXXXXX)"

# ---- configuration (edit as needed) ----------------------------------------
LXC_ZFS_POOL="${LXC_ZFS_POOL:-rpool}"
BASE_PROJECT_DIR="${BASE_PROJECT_DIR:-/opt/project}"
LXC_USERS_GROUP="${LXC_USERS_GROUP:-lxc-users}"
LXC_ADMIN_GROUP="${LXC_ADMIN_GROUP:-lxc-admin}"
SUBUID_BASE="${SUBUID_BASE:-100000}"
IDMAP_RANGE="${IDMAP_RANGE:-65536}"
# Source of the lxc-tools executable. In the no-sudo track set this to the
# venv entry point, e.g. /path/to/lxc-tools/.venv/bin/lxc-tools.
LXC_TOOLS_SOURCE="${LXC_TOOLS_SOURCE:-/usr/local/bin/lxc-tools}"
# Canonical path the sudoers NOPASSWD rule points at.
LXC_TOOLS_LINK="${LXC_TOOLS_LINK:-/usr/local/bin/lxc-tools}"
# Space-separated list of users who may create/manage containers.
TARGET_USERS="${TARGET_USERS:-}"

# ---- root + pre-install dependency assertions --------------------------------
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ This script must run as root (use sudo)." >&2
    exit 1
fi
require_bin() {
    command -v "$1" >/dev/null 2>&1 \
        || { echo "❌ Required binary missing: $1" >&2; exit 1; }
}
# Only tools that must exist BEFORE apt-get runs. Everything else (zfs, acl
# tools, groupadd/usermod) is installed by apt-get below and asserted after.
for bin in apt-get install visudo; do require_bin "$bin"; done

# ---- system packages ---------------------------------------------------------
apt-get update
apt-get install -y \
    lxc lxc-utils zfsutils-linux acl uidmap distro-info \
    python3-pyzfs python3-lxc python3-distro-info liblxc-dev libacl1-dev

# ---- post-install dependency assertions --------------------------------------
for bin in zfs groupadd usermod setfacl getfacl getent; do require_bin "$bin"; done

# ---- lxc-tools binary + canonical link ----------------------------------------
[ -x "${LXC_TOOLS_SOURCE}" ] \
    || { echo "❌ lxc-tools not found at ${LXC_TOOLS_SOURCE} — install the Python package first" >&2; exit 1; }
if [ "${LXC_TOOLS_SOURCE}" != "${LXC_TOOLS_LINK}" ]; then
    ln -sf "${LXC_TOOLS_SOURCE}" "${LXC_TOOLS_LINK}"
fi
echo "✅ lxc-tools available at ${LXC_TOOLS_LINK}"

# ---- groups ------------------------------------------------------------------
getent group "${LXC_ADMIN_GROUP}" >/dev/null 2>&1 || groupadd "${LXC_ADMIN_GROUP}"
getent group "${LXC_USERS_GROUP}" >/dev/null 2>&1 || groupadd "${LXC_USERS_GROUP}"
echo "✅ Groups: ${LXC_ADMIN_GROUP}, ${LXC_USERS_GROUP}"

# ---- project directory -------------------------------------------------------
mkdir -p "${BASE_PROJECT_DIR}"
chown "root:${LXC_USERS_GROUP}" "${BASE_PROJECT_DIR}"
chmod 2775 "${BASE_PROJECT_DIR}"
echo "✅ Project directory: ${BASE_PROJECT_DIR}"

# ---- ZFS datasets ------------------------------------------------------------
if zfs list "${LXC_ZFS_POOL}/lxc/privileged" >/dev/null 2>&1; then
    echo "✅ Dataset exists: ${LXC_ZFS_POOL}/lxc/privileged"
else
    zfs create "${LXC_ZFS_POOL}/lxc/privileged"
    echo "✅ Created: ${LXC_ZFS_POOL}/lxc/privileged"
fi
if zfs list "${LXC_ZFS_POOL}/lxc/unprivileged" >/dev/null 2>&1; then
    echo "✅ Dataset exists: ${LXC_ZFS_POOL}/lxc/unprivileged"
else
    zfs create "${LXC_ZFS_POOL}/lxc/unprivileged"
    echo "✅ Created: ${LXC_ZFS_POOL}/lxc/unprivileged"
fi

# ---- ZFS delegation ----------------------------------------------------------
zfs allow -g "${LXC_USERS_GROUP}" \
    create,destroy,mount,snapshot,quota,promote,rename,rollback,clone,mountpoint,canmount,userprop \
    "${LXC_ZFS_POOL}/lxc/unprivileged"
echo "✅ ZFS delegation configured for ${LXC_USERS_GROUP}"

# ---- subuid/subgid mappings + group membership -------------------------------
# Each user gets a distinct, non-overlapping subordinate range.
if [ -n "${TARGET_USERS}" ]; then
    read -r -a TARGET_USER_ARR <<< "${TARGET_USERS}"
    idx=0
    for user in "${TARGET_USER_ARR[@]}"; do
        uid_start=$(( SUBUID_BASE + idx * IDMAP_RANGE ))
        idx=$(( idx + 1 ))
        grep -q "^${user}:" /etc/subuid || echo "${user}:${uid_start}:${IDMAP_RANGE}" >> /etc/subuid
        grep -q "^${user}:" /etc/subgid || echo "${user}:${uid_start}:${IDMAP_RANGE}" >> /etc/subgid
        usermod -aG "${LXC_USERS_GROUP}" "${user}"
        echo "✅ Mapped + grouped user: ${user} (subuid start ${uid_start}, range ${IDMAP_RANGE})"
    done
fi

# ---- sudoers (validate before installing) ------------------------------------
SUDOERS_FILE="/etc/sudoers.d/lxc-automation"
SUDOERS_TMP="${TMP_DIR}/lxc-automation"
printf '%%%s ALL=(ALL) NOPASSWD: %s\n' "${LXC_USERS_GROUP}" "${LXC_TOOLS_LINK}" > "${SUDOERS_TMP}"
visudo -cf "${SUDOERS_TMP}"
install -m 440 "${SUDOERS_TMP}" "${SUDOERS_FILE}"
echo "✅ Sudoers installed: ${SUDOERS_FILE} (NOPASSWD for ${LXC_TOOLS_LINK})"

# ---- done --------------------------------------------------------------------
echo "🎉 lxc-tools system setup complete."
echo "   Pool:            ${LXC_ZFS_POOL}"
echo "   Project dir:     ${BASE_PROJECT_DIR}"
echo "   lxc-tools:       ${LXC_TOOLS_LINK}"
echo "   Users:           ${TARGET_USERS:-<none configured>}"
```

---

## 7. Configuration reference

Configuration is resolved in this order (highest precedence first):

1. Environment variables: `LXC_ZFS_POOL`, `LXC_PRIV_PATH`, `LXC_UNPRIV_BASE`,
   `BASE_PROJECT_DIR`, `LXC_NET_LINK`.
2. `/etc/lxc-tools/lxc-tools.conf` (INI)
3. `~/.config/lxc-tools/lxc-tools.conf` (INI)
4. `./lxc-tools.conf` (INI)
5. Built-in defaults (`rpool`, `lxcbr0`, `/opt/project`).

INI keys (sections are ignored; keys are matched case-insensitively):

| Key | Default | Description |
|---|---|---|
| `pool` | `rpool` | ZFS pool name |
| `priv_path` | `/<pool>/lxc/privileged` | Privileged container path |
| `unpriv_base` | `/<pool>/lxc/unprivileged` | Unprivileged container base |
| `project_dir` | `/opt/project` | Bind-mounted project directory |
| `bridge` | `lxcbr0` | Container network bridge |

`priv_path` and `unpriv_base` are derived from `pool` when omitted.

---

## 7.5 MCP server (AI agent integration)

A [FastMCP](https://github.com/punkpeye/fastmcp) server exposes `lxc-tools` as
MCP tools so an AI agent can inspect and manage LXC containers on localhost. It
is a thin adapter that shells out to the `lxc-tools` CLI, so it inherits the
existing sudoers trust model — **no root daemon is required**.

### Install

```bash
pip install -e ".[mcp]"
```

### Run (stdio transport)

```bash
lxc-tools-mcp                 # console script
python -m lxc_tools.mcp_server
fastmcp run lxc_tools.mcp_server
```

### Tools

`create_container`, `start_container`, `stop_container`, `restart_container`,
`list_containers`, `remove_container`, `container_info` (read-only) and
`config_dump` (read-only). Every mutating tool accepts `dry_run` to preview
actions without executing destructive steps.

### Client configuration

Register the server in your MCP client using the stdio transport, pointing at
the `lxc-tools-mcp` console script:

```json
{
  "mcpServers": {
    "lxc-tools": {
      "command": "/path/to/.venv/bin/lxc-tools-mcp",
      "args": []
    }
  }
}
```

> **Privilege note**: the server must run as a user who is a member of the
> `lxc-users` group and has the sudoers NOPASSWD rule for `lxc-tools`. The
> `lxc-tools-mcp` console script must be on the user's PATH so the CLI's
> auto-sudo re-exec resolves to the linked path matching the sudoers rule.

---

## 8. Verification checklist

### Non-privileged (any agent)

```bash
pytest
python -m lxc_tools --help
python -m lxc_tools create --help
```

### Privileged (root / operator)

```bash
# Dry-run subcommands (auto-elevate; use the lxc-tools console script)
lxc-tools --dry-run create smoke-test
lxc-tools --dry-run remove smoke-test

# Delegation present
zfs allow -l <pool>/lxc/unprivileged | grep lxc-users

# Sudoers entry present
sudo -l | grep lxc-tools

# ID mappings present
grep <user> /etc/subuid /etc/subgid
```

---

## 9. Common failures & remedies

| Symptom | Cause | Remedy |
|---|---|---|
| `ZFSError` / ZFS bindings missing | `python3-pyzfs` absent or venv lacks system packages | `sudo apt install python3-pyzfs`; recreate venv with `--system-site-packages` |
| ACL backend missing | `pylibacl` absent or `libacl1-dev` not installed | `sudo apt install libacl1-dev && pip install pylibacl` |
| `pip install pylibacl` fails to build | `libacl1-dev` missing | Install `libacl1-dev` first (operator step in the sysadmin script) |
| "not a member of lxc-users" | Group membership missing | `sudo usermod -aG lxc-users <user>` (re-login required) |
| `zfs allow` permission denied on create | Delegation missing | Run the sysadmin script (delegation step) |
| sudo password prompt | sudoers NOPASSWD not installed, or the invoked path differs from the sudoers rule | Re-run the sysadmin script sudoers step; invoke `lxc-tools` via the linked path |
| `sudo` re-exec fails (`Exec format error`) | Invoking a `.py` module directly (`python -m ...`) with a subcommand that auto-elevates | Use the `lxc-tools` console script for auto-elevating subcommands |
| Container creation "Couldn't find a matching image" | Distro/release unavailable | `lxc-create -n x -t download -- --list \| grep <distro>` |
