# LXC Tools

A suite of bash scripts for managing unprivileged LXC containers with ZFS backing and secure bind mounts to a shared project directory.

## Features

- **Unprivileged Containers**: Run containers as non-root users with full isolation
- **ZFS Integration**: Automatic dataset creation, quota management, and snapshots
- **Secure Bind Mounts**: Project directories bind-mounted into containers with proper ACLs
- **Flexible Configuration**: Environment-based or config-file-based customization
- **LTS Resolution**: Automatic resolution of "lts" keyword to latest stable release per distro

## Prerequisites

### System Packages

```bash
sudo apt update
sudo apt install lxc lxc-utils zfsutils-linux acl
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
echo "%lxc-users ALL=(ALL) NOPASSWD: /usr/local/bin/create-lxc-project, /usr/local/bin/remove-lxc-project, /usr/local/bin/list-lxc-projects, /usr/local/bin/start-lxc-project, /usr/local/bin/stop-lxc-project, /usr/local/bin/restart-lxc-project" | sudo tee /etc/sudoers.d/lxc-automation
```

### Configuration

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
2. `/etc/lxc-tools/lxc-tools.conf`
3. `~/.config/lxc-tools/lxc-tools.conf`
4. `./lxc-tools.conf` (current directory)
5. Safe defaults (rpool, lxcbr0, /opt/project)

## Usage

### Create a Container

```bash
# Basic: Ubuntu LTS, amd64, 10G quota
create-lxc-project my-app

# Debian stable, 20G quota
create-lxc-project my-debian debian lts amd64 20G

# Alpine LTS, shorthand (4-arg form)
create-lxc-project my-alpine alpine lts 50G

# Rocky Linux LTS
create-lxc-project my-rocky rockylinux lts amd64 30G
```

### List Containers

```bash
# List your containers
list-lxc-projects

# List only running containers
list-lxc-projects --active

# List only stopped containers
list-lxc-projects --stopped

# As root: list all system and user containers
sudo list-lxc-projects
```

### Start/Stop/Restart

```bash
# Start a container
start-lxc-project my-app

# Stop gracefully
stop-lxc-project my-app

# Force kill
stop-lxc-project my-app --kill

# Restart
restart-lxc-project my-app
```

### Remove a Container

```bash
# Interactive removal (prompts for confirmation)
remove-lxc-project my-app

# Force removal without prompt
remove-lxc-project my-app --force
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

## Security Model

- **Unprivileged Containers**: Containers run under mapped UIDs (e.g., 100000+) isolated from the host
- **ZFS Quotas**: Each container has a configurable disk quota enforced at the filesystem level
- **ACLs**: Project directories have POSIX ACLs granting container root access only to its own project
- **Sudoers Delegation**: Scripts run with minimal required privileges via `/etc/sudoers.d/lxc-automation`

See [SECURITY.md](SECURITY.md) for detailed security considerations.

## Troubleshooting

### Container creation fails with "Couldn't find a matching image"

Ensure the distribution and release are available on `images.linuxcontainers.org`. Check:

```bash
lxc-create -n test_lookup -t download -- --list | grep <distro>
```

### Permission denied errors

Verify:
- User is in the `lxc-users` group: `groups | grep lxc-users`
- ZFS permissions are delegated: `zfs allow -l <pool>/lxc/unprivileged | grep lxc-users`
- Sudoers entry exists: `sudo -l | grep create-lxc-project`

### Container won't start

Check container config and logs:

```bash
lxc-info -n my-app -P /path/to/lxc
lxc-start -n my-app -P /path/to/lxc -F  # Foreground with output
```

## License

See [LICENSE](LICENSE) file.

## Contributing

Contributions are welcome. Please ensure scripts pass `shellcheck` and `bash -n` syntax checks before submitting.
