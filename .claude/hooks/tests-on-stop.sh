#!/usr/bin/env sh
# Stop: when Python files differ from HEAD, run the unit tests before Claude finishes its turn.
# Skips when the Python diff is unchanged since the last green run (stamp in .git/), and never loops twice.
input=$(cat)
active=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("stop_hook_active", False))')
[ "$active" = "True" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
changed=$( { git diff --name-only HEAD -- '*.py'; git ls-files --others --exclude-standard -- '*.py'; } 2>/dev/null )
[ -z "$changed" ] && exit 0
stamp=.git/aistudio-tests-green
sig=$( { git diff HEAD -- '*.py'; for f in $(git ls-files --others --exclude-standard -- '*.py'); do cat "$f"; done; } | shasum | cut -d' ' -f1)
[ -f "$stamp" ] && [ "$(cat "$stamp")" = "$sig" ] && exit 0
out=$(./.venv/bin/python -m unittest discover -s tests 2>&1)
if [ $? -ne 0 ]; then
  { echo "Python tests failed; fix before finishing:"; echo "$out" | tail -40; } >&2
  exit 2
fi
echo "$sig" > "$stamp"
exit 0
