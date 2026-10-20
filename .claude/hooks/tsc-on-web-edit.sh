#!/usr/bin/env sh
# PostToolUse (Edit|Write|MultiEdit): type-check the web app after a .ts/.tsx edit under web/src.
# Exit 2 sends the compiler errors back to Claude so it fixes them before moving on.
file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))')
case "$file" in
  */web/src/*.ts|*/web/src/*.tsx) ;;
  *) exit 0 ;;
esac
cd "$CLAUDE_PROJECT_DIR/web" || exit 0
out=$(npx tsc --noEmit 2>&1) || { echo "$out" | tail -40 >&2; exit 2; }
exit 0
