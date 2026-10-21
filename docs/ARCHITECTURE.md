# AI Studio Architecture

This document describes the high-level architecture of AI Studio, the layers, the money flow, and where to extend the system.

## Layers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            WEB / CLI / MCP CLIENTS                          │
│  React UI (web/)  ◄── HTTP API (server/app.py)  ◄── MCP Server (mcp_server)│
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FACADE SERVICE                                 │
│                        aistudio/service.py (Service)                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│    DOMAIN        │    │    CREW          │    │    RECIPES       │
│  (domain/*.py)   │    │  (crew/*.py)     │    │  (recipes.py)    │
├──────────────────┤    ├──────────────────┤    ├──────────────────┤
│ projects.py      │    │ agents.py        │    │ validate()       │
│ storyboard.py    │    │ stages.py        │    │ plan()           │
│ pipeline.py      │    │ runtime.py       │    │ run_item()       │
│ characters.py    │    └──────────────────┘    └──────────────────┘
│ costs.py         │
│ todos.py         │
│ chat.py          │
│ agents.py        │
│ spec.py          │
│ verify.py        │
│ batches.py       │
│ common.py        │
└──────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PROVIDERS / ADAPTERS LAYER                             │
│  aistudio/providers/                                                        │
│  ├── config.py          # Provider types, role chains, adapter loading      │
│  ├── base.py            # Adapter base class, capabilities, methods         │
│  └── adapters/          # One file per provider type                        │
│       ├── openrouter.py │   ├── google.py       │   ├── openai.py          │
│       ├── anthropic.py  │   ├── runway.py       │   ├── kling.py           │
│       ├── replicate.py  │   ├── elevenlabs.py   │   ├── hedra.py           │
│       ├── heygen.py     │   ├── tavus.py        │   ├── google_cloud_tts.py│
│       ├── azure_speech.py│  ├── sarvam.py       │   ├── stability.py       │
│       ├── cartesia.py   │   ├── fal.py          │   ├── whisper_cpp.py     │
│       ├── sync_so.py    │   ├── comfyui.py      │   ├── chatgpt.py         │
│       ├── cli_agent.py  │   ├── custom.py       │   ├── fake.py            │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CATALOG / SPEC / PRICING                                 │
│  aistudio/                                                                  │
│  ├── pricing.py           # rates.json loader, price resolution             │
│  ├── formats.py           # Project formats (aspect, shots, safe area)      │
│   ├── catalog/                                                          │
│   │   ├── agents/           # Agent definitions (catalog/agents/*.md)     │
│   │   ├── recipes/          # Recipe data files (catalog/recipes/*.json)  │
│   │   ├── camera_presets.json                                            │
│   ├── rates.py              # Built-in model rates                        │
│   ├── models.json           # User capability/price overrides (settings)  │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  APPROVALS / GATES / LOCKS / JOBS                           │
│  aistudio/                                                                  │
│  ├── approvals.py          # Proposal/budget approval, elicitation, codes   │
│  ├── gates.py              # Budget stop-loss, attempt limits, spec checks  │
│  ├── costlog.py            # CSV cost log, spent/discarded split            │
│  ├── jobs.py               # Durable job ledger (survives restart)          │
│  ├── consent.py            # real_person flag, SHA-bound consent records    │
│  ├── secrets.py            # OS keychain / file secret store (write-only)   │
│  ├── apikeys.py            # API key management (hash-only storage)        │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ENGINE / INFRASTRUCTURE                             │
│  aistudio/                                                                  │
│  ├── project.py            # Project facade, file I/O, JSON save/load       │
│  ├── schemas/              # Pydantic models for all project JSON files     │
│  ├── history.py            # Document versioning (git-like per file)        │
│  ├── editor.py             # Timeline edit (OTIO, FCPXML, EDL, SRT, VTT)   │
│  ├── library.py            # Workspace media library search                 │
│  ├── cli.py                # CLI commands                                   │
│  ├── mcp_server.py         # MCP stdio server, tool dispatch, elicitation  │
│  ├── tools.py              # Local tools (reframe, assemble, etc.)          │
│  └── activity.py           # Project activity log                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Money Path: From Proposal to Cost Log (ASCII Diagram)

```
USER ACTION                          ENGINE FLOW                            PERSISTENCE
────────────────────────────────────────────────────────────────────────────────────────
                                                                     ┌─────────────────┐
                                                                     │  budget.json    │
                                                                     │  (approved,     │
1. USER: "Generate clip for shot s01"                               │   stop_loss)    │
   │                                                                 │                 │
   ▼                                                                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 2. propose(kind="clip", target="s01")                                                 │
│    ──► spec.resolve() ──► model, price, capabilities                                   │
│    ──► gates.can_spend(price) ──► checks budget, stop-loss, attempts                  │
│    ──► Proposal created: {id, kind, target, model, price, request_hash, status}      │
└─────────────────────────────────────────────────────────────────────────────────────┘
   │                                                                     │
   │                           ┌────────────────────────────────────────┘
   │                           ▼
   │                  ┌──────────────────┐
   │                  │ proposals.jsonl  │  (append-only, one line per proposal)
   │                  │ {id, kind,       │
   │                  │  target, model,  │
   │                  │  price, status,  │
   │                  │  request_hash,   │
   │                  │  code, code_id}  │
   │                  └──────────────────┘
   │
   ▼
3. HUMAN APPROVAL (MCP elicitation OR one-time fallback code)
   ┌─────────────────────────────────────────────────────────────┐
   │ approve_proposal(id, code)                                  │
   │   ──► Validates code (elicitation accept OR HMAC fallback)  │
   │   ──► proposal.status = "approved"                          │
   │   ──► proposal.approved_at, approved_by set                 │
   └─────────────────────────────────────────────────────────────┘
   │
   ▼
4. EXECUTION (run_proposal or run_batch)
   ┌─────────────────────────────────────────────────────────────┐
   │ execute(proposal_id)                                        │
   │   ──► gates.can_run(proposal) ──► re-checks model, price,   │
   │       request_hash, input file SHA, consent                 │
   │   ──► Creates JOB in ledger: {id, kind, target, state,      │
   │       provider_job, batch_id, actor, created}               │
   │   ──► Calls adapter.method() (e.g. video_submit)            │
   │   ──► On provider response: job.state = "done", result      │
   │   ──► costlog.append({provider, kind, target, model,        │
   │       price_usd, request_hash, exact=true, job_id})         │
   └─────────────────────────────────────────────────────────────┘
   │                                                                     │
   ▼                                                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 5. COST LOG (cost_log.csv)                                                           │
│    date,project,kind,target,model,provider,price_usd,request_hash,exact,job_id,     │
│    discarded_reason                                                                   │
│                                                                                       │
│    budgets.json:  {estimate, stop_loss, spent, approved, budget_hash}               │
│    proposals.jsonl: updated status ("used", "void", "needs_reapproval")              │
│    jobs.sqlite: job row with final state, cost, result                               │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Where to Add Things

### Add a Provider / Adapter
1. Create `aistudio/providers/adapters/<name>.py` subclassing `Adapter` (from `base.py`)
2. Implement required capabilities: `chat`, `vision`, `image`, `video` methods
3. Register in `aistudio/providers/config.py` → `PROVIDER_TYPES` dict:
   ```python
   "my_provider": {
       "label": "My Provider",
       "sub": "Description",
       "adapter": "my_provider.MyProviderAdapter",
       "fields": ["api_key"],      # or ["access_key", "secret_key"]
       "base_url": False,
   }
   ```
4. Add tests in `tests/test_adapter_<name>.py` (use fake transport)

### Add a Recipe
1. Create `catalog/recipes/<id>.json` with:
   ```json
   {
     "id": "my-recipe",
     "label": "My Recipe",
     "category": "ads",
     "description": "...",
     "consent": "none",           // or "if-real-person" or "required"
     "format": "instagram-reel",  // optional
     "inputs": [...],             // image, text, choice, number, audio
     "steps": [...],              // each with task, optional source, prompt, etc.
     "requires": []               // task names that must be available
   }
   ```
2. Run `python -m aistudio.recipes` to validate (loads all recipes)

### Add an Agent
1. Create `catalog/agents/<id>.md` with frontmatter:
   ```markdown
   ---
   id: my-agent
   name: My Agent
   version: 1
   role: director
   tools: ["get_project", "read_doc", "propose", "update_shots", ...]
   engine: builtin
   limits: {max_steps: 12, max_tokens: 20000, max_llm_usd: 0.25}
   ---
   # Prompt body (markdown)
   ```
2. Only tools from `tool_registry.crew_tools()` (free + paid classes) allowed
3. Override prompt/limits in `settings/agents.json` (tools cannot be changed)

### Add a Tool (MCP + HTTP + Crew)
1. Add entry to `TOOLS` dict in `aistudio/tool_registry.py`:
   ```python
   "my_tool": ("One-line purpose.", S(param=STR), lambda ws, a: ws.my_method(...))
   ```
2. Classify in `FREE_READ`, `FREE_WRITE`, `PAID`, `APPROVAL`, or `HUMAN_ONLY`
3. If `PAID`: it creates a proposal; human must approve via `approve_proposal`/`run_proposal`
4. If `APPROVAL` or `HUMAN_ONLY`: never available to crew agents
5. Add HTTP route in `server/api_docs.py` (with `agent=True/False` for API key access)
6. Implement handler in `aistudio/service.py` (Service class)

### Add a Domain Module
1. Create `aistudio/domain/<name>.py` with a Domain class
2. Register in `aistudio/service.py` Service.__init__
3. Expose via Service methods and/or MCP tools

## Key Data Files (per project)

| File | Purpose |
|------|---------|
| `brief.md` | User answers: brand, goal, story, audience, platform, length, language, characters, setting, budget_cap |
| `Story.md` | Shared style, characters, backgrounds, shots (human-editable) |
| `shots.json` | Shot list: id, prompt, seconds, direction, audio, model, first_frame, recipe |
| `images.json` | Asset list: id, kind, out, refs, aspect_ratio, prompt, model, recipe, real_person |
| `budget.json` | estimate, stop_loss, spent, approved, budget_hash |
| `proposals.jsonl` | Append-only: every proposal with status, code, request_hash |
| `cost_log.csv` | Every paid action: provider, model, price, exact/estimated, job_id |
| `consent.json` | subject, statement, date, kind, asset_sha |
| `edit.json` | Timeline: video/audio/text/elements tracks, transitions |
| `checks/<id>.json` | Vision drift check results (character consistency scores) |
| `jobs.sqlite` | Durable job ledger (survives restart) |
| `batches/` | Batch plans (awaiting_approval → running → done/needs_reapproval) |

## Security Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                        HUMAN SESSION                            │
│  • Full HTTP API access (session token in cookie/header)       │
│  • Can approve budgets, proposals, batches, clips              │
│  • Can manage providers, keys, limits, recipes, crew           │
│  • Can upload images, delete projects, export/import           │
│  • Can record consent, mark real_person                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ MCP / API Key
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT / SCRIPT                             │
│  • Free read/write tools                                       │
│  • Paid tools: create proposals only                           │
│  • CANNOT: approve_budget, approve_proposal, approve_batch,    │
│    approve_shot, run_proposal (pending), run_batch,            │
│    set_max_attempts, discard, restore,                         │
│    create_project, delete_project, list_projects,              │
│    list_trash, restore_trash, upload_image,                    │
│    list_jobs, get_job, list_crew_runs, get_crew_run,           │
│    search_library, plan_recipe                                 │
│  • Provider keys: write-only (header), never readable          │
│  • Consent: read-only, cannot create/modify                    │
└─────────────────────────────────────────────────────────────────┘
```

## Request Flow (Clip Generation)

```
User clicks "Generate" on shot s01
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ HTTP: POST /api/projects/{name}/clips/s01/generate           │
│      (or MCP: propose + approve_proposal + run_proposal)     │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Service.propose()                                            │
│   ──► spec.resolve(video, s01) ──► {model, price, caps}     │
│   ──► gates.check_budget(price) ──► under stop-loss?         │
│   ──► gates.check_attempts(s01) ──► < 3 attempts?            │
│   ──► Create proposal (pending) with request_hash            │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
Human approves via UI (elicitation) or CLI (fallback code)
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Service.execute(proposal_id)                                 │
│   ──► gates.can_run(proposal) ──► re-check everything        │
│   ──► jobs.create(kind="clip", target="s01", ...)            │
│   ──► adapter.video_submit(prompt, first_frame, seconds)     │
│   ──► On done: costlog.append(..., exact=true)               │
│   ──► Update shots.json: clip path, version, cost            │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
Cost log updated, budget.spent increased, proposal.status = "used"
```

## Concurrency & Durability

- **Job ledger** (`jobs.sqlite`): survives server restart. Jobs in `provider_pending` state are synced on startup via `POST /api/projects/{name}/sync`.
- **Proposals** (`proposals.jsonl`): append-only; status transitions: `pending → approved → used|rejected|expired|void|needs_reapproval`.
- **Cost log** (`cost_log.csv`): append-only; `discarded_reason` column for discarded items.
- **Document history** (`history/`): every `write_doc`, `update_shots`, `update_images`, `update_edit` creates a versioned backup (git-like per file).
- **Locks**: per-project file lock (`.lock`) for writes; `batches/` and `jobs/` use atomic write + rename.

## Testing Boundaries

- **No network, no money**: All tests use `fake` provider and `test_pipeline=True` projects.
- **Unit tests**: `tests/test_*.py` for each domain/module.
- **E2E tests**: `web/e2e/*.mjs` (Playwright) for UI flows.
- **Run targeted**: `./.venv/bin/python -m unittest tests/test_service.py tests/test_service_more.py`
- **TypeScript**: `cd web && npx tsc --noEmit`