#!/usr/bin/env bash
# sentry-instrumentation installer — one command per agent.
#
# Usage:
#   scripts/install.sh --agent=<name> [--project=<path>] [--skill-clone=<path>]
#
# Agents: claude-code, cursor, codex, aider, continue, windsurf
# (Claude.ai web is not scriptable — see adapters/claude-ai-web.md.)
#
# Idempotent: re-run safely after the skill updates.

set -euo pipefail

AGENT=""
PROJECT=""
PROJECT_EXPLICIT=0
SKILL_CLONE=""

usage() {
    cat <<'EOF'
sentry-instrumentation installer

Usage:
  scripts/install.sh --agent=<name> [--project=<path>] [--skill-clone=<path>]

Agents:
  claude-code   symlink into ~/.claude/skills/ (or <project>/.claude/skills/)
  cursor        write <project>/.cursor/rules/sentry-instrumentation.mdc
  codex         insert skill-enable block into <project>/AGENTS.md
  aider         write <project>/CONVENTIONS.md
  continue      write <project>/.continuerules
  windsurf      write <project>/.windsurfrules

Options:
  --agent=<name>         required
  --project=<path>       target project dir (default: $PWD; ignored for
                         user-level claude-code)
  --skill-clone=<path>   path to the cloned skill repo (default: this
                         script's repo root)
  --help                 show this help

Claude.ai web is not scriptable — upload via Settings -> Skills.
EOF
}

for arg in "$@"; do
    case "$arg" in
        --agent=*)       AGENT="${arg#*=}" ;;
        --project=*)     PROJECT="${arg#*=}"; PROJECT_EXPLICIT=1 ;;
        --skill-clone=*) SKILL_CLONE="${arg#*=}" ;;
        --help|-h)       usage; exit 0 ;;
        *) echo "error: unknown argument: $arg" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "$AGENT" ]]; then
    echo "error: --agent=<name> is required" >&2
    usage >&2
    exit 2
fi

if [[ -z "$PROJECT" ]]; then
    PROJECT="${PWD}"
fi

# Resolve skill-clone to the repo root containing this script.
if [[ -z "$SKILL_CLONE" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SKILL_CLONE="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

if [[ ! -f "$SKILL_CLONE/SKILL.md" ]]; then
    echo "error: skill-clone at '$SKILL_CLONE' does not look like the skill repo (no SKILL.md)" >&2
    exit 1
fi

MINIMAL_CONCAT_FILES=(
    "$SKILL_CLONE/SKILL.md"
    "$SKILL_CLONE/references/signal-model.md"
    "$SKILL_CLONE/references/tagging-and-cardinality.md"
    "$SKILL_CLONE/references/surface-patterns.md"
    "$SKILL_CLONE/references/failure-taxonomy.md"
)

concat_minimal() {
    local out="$1"
    local header="$2"
    mkdir -p "$(dirname "$out")"
    {
        if [[ -n "$header" ]]; then
            printf '%s\n' "$header"
        fi
        cat "${MINIMAL_CONCAT_FILES[@]}"
    } > "$out"
}

install_claude_code() {
    local target
    if [[ "$PROJECT_EXPLICIT" -eq 1 ]]; then
        target="${PROJECT}/.claude/skills/sentry-instrumentation"
    else
        target="${HOME}/.claude/skills/sentry-instrumentation"
    fi
    mkdir -p "$(dirname "$target")"
    if [[ -L "$target" ]]; then
        local current
        current="$(readlink "$target")"
        if [[ "$current" == "$SKILL_CLONE" ]]; then
            echo "Done: symlink already points at $SKILL_CLONE ($target)"
            return 0
        fi
        rm "$target"
    elif [[ -e "$target" ]]; then
        echo "error: $target exists and is not a symlink; refusing to overwrite" >&2
        exit 1
    fi
    ln -s "$SKILL_CLONE" "$target"
    echo "Done: wrote symlink $target -> $SKILL_CLONE"
}

install_concat() {
    # $1 = output path relative to $PROJECT
    # $2 = optional frontmatter header
    local out="${PROJECT}/$1"
    concat_minimal "$out" "$2"
    echo "Done: wrote $out"
}

install_cursor() {
    local header
    header='---
description: Sentry instrumentation rules — see sentry-instrumentation skill
globs: **/*.py
alwaysApply: true
---
'
    install_concat ".cursor/rules/sentry-instrumentation.mdc" "$header"
}

install_aider() {
    install_concat "CONVENTIONS.md" ""
}

install_continue() {
    install_concat ".continuerules" ""
}

install_windsurf() {
    install_concat ".windsurfrules" ""
}

install_codex() {
    local out="${PROJECT}/AGENTS.md"
    local begin="<!-- BEGIN sentry-instrumentation -->"
    local end="<!-- END sentry-instrumentation -->"
    local block
    block="$(cat <<EOF
$begin
## Sentry instrumentation

This project uses the \`sentry-instrumentation\` skill. When writing code
that emits a Sentry metric, measures duration, counts failures, wraps a
workflow step, or adds a retry or fallback path:

1. Read \`$SKILL_CLONE/SKILL.md\`.
2. Follow its decision rules and surface patterns.
3. For deeper rules (tagging, cost model, lifecycle), open the relevant
   file under \`$SKILL_CLONE/references/\`.
4. Use \`$SKILL_CLONE/examples/python/\` as the canonical drop-in
   reference.

Never hand-roll emissions — use the surface patterns (middleware,
decorator, base class). Never pass a raw string to an emit helper.
$end
EOF
)"

    mkdir -p "$(dirname "$out")"
    if [[ -f "$out" ]] && grep -qF "$begin" "$out"; then
        # Replace the existing block in place.
        local tmp block_file
        tmp="$(mktemp)"
        block_file="$(mktemp)"
        printf '%s\n' "$block" > "$block_file"
        awk -v begin="$begin" -v end="$end" -v block_file="$block_file" '
            BEGIN {
                while ((getline line < block_file) > 0) {
                    block = (block == "" ? line : block "\n" line)
                }
                close(block_file)
            }
            $0 == begin { skip = 1; print block; next }
            skip && $0 == end { skip = 0; next }
            !skip { print }
        ' "$out" > "$tmp"
        mv "$tmp" "$out"
        rm -f "$block_file"
        echo "Done: updated skill-enable block in $out"
    else
        if [[ -f "$out" ]]; then
            printf '\n%s\n' "$block" >> "$out"
        else
            printf '# Agents guide\n\n%s\n' "$block" > "$out"
        fi
        echo "Done: appended skill-enable block to $out"
    fi
}

case "$AGENT" in
    claude-code) install_claude_code ;;
    cursor)      install_cursor ;;
    codex)       install_codex ;;
    aider)       install_aider ;;
    continue)    install_continue ;;
    windsurf)    install_windsurf ;;
    *)
        echo "error: unknown agent '$AGENT'" >&2
        echo "       valid: claude-code, cursor, codex, aider, continue, windsurf" >&2
        exit 2
        ;;
esac
