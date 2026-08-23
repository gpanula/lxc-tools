# Agent Workspace Rules

## 1. Branching & Workflow Standards
* **No Direct Commits to `main`**: Never commit directly to the `main` branch. All work must be conducted on dedicated feature or task branches.
* **Branch Naming Standard**:
  * `feat/<topic>` — New features, configurations, or modules (e.g., `feat/zfs-snapshot-schedule`)
  * `fix/<topic>` — Bug fixes, syntax corrections, or troubleshooting (e.g., `fix/subuid-map-validation`)
  * `docs/<topic>` — Documentation, roadmaps, or notes (e.g., `docs/security-model`)
  * `exp/<topic>` — Experiments, prototypes, or benchmarks (e.g., `exp/ipv6-networking`)
* **Pull Request Workflow**: Push the branch and open/propose a Pull Request using the repository's PR template for human review and merge.

## 2. Git Commit Standards
* **Mandatory Gitmoji Prefix**: All Git commit messages created by the agent MUST start with a valid Gitmoji (Unicode emoji or shortcode) as defined in [`CONTRIBUTING.md`](./CONTRIBUTING.md) and [gitmoji.dev](https://gitmoji.dev/).
* **Commit Message Format**: `<gitmoji> [optional scope]: <description>`
  * *Example*: `✨ (create): add Alpine template aliases`
  * *Example*: `📝 (docs): update installation guide`
  * *Example*: `🔧 (config): add network bridge override`
* **Bot Author**: All commits must use the repository's local Git author configuration (`gpanula <github@kablah.com>`).

## 3. Safety & Verification Standards
* **Linux SysAdmin**: Always prefer dry-runs / check-mode / non-destructive inspection before applying changes.
* **Rollbacks & State**: Preserve file states and track changes cleanly.
* **Defensive Scripting & Error Traps**: All shell scripts in this repository must implement strict defensive error handling:
  * Strict error headers: `set -euo pipefail`
  * Error trap diagnostics: `trap 'echo "❌ [ERROR] Script failed on line ${LINENO} executing: ${BASH_COMMAND}" >&2; exit 1' ERR`
  * Exit cleanup traps: `trap 'rm -rf "${TMP_DIR:-}"' EXIT`
  * Temporary Directory Resilience: Never assume `$TMPDIR` exists or is initialized. Always ensure parent directories exist (`mkdir -p "${TMPDIR:-/tmp}"`) or explicitly specify `-p /tmp` when creating scratch files/directories (e.g. `mktemp -d -p /tmp` or `mktemp -d "/tmp/script_XXXXXX"`).
  * Explicit binary assertions: Explicitly verify that required binaries exist and are executable (`[ -x "${BIN}" ]`) before use.
  * Explicit tool path resolution: Do not rely on ambient system `$PATH` for core tooling. Resolve required binaries explicitly (`command -v lxc-create`, `command -v zfs`, `command -v setfacl`) and verify they are executable before invocation.
  * Functional sanity gates: Test binary execution and return codes before emitting success banners. Success banners (`🎉 ...`) must NEVER be printed if an intermediate assertion fails.

## 4. Privacy, Secrets & Sensitive Information
* **Zero Secret Commits**: Never commit, log, or hardcode API keys, personal access tokens (PATs), passwords, private SSH keys, or certificates. Always rely on environment variables (e.g., `$GH_TOKEN`) or git-ignored local credential files (`.git/credentials`).
* **Path & Identity Sanitization**: Never commit hardcoded user home directories (e.g., `/home/<user>`) or personally identifiable information into repository files. Always use `~`, `${HOME}`, or relative workspace paths.
* **Leak Prevention**: Ensure `.gitignore` continuously excludes `.env*`, credentials, local scratch logs, and environment configurations before staging changes.

## 5. Command Brevity & Permission Review Readability
* **Concise Shell Commands**: Avoid long, multi-line inline scripts (such as `python3 -c '...'` or embedded multi-line string blobs) in proposed tool commands to keep permission dialogs easy to review.
* **Script Encapsulation**: Encapsulate non-trivial Python or shell logic into dedicated scripts and invoke them with short, clear command lines (e.g. `python3 scripts/helper.py <subcommand> [args]`).
