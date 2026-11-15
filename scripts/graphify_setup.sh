#!/usr/bin/env bash
# graphify_setup.sh - one-command graphify setup for a fresh clone.
#
# Installs graphify's git hooks, records the interpreter that can import
# graphify so the hooks have a fast path that survives a uv tool reinstall,
# and seeds the initial knowledge graph if none exists.
#
# Idempotent: safe to re-run at any time. Re-running refreshes the pinned
# interpreter and re-installs the hooks in place.
#
# Usage:
#   scripts/graphify_setup.sh              # hooks + interpreter + seed graph
#   scripts/graphify_setup.sh --hooks-only # skip the initial graph build
#   scripts/graphify_setup.sh --check      # report state, change nothing

set -euo pipefail
trap 'echo "❌ [ERROR] Script failed on line ${LINENO} executing: ${BASH_COMMAND}" >&2; exit 1' ERR

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

HOOKS_ONLY=0
CHECK_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --hooks-only) HOOKS_ONLY=1 ;;
        --check)      CHECK_ONLY=1 ;;
        -h|--help)
            sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "❌ Unknown argument: $arg" >&2
            echo "   Try --help" >&2
            exit 2
            ;;
    esac
done

# --- 1. Resolve the graphify launcher -------------------------------------
GRAPHIFY_BIN="$(command -v graphify || true)"
if [ -z "$GRAPHIFY_BIN" ]; then
    echo "❌ graphify not found on PATH." >&2
    echo "   Install it with: uv tool install graphifyy" >&2
    echo "   Then re-run this script from a shell where 'graphify' resolves." >&2
    exit 1
fi
if [ ! -x "$GRAPHIFY_BIN" ]; then
    echo "❌ graphify at $GRAPHIFY_BIN is not executable." >&2
    exit 1
fi
echo "✅ graphify launcher: $GRAPHIFY_BIN"

# --- 2. Resolve an interpreter that can import graphify -------------------
# Mirrors the probe the generated hooks use, so the value written here is
# exactly what they will accept. Candidates are tried in order; the first
# one that passes wins.
PROBE="import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('graphify') else 1)"
GRAPHIFY_PYTHON=""

# 2a. The launcher's shebang (uv tool, pipx, venv installs).
SHEBANG="$(head -c 256 "$GRAPHIFY_BIN" 2>/dev/null | tr -d '\000' | head -n 1 || true)"
case "$SHEBANG" in
    '#!'*)
        CAND="${SHEBANG#\#!}"
        CAND="${CAND# }"
        case "$CAND" in
            */env\ *) CAND="${CAND#*/env }" ;;
        esac
        if [ -x "$CAND" ] && "$CAND" -c "$PROBE" 2>/dev/null; then
            GRAPHIFY_PYTHON="$CAND"
        fi
        ;;
esac

# 2b. uv tool environments, in case the launcher is a binary trampoline.
if [ -z "$GRAPHIFY_PYTHON" ]; then
    for TOOLS_DIR in "${UV_TOOL_DIR:-}" "$HOME/.local/share/uv/tools"; do
        [ -n "$TOOLS_DIR" ] || continue
        for CAND in "$TOOLS_DIR"/*/bin/python; do
            [ -x "$CAND" ] || continue
            if "$CAND" -c "$PROBE" 2>/dev/null; then
                GRAPHIFY_PYTHON="$CAND"
                break 2
            fi
        done
    done
fi

# 2c. Ambient interpreters.
if [ -z "$GRAPHIFY_PYTHON" ]; then
    for CAND in python3 python; do
        if command -v "$CAND" >/dev/null 2>&1 && "$CAND" -c "$PROBE" 2>/dev/null; then
            GRAPHIFY_PYTHON="$(command -v "$CAND")"
            break
        fi
    done
fi

if [ -z "$GRAPHIFY_PYTHON" ]; then
    echo "❌ Could not find a Python interpreter that can import graphify." >&2
    echo "   The hooks will still work via their own fallback chain, but the" >&2
    echo "   fast path cannot be recorded. Re-run from the env where graphify lives." >&2
    exit 1
fi
echo "✅ graphify interpreter: $GRAPHIFY_PYTHON"

if [ "$CHECK_ONLY" = "1" ]; then
    echo
    echo "--- current state ---"
    graphify hook status || true
    if [ -f graphify-out/graph.json ]; then
        echo "graph: present ($(wc -c < graphify-out/graph.json) bytes)"
    else
        echo "graph: absent (run without --check to build it)"
    fi
    exit 0
fi

# --- 3. Record the interpreter for the hooks ------------------------------
mkdir -p graphify-out
printf '%s' "$GRAPHIFY_PYTHON" > graphify-out/.graphify_python
echo "✅ wrote graphify-out/.graphify_python"

# --- 4. Install the git hooks --------------------------------------------
# graphify appends to existing hooks and respects core.hooksPath, so this
# lands in .githooks/ here and leaves pre-commit / commit-msg untouched.
graphify hook install
echo "✅ git hooks installed"

# --- 5. Seed the initial graph -------------------------------------------
if [ "$HOOKS_ONLY" = "1" ]; then
    echo "⏭️  --hooks-only: skipping initial graph build"
elif [ -f graphify-out/graph.json ]; then
    echo "⏭️  graph already exists; refreshing incrementally"
    graphify update .
else
    echo "🔨 building initial graph (code only, no LLM, no API key)"
    graphify extract . --code-only
    graphify cluster-only . --no-label
fi

# --- 6. Verify ------------------------------------------------------------
echo
echo "--- verification ---"
graphify hook status
if [ ! -f graphify-out/graph.json ]; then
    echo "❌ graphify-out/graph.json is missing after setup." >&2
    exit 1
fi
if [ ! -s graphify-out/.graphify_python ]; then
    echo "❌ graphify-out/.graphify_python is missing or empty." >&2
    exit 1
fi

echo
echo "🎉 graphify setup complete."
echo "   Query the graph:  graphify query \"<question>\""
echo "   Rebuild manually: graphify update ."
echo "   Skip a rebuild:   GRAPHIFY_SKIP_HOOK=1 git commit ..."
