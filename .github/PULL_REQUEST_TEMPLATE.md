## What and why

## Checklist
- [ ] `python -m unittest discover -s tests` passes (no network, no money)
- [ ] `cd web && npm run typecheck && npm run build` passes
- [ ] New HTTP route? It is described in `server/api_docs.py`
- [ ] Safety code (approvals, gates, MCP tools, auth) changed? Every rule has a test
- [ ] No keys, tokens, client projects or generated media in the diff
