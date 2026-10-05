# research-docs
PR: https://github.com/wScottSh/ares/pull/48 (feat/research-docs -> master). Not merged.
- 25 origin/research/* branches, 63 files under docs/research/ copied via git checkout (no merges). Per-branch counts in PR body. Largest: scheduler-granularity 19, determinism 8, mm-filesel-slowdown 8.
- Skipped: research/mm-rdp-stream also modifies 7 ares/n64 sources (cpu.cpp, mi.cpp, n64.hpp, rdp/io.cpp, rdp/render.cpp, rsp/interpreter-ipu.cpp, rsp/io.cpp). Not brought. All other branches docs-only.
- No path conflicts.
- Verified: all 63 files blob-id identical to branch versions at commit 1 (git rev-parse compare; working tree shows CRLF via autocrlf, so byte cmp on checkout is misleading). Commit 2 rewrites blob/research links to relative paths in 6 docs (ares-timing-architecture, mm-buffer-placement, mm-rdp-stream, rdp-noise, rsp-recompiler-timing, span-ram), so those 6 differ from branch by link text only. No such links in docs/adr, docs/design, tools.
- docs/research/README.md: 25 rows; 23 from map Decisions; ares-timing-architecture has no ticket (listed as map #1 ground); jgemu-dpc-probe etc. per map. (25 docs, 23 map entries matched.)
- tools/n64-timing/map-links.py: stdin -> stdout rewrite; --check exits 1 on missing target. On current map body: 23 links, 0 missing, rc=0; output has 0 blob/research links.
- Coordinator after merge: gh issue view 1 -R wScottSh/ares --json body --jq .body | python tools/n64-timing/map-links.py > body.md ; then gh issue edit 1 --body-file body.md
