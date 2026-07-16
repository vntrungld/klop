#!/usr/bin/env bash
# PostToolUse: format and autofix Python files with Ruff after Edit/Write.
set -euo pipefail

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty')

if [[ -z "$file_path" ]]; then
  exit 0
fi

case "$file_path" in
  *.py) ;;
  *) exit 0 ;;
esac

# Resolve path relative to project if needed
if [[ "$file_path" != /* ]]; then
  file_path="${CLAUDE_PROJECT_DIR:-$PWD}/$file_path"
fi

if [[ ! -f "$file_path" ]]; then
  exit 0
fi

# Prefer project venv ruff, then PATH
if [[ -n "${CLAUDE_PROJECT_DIR:-}" && -x "${CLAUDE_PROJECT_DIR}/.venv/bin/ruff" ]]; then
  RUFF="${CLAUDE_PROJECT_DIR}/.venv/bin/ruff"
elif command -v ruff >/dev/null 2>&1; then
  RUFF=ruff
else
  # Soft skip when ruff is not installed (non-blocking for the agent)
  echo "ruff not found; skip format for $file_path" >&2
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$file_path")}"
"$RUFF" format "$file_path" >/dev/null
# Autofix safe issues; do not fail the edit if remaining lints need human judgment
"$RUFF" check --fix "$file_path" >/dev/null 2>&1 || true
exit 0
