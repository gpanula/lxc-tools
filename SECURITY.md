# Security Considerations

## Overview

These scripts implement a **delegated privilege model** where unprivileged users can manage their own LXC containers without full root access. This document outlines the security boundaries, assumptions, and best practices.

## Trust Boundaries

### Root Operations

The following operations require root privileges and are delegated via `sudoers`:

- Creating ZFS datasets and setting quotas
- Applying POSIX ACLs to project directories
- Configuring network interfaces and bridges
- Managing container lifecycle (create, destroy, start, stop)

**Sudoers Configuration** (`/etc/sudoers.d/lxc-automation`):
```bash
%lxc-users ALL=(ALL) NOPASSWD: /usr/local/bin/create-lxc-project, /usr/local/bin/remove-lxc-project, /usr/local/bin/list-lxc-projects, /usr/local/bin/start-lxc-project, /usr/local/bin/stop-lxc-project, /usr/local/bin/restart-lxc-project
```

This grants passwordless execution of these specific scripts only. Users cannot escalate to arbitrary root commands.

### User-Level Operations

Unprivileged users can:
- Create and manage containers in their own LXC path (`/<pool>/lxc/unprivileged/<username>/`)
- Access only their own containers and project directories
- Cannot access other users' containers or datasets

## Isolation Mechanisms

### 1. User Namespaces (UID Mapping)

Each unprivileged container runs with mapped UIDs:

```bash
# Example: user 'alice' (UID 1000) maps to container UID 0 as host UID 100000
lxc.idmap = u 0 100000 65536
lxc.idmap = g 0 100000 65536
```

**Effect**: Container root (UID 0) is actually UID 100000 on the host, preventing privilege escalation to host root.

### 2. ZFS Quotas

Each container's rootfs is a dedicated ZFS dataset with an enforced quota:

```bash
zfs set quota=10G <pool>/lxc/unprivileged/<user>/<container>
```

**Effect**: Containers cannot consume more than their allocated disk space, preventing denial-of-service attacks.

### 3. POSIX ACLs

Project directories are protected with ACLs granting access only to the container's mapped UID:

```bash
setfacl -R -m u:100000:rwx /opt/project/<container>
```

**Effect**: Only the specific container can access its project directory; other containers and users cannot.

### 4. LXC Confinement

LXC provides additional isolation:
- **AppArmor/SELinux**: Restrict container syscalls (if enabled on host)
- **Cgroups**: Limit CPU, memory, and I/O resources
- **Network Namespaces**: Isolated network stack per container

## Input Validation

All user-supplied parameters are validated:

- **Container names**: Alphanumeric, dots, underscores, dashes only (no shell metacharacters)
- **Distribution names**: Alphanumeric only
- **Release names**: Alphanumeric, dots, dashes only
- **Architecture names**: Alphanumeric only
- **Quota sizes**: Numeric with size suffix (K, M, G, T, P, E)

**Validation prevents**: Command injection, path traversal, and argument confusion attacks.

## Configuration Security

### Sensitive Paths

The following paths are environment-specific and should be customized:

- `LXC_ZFS_POOL`: Your ZFS pool name (default: `rpool`)
- `LXC_PRIV_PATH`: Privileged container path (default: `/<pool>/lxc/privileged`)
- `LXC_UNPRIV_BASE`: Unprivileged container base (default: `/<pool>/lxc/unprivileged`)
- `BASE_PROJECT_DIR`: Project bind-mount directory (default: `/opt/project`)
- `LXC_NET_LINK`: Network bridge (default: `lxcbr0`)

**Best Practice**: Store custom values in `/etc/lxc-tools/lxc-tools.conf` (system-wide) or `~/.config/lxc-tools/lxc-tools.conf` (user-specific). Do not hardcode in scripts.

### Configuration File Permissions

```bash
# System config should be readable by all, writable by root only
sudo chmod 644 /etc/lxc-tools/lxc-tools.conf

# User config should be readable/writable by owner only
chmod 600 ~/.config/lxc-tools/lxc-tools.conf
```

## Known Limitations

### 1. Kernel Vulnerabilities

Container isolation depends on the Linux kernel. Kernel CVEs affecting namespaces, cgroups, or AppArmor can compromise isolation.

**Mitigation**: Keep the host kernel and LXC packages up to date.

### 2. Shared Kernel

All containers share the host kernel. A kernel exploit in one container can affect all containers and the host.

**Mitigation**: Use a hardened kernel (e.g., with AppArmor/SELinux enabled) and monitor for CVEs.

### 3. Privileged Operations

Users with `lxc-users` group membership can create containers with arbitrary configurations. A malicious user could:
- Create a container with `lxc.cap.drop` set to allow dangerous capabilities
- Disable AppArmor confinement
- Mount host filesystems into the container

**Mitigation**: Only add trusted users to the `lxc-users` group. Audit container configurations regularly.

### 4. ZFS Delegation

Users can destroy their own ZFS datasets, including snapshots. There is no built-in backup or recovery mechanism.

**Mitigation**: Implement external ZFS snapshots and backups at the pool level.

## Audit & Monitoring

### Log Container Creation

```bash
# Monitor /var/log/auth.log for sudo usage
sudo tail -f /var/log/auth.log | grep create-lxc-project

# Check ZFS dataset creation
zfs list -r <pool>/lxc/unprivileged
```

### Verify ACLs

```bash
# Check project directory ACLs
getfacl -R /opt/project/<container>

# Verify container UID mapping
lxc-info -n <container> -P <path> | grep idmap
```

### Container Inspection

```bash
# List all containers and their states
lxc-ls -f -P <path>

# Check container resource limits
lxc-cgroup -n <container> -P <path> memory.limit_in_bytes
```

## Recommendations

1. **Principle of Least Privilege**: Only add users to `lxc-users` who need container management.
2. **Regular Updates**: Keep LXC, ZFS, and the kernel up to date.
3. **Network Isolation**: Use separate network bridges for different container groups if needed.
4. **Backup Strategy**: Implement ZFS snapshots and off-site backups for critical containers.
5. **Audit Logging**: Monitor `/var/log/auth.log` for privileged operations.
6. **AppArmor/SELinux**: Enable and maintain security profiles for additional confinement.

## Reporting Security Issues

If you discover a security vulnerability in these scripts, please report it responsibly:

1. Do not disclose the vulnerability publicly
2. Contact the maintainers privately
3. Allow time for a fix before public disclosure

## References

- [LXC Security](https://linuxcontainers.org/lxc/security/)
- [Linux Namespaces](https://man7.org/linux/man-pages/man7/namespaces.7.html)
- [POSIX.1e ACLs](https://man7.org/linux/man-pages/man5/acl.5.html)
- [ZFS Security](https://openzfs.org/wiki/Security)
