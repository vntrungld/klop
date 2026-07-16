#!/usr/bin/env bash
# PreToolUse: block Edit/Write on venv, caches, and other protected paths.
set -euo pipefail

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // empty')

if [[ -z "$file_path" ]]; then
  exit 0
fi

# Normalize to absolute when possible for reliable matching
case "$file_path" in
  /*) abs="$file_path" ;;
  *) abs="${CLAUDE_PROJECT_DIR:-$PWD}/$file_path" ;;
esac

blocked_patterns=(
  '/\.venv/'
  '/venv/'
  '/__pycache__/'
  '\.pyc$'
  '/\.git/'
  '/\.pytest_cache/'
  '/\.ruff_cache/'
  '/dist/'
  '/build/'
  '\.egg-info/'
)

for pat in "${blocked_patterns[@]}"; do
  if printf '%s' "$abs" | grep -Eq "$pat"; then
    echo "Blocked edit to protected path: $file_path" >&2
    echo "Edit source under src/ or tests/ instead of generated/venv/cache paths." >&2
    exit 2
  fi
done

exit 0
