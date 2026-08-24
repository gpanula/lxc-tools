# LXC Tools

A Python CLI for managing unprivileged LXC containers with ZFS backing and secure bind mounts to a shared project directory. This is the refactored successor to the legacy bash scripts (`create-lxc-project`, `start-lxc-project`, `stop-lxc-project`, `list-lxc-projects`, `remove-lxc-project`, `restart-lxc-project`), now exposed as a single `lxc-tools` command backed by a shared Python package.

## Features

- **Unprivileged Containers**: Run containers as non-root users with full isolation
- **ZFS Integration**: Native dataset creation, quota management, and mounting via the OpenZFS Python bindings (`python3-pyzfs` / `libzfs_core`)
- **Secure Bind Mounts**: Project directories bind-mounted into containers with proper POSIX ACLs (via `pylibacl`)
- **Flexible Configuration**: INI-file or environment-variable based customization
- **LTS Resolution**: Automatic resolution of the `lts` keyword to the latest stable release per distro
- **Dry-run**: `--dry-run` prints every action without executing destructive changes

## Prerequisites

### System Packages

```bash
sudo apt update
sudo apt install lxc lxc-utils zfsutils-linux acl uidmap distro-info \
  python3-pyzfs python3-lxc python3-distro-info liblxc-dev libacl1-dev
```

- `python3-pyzfs` provides the strictly-native ZFS backend (`libzfs_core` has **no PyPI wheel**).
- `python3-lxc` provides the LXC read/inspect binding.
- `python3-distro-info` provides LTS resolution for Ubuntu/Debian.
- `liblxc-dev` / `libacl1-dev` are build headers for the optional pip bindings.

### Python Virtual Environment

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .
```

> `--system-site-packages` is required so the apt-installed native bindings
> (`python3-pyzfs`, `python3-lxc`) are visible inside the venv. Install any
> pip-only bindings into the venv:
>
> ```bash
> pip install pylibacl      # POSIX ACL support (requires libacl1-dev)
> pip install lxc-python3   # alternative LXC binding compiled from source
> ```

Make the CLI available at the sudoers path:

```bash
sudo ln -sf "$PWD/.venv/bin/lxc-tools" /usr/local/bin/lxc-tools
```

### System Setup (Run Once as Root)

```bash
# 1. Create groups
sudo groupadd lxc-admin
sudo groupadd lxc-users

# 2. Create project directory
sudo mkdir -p /opt/project
sudo chown root:lxc-users /opt/project
sudo chmod 2775 /opt/project

# 3. Create ZFS datasets (adjust <pool> to your ZFS pool name)
sudo zfs create <pool>/lxc/privileged
sudo zfs create <pool>/lxc/unprivileged

# 4. Delegate ZFS permissions to lxc-users group
sudo zfs allow -g lxc-users create,destroy,mount,snapshot,quota,promote,rename,rollback,clone,mountpoint,canmount,userprop <pool>/lxc/unprivileged

# 5. Configure user ID mapping (run for each user in lxc-users)
echo "$(whoami):$(id -u):1" | sudo tee -a /etc/subuid /etc/subgid

# 6. Configure sudoers for passwordless execution
echo "%lxc-users ALL=(ALL) NOPASSWD: /usr/local/bin/lxc-tools" | sudo tee /etc/sudoers.d/lxc-automation
```

> The sudoers rule grants `lxc-users` passwordless execution of the single
> `lxc-tools` binary (all subcommands), matching the trust model of the legacy
> scripts which ran as root. See [SECURITY.md](SECURITY.md) for details.

## Configuration

Copy the example configuration to your preferred location:

```bash
# System-wide (requires root)
sudo mkdir -p /etc/lxc-tools
sudo cp lxc-tools.conf.example /etc/lxc-tools/lxc-tools.conf
sudo vi /etc/lxc-tools/lxc-tools.conf

# Or user-specific
mkdir -p ~/.config/lxc-tools
cp lxc-tools.conf.example ~/.config/lxc-tools/lxc-tools.conf
vi ~/.config/lxc-tools/lxc-tools.conf
```

Configuration is loaded in this order (first match wins):

1. Environment variables (e.g., `LXC_ZFS_POOL=mypool`)
2. `/etc/lxc-tools/lxc-tools.conf` (INI)
3. `~/.config/lxc-tools/lxc-tools.conf` (INI)
4. `./lxc-tools.conf` (INI)
5. Safe defaults (rpool, lxcbr0, /opt/project)

## Usage

Every subcommand supports `--help`, and the whole CLI supports a global `--dry-run` flag (accepted before or after the subcommand).

### Create a Container

```bash
# Basic: Ubuntu LTS, amd64, 10G quota
lxc-tools create my-app

# Debian stable, 20G quota
lxc-tools create my-debian debian lts amd64 20G

# Alpine LTS, shorthand (4-arg form)
lxc-tools create my-alpine alpine lts 50G

# Rocky Linux LTS
lxc-tools create my-rocky rockylinux lts amd64 30G

# Preview what would happen without executing destructive steps
lxc-tools --dry-run create my-app
```

### List Containers

```bash
# List your containers
lxc-tools list

# List only running containers
lxc-tools list --active

# List only stopped containers
lxc-tools list --stopped

# As root: list all system and user containers
sudo lxc-tools list
```

### Start/Stop/Restart

```bash
# Start a container
lxc-tools start my-app

# Stop gracefully
lxc-tools stop my-app

# Force kill
lxc-tools stop my-app --kill

# Restart
lxc-tools restart my-app
```

### Remove a Container

```bash
# Interactive removal (prompts for confirmation)
lxc-tools remove my-app

# Force removal without prompt
lxc-tools remove my-app --force

# Preview the removal
lxc-tools --dry-run remove my-app
```

### Connect to a Container

```bash
# Root shell
lxc-attach -n my-app -P /path/to/lxc

# Console
lxc-console -n my-app -P /path/to/lxc
```

## Directory Layout

```
/opt/project/
├── my-app/          # Bind-mounted into container at /opt/project
├── my-debian/
└── my-alpine/

/<pool>/lxc/
├── privileged/      # System-managed containers
└── unprivileged/
    └── <username>/
        ├── my-app/
        ├── my-debian/
        └── my-alpine/
```

## Project Layout

```
lxc_tools/
├── cli.py           # argparse dispatcher (lxc-tools entry point)
├── config.py        # INI configparser loader + env overrides + defaults
├── prereq.py        # sudo re-exec, identity, group gate, dependency checks
├── zfs.py           # native ZFS backend (pyzfs / libzfs_core)
├── lxc.py           # LXC backend (python3-lxc + documented CLI escapes)
├── acl.py           # POSIX ACL backend (pylibacl / posix1e)
├── distro.py        # LTS resolution
└── commands/        # create | start | stop | list | remove | restart
```

## Security Model

- **Unprivileged Containers**: Containers run under mapped UIDs (e.g., 100000+) isolated from the host
- **ZFS Quotas**: Each container has a configurable disk quota enforced at the filesystem level
- **ACLs**: Project directories have POSIX ACLs granting container root access only to its own project
- **Sudoers Delegation**: The CLI runs with minimal required privileges via `/etc/sudoers.d/lxc-automation`
- **Dry-run**: Destructive operations are gated behind `--dry-run` for safe inspection

See [SECURITY.md](SECURITY.md) for detailed security considerations.

## Troubleshooting

### Container creation fails with "Couldn't find a matching image"

Ensure the distribution and release are available on `images.linuxcontainers.org`. Check:

```bash
lxc-create -n test_lookup -t download -- --list | grep <distro>
```

### ZFS backend missing

```bash
sudo apt install python3-pyzfs
# and ensure the venv was created with --system-site-packages
python3 -m venv --system-site-packages .venv
```

### ACL backend missing

```bash
sudo apt install libacl1-dev
pip install pylibacl
```

### Permission denied errors

Verify:

- User is in the `lxc-users` group: `groups | grep lxc-users`
- ZFS permissions are delegated: `zfs allow -l <pool>/lxc/unprivileged | grep lxc-users`
- Sudoers entry exists: `sudo -l | grep lxc-tools`

### Container won't start

Check container config and logs:

```bash
lxc-info -n my-app -P /path/to/lxc
lxc-start -n my-app -P /path/to/lxc -F  # Foreground with output
```

## License

See [LICENSE](LICENSE) file.

## Contributing

Contributions are welcome. Please ensure Python code passes `pytest`, `python -m compileall lxc_tools` and the project lint style before submitting. See [CONTRIBUTING.md](CONTRIBUTING.md).
