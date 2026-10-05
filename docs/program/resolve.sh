#!/usr/bin/env bash
# usage: resolve.sh <issue> <doc-url> <map-gist-line>
set -euo pipefail
n=$1; doc=$2; gist=$3; S=/c/Users/Scott/.claude/orchestrate/ares-n64-timing
cd /c/Users/Scott/repos/ares
gh issue view 1 --json body --jq .body > $S/mapbody.md
python "C:/Users/Scott/.claude/orchestrate/ares-n64-timing/map_add.py" "C:/Users/Scott/.claude/orchestrate/ares-n64-timing/mapbody.md" "$gist"
gh issue edit 1 --body-file $S/mapbody.md >/dev/null
gh issue comment $n --body "Answered: [doc]($doc). Gist added to the map's Decisions so far." >/dev/null
gh issue close $n >/dev/null
gh issue view 1 --json body --jq .body | grep -c "issues/$n)"
