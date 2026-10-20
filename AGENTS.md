# AI Studio Agent Operational Guidelines (`AGENTS.md`)

This repository is optimized for high-speed, token-efficient AI agent collaboration. Every AI agent working on this codebase MUST adhere to these rules:

---

## 1. Targeted Scoping (Do Not Scan the Entire Repo)
* **Never perform repository-wide regex or AST scans** (e.g. Graphify dumps, `graphify-out/`, `projects/`, `node_modules/`).
* **Work in domain slices:**
  - Projects / Filesystem / Trash: `aistudio/domain/projects.py`
  - Chat streaming / execution: `aistudio/domain/chat.py`
  - Storyboard / Shots / Stills: `aistudio/domain/storyboard.py`
  - Todo & Document sync: `aistudio/domain/todos.py`
  - Pipeline / Batch generation: `aistudio/domain/pipeline.py`
  - Character consistency & vision: `aistudio/domain/characters.py`
  - Costs, rates & pricing: `aistudio/domain/costs.py`
  - Facade API: `aistudio/service.py`
  - Server endpoints: `server/app.py`
  - Frontend components: `web/src/pages/`
* Only view the specific file you need to modify. Do NOT read large unrelated files into context.

---

## 2. No Autonomous Full Builds or Unbounded Loops
* **NEVER execute `npm run build`** unless the user explicitly requests a production build verification. The dev server (`./start` / Vite) runs HMR automatically.
* **NEVER run full repository test suites** on minor edits.
* Avoid spinning on exploratory curl / browser automation loops. Limit investigative turns to 1–2 calls.

---

## 3. Verification by Slice
* Verify Python backend changes using targeted unit tests:
  ```bash
  ./.venv/bin/python -m unittest tests/test_service.py tests/test_service_more.py
  ```
* For specific domain changes, test only the affected test module (e.g., `tests/test_character_check.py`, `tests/test_chat.py`, `tests/test_flow.py`).

---

## 4. Plans Workflow
* Respect the `plans/` lifecycle defined in [plans/readme.md](file:///Users/dinesh/DLanzer/AI%20Studio/plans/readme.md):
  - `plans/not-started/`: Pending implementation
  - `plans/on-processing/`: Currently active tasks
  - `plans/completed/`: Finished and verified tasks
  - `plans/discarded/`: Obsolete or rejected plans
* Update plan checklists as tasks progress.

---

## 5. Approval and spend safety
* Agents and Tara may inspect, edit documents, estimate, and create paid proposals, but they never approve budgets or proposals and never execute an unapproved proposal.
* Paid runner calls require a one-use grant issued by consuming the exact human-approved proposal. Never hand-build or reuse a grant.
* MCP approval uses `elicitation/create` when the client advertises form elicitation. Otherwise the one-time fallback code is shown only in the local human web notification and `aistudio serve` stderr; it is HMAC-derived from the challenge id and an external keychain secret and is never stored in a project.
* Use only fake/test providers and test projects during agent work. Never call a paid provider or approve a real proposal.

## 6. Conversational Session Hygiene
* Keep agent turn counts low (<15 turns per task).
* If a task exceeds 20 turns or the context fills with long outputs, advise the user to start a fresh chat session.
