# Development Standards & Contributing Guide

To maintain a clean, stable, and bisectable repository, all contributors and AI agents follow structured branch hygiene and the **[Gitmoji](https://gitmoji.dev/)** commit standard.

---

## 🌿 1. Branching & PR Workflow

### Branch Rules
* **Direct commits to `main` are prohibited.** All work must be developed on a dedicated branch and merged via Pull Request.
* A local `.githooks/pre-commit` hook guards against accidental commits on `main`.

### Branch Naming Conventions
Use descriptive prefixes for all branch names:
* `feat/<topic>` — New features, configurations, or modules (e.g., `feat/zfs-snapshot-schedule`)
* `fix/<topic>` — Bug fixes, syntax corrections, or troubleshooting (e.g., `fix/subuid-map-validation`)
* `docs/<topic>` — Documentation, roadmaps, or architecture notes (e.g., `docs/security-model`)
* `exp/<topic>` — Experiments, prototypes, or benchmark scripts (e.g., `exp/ipv6-networking`)

---

## 📌 2. Commit Message Format

Every commit message must begin with a valid **Gitmoji** (either the Unicode emoji or shortcode format):

```text
<gitmoji> [optional scope]: <description>
```

### Examples
* `✨ (create): add Alpine template aliases for common distros`
* `📝 (docs): update installation and configuration guide`
* `🔧 (config): add network bridge override via lxc-tools.conf`
* `🐛 (remove): fix force-flag validation for running containers`
* `🚀 (scripts): benchmark container startup times across distros`
* `♻️ (scripts): refactor shared config loader into common functions`

---

## 🎨 3. Common Gitmojis

| Gitmoji | Shortcode | Meaning / Use Case |
| :--- | :--- | :--- |
| ✨ | `:sparkles:` | Introduce new features, modules, or tools |
| 🐛 | `:bug:` | Fix a bug or logic error |
| 📝 | `:memo:` | Add or update documentation / roadmaps / READMEs |
| 🚀 | `:rocket:` | Performance improvements, speedups, or benchmark scripts |
| 🔧 | `:wrench:` | Configuration, tooling, or environment changes |
| 🧱 | `:bricks:` | Infrastructure, hardware, or system architecture updates |
| 🧠 | `:brain:` | Model integrations, prompt engineering, or MoE experiments |
| 🔒 | `:lock:` | Security fixes, credential handling, or permission updates |
| ♻️ | `:recycle:` | Refactoring code without altering external behavior |
| 🧪 | `:test_tube:` | Adding tests, validation harnesses, or verification suites |
| 🚧 | `:construction:` | Work in progress |
| 🎨 | `:art:` | Improving structure, formatting, or UI/TUI layout |
| 🗑️ | `:wastebasket:` | Deprecating or removing code/files |
| ➕ | `:heavy_plus_sign:` | Adding new dependencies |
| ➖ | `:heavy_minus_sign:` | Removing dependencies |

---

## ⚙️ 4. Automated Verification

* **Pre-commit Hook**: Blocks direct commits on `main` (`.githooks/pre-commit`).
* **Commit-msg Hook**: Validates Gitmoji prefix format on every commit (`.githooks/commit-msg`).
* **GitHub Actions CI**: Validates all incoming PRs and commits against the Gitmoji standard (`.github/workflows/gitmoji-check.yml`).

### Python Verification

The tooling is now a Python package (`lxc_tools/`). Before submitting a PR, verify your changes:

```bash
# Install the test tooling (pytest)
pip install -e ".[test]"

# Run the unit test suite
pytest

# Byte-compile the package (catches syntax errors)
python -m compileall -q lxc_tools

# Exercise the CLI help output
python -m lxc_tools --help
python -m lxc_tools <subcommand> --help

# Dry-run checks against non-destructive subcommands
python -m lxc_tools --dry-run create my-app
python -m lxc_tools --dry-run remove my-app
```

### Enable Git Hooks

The local hooks in `.githooks/` are **not active by default**. Enable them once per clone:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/commit-msg
```

> **Note**: `core.hooksPath` is a *local* Git setting and is not version-controlled, so each contributor must enable hooks on their own checkout.
