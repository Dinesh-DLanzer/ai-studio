# Contributing

Thanks for helping! AI Studio is small and dependency-light on purpose.

## Setup
```
python3 -m venv .venv && ./.venv/bin/pip install -r requirements-dev.txt
(cd web && npm install)
./.venv/bin/python -m unittest discover -s tests      # all tests must pass, no network, no money
(cd web && npm run typecheck && npm run build)
./.venv/bin/python -m server.app                        # http://127.0.0.1:8765 (prints a token link)
for t in shell smoke chat assets import manage agent editor projects settings setup help; do node web/e2e/$t.mjs; done        # browser tests (needs `npx playwright install chromium` and ffmpeg)
python3 scripts/secret_scan.py
```

## Ground rules
1. **Tests never spend money or use the network.** Every test that touches the service, CLI, MCP or server must `import tests._hermetic` first: it removes any key and the test switch and uses a private empty key store, and sets `AISTUDIO_NO_NETWORK=1` (a kill switch real providers obey). Use `aistudio/providers/fake.py` or an injected transport.
2. **Safety code is sacred.** `approvals.py`, `gates.py`, the MCP tool list and the server's auth/host checks need a test for every rule and a careful review. The MCP server must never expose approval, budget-approval, clip-approval or provider tools.
3. **Files are the source of truth.** A project is a folder of plain files; the engine must never delete them (discard = move).
4. **Standard library first** in `aistudio/`. Web/server extras go in `requirements.txt` with a reason.
5. **New HTTP route?** Describe it in `server/api_docs.py` (a test fails if you do not). It is **page-only by default**; mark `agent=True` only if an MCP tool can already do the same thing and it can neither approve nor spend by itself.
6. **UI wording:** the chat AI is called Tara (`web/src/brand.ts`); a project is a *test project* or a *real project* (there is no app-wide mode); say "test", never "fake", in anything the user reads.
7. **New language or model?** Add what you tested (and what you did not) to `.claude/skills/ai-studio/reference.md`.
8. Never commit keys, client projects, or generated media (`projects/` is git-ignored on purpose).

## Good first contributions
Language packs (storyboard guidance per language), extra providers (an adapter in `aistudio/providers/adapters/`, registered in `providers/config.py`), vision-checklist improvements
(`aistudio/vision/`), more UI polish, translations of the docs.
