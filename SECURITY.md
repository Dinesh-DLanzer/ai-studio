# Security

AI Studio runs **on your own machine** and calls paid AI APIs with **your own key**.

## Model
- Server binds to `127.0.0.1` only; every API call needs the session token printed at start-up; unknown `Host`/`Origin` headers are rejected; files are served only from a project's `stills/`, `clips/`, `checks/`, `audio/` and `exports/` with an extension allow-list and path-traversal checks. Only `/api/health` and the bundled fonts are reachable without a token, and they hold nothing private.
- Your API keys are **write-only**: saved from Settings into the OS keychain (or `~/.aistudio/secrets.json`, mode 0600, outside the repo and every project). They are never read from a `.env` file or the environment. The API only ever returns whether a key is set and its last 4 characters. Keys are never sent to the browser after saving, logged, put in error messages (they are scrubbed), written into project files or exports, or readable through MCP. The key-saving endpoints accept the session token only in a header, never in a URL.
- **Fallback never raises a price silently.** A fallback image/video model is only used automatically when its price is known and not higher than the price a human approved; otherwise the action stops and asks again. A video job that was accepted and then failed is not resubmitted to another model.
- **Paid actions need a human.** Every image, clip, edit, extension, character analysis or review is a *proposal* bound to the exact request (prompt, model, price, input files). It runs only after a human approves that proposal, once. MCP approval tools do not trust `confirm=true`: clients with elicitation receive an `elicitation/create` form; other clients receive a one-time fallback challenge whose code is shown only in the local web notification and `aistudio serve` stderr.
- **API keys (agents and scripts).** Created in Settings > Integrations, shown once, stored only as a SHA-256 hash in `settings/api_keys.json` (mode 0600), revocable at once. A key is an *agent* key: the server lets it call only the routes for reading/writing project documents, estimating, proposing, proposal-only edit/extend/character analysis, and executing a proposal that a human already approved. Budget approval, proposal approval/rejection, clip approval, providers and their keys, limits, prices, other API keys, deleting, exporting and importing projects all need the page's session token (403 for a key). An unapproved execute request fails at the server gate and creates no cost row. A proposal made with a key does not include its approval code. Keys and provider secrets are accepted in a header only, never in a URL.
- **Real people and cloned voices need recorded consent.** `consent.json` (subject, statement, date, kind) is written only through a human-session route; API keys, MCP and the crew have no way to write it. An asset marked `real_person` (uploads included) is refused for generation, as a subject or as a reference, until a matching entry exists, checked again at execute. Consent records in an imported zip are dropped. Honest limit: the `real_person` mark is a declaration made by whoever adds the asset; AI Studio does not recognise faces.
- **Importing a project zip** is validated before anything is installed: safe relative paths only, no links, an allow-list of file types whose contents must match their names, valid project files, size and compression-ratio limits, and approvals plus the budget approval inside the zip are reset so a zip cannot approve spending on your machine.
- **The chat AI (Tara) cannot act.** It can only talk and propose text; it is told the project's real state each turn and its answers are parsed as data, never executed.
- Nothing is deleted: discard moves files to `_discarded/`, and deleting a project moves it to the trash folder.
- There is no app-wide mode. A project is a test project (no network, no cost) or a real one; real projects need a provider and every paid action needs your approval.
- Recipes (one-click tools, `catalog/recipes/*.json`) are data, not code: inputs are validated and only ever substituted as plain text, never evaluated. Planning a recipe creates one awaiting-approval batch; only a human approves its exact total and starts it, and every item is re-checked (model, price, request, input bytes, consent) when it runs. A recipe never approves or spends by itself, and the studio crew, chat and API keys cannot plan, approve or run one.
- Recipes cannot target or impersonate public figures or anyone else. No typed name is ever used as a face or voice target: a person appears only through a photo that a human registered as a real person with that person's recorded consent (a `required` recipe is refused without it, at plan time and again at run time), and free text never steers image or video generation in those recipes. Do not use a recipe for anyone who has not agreed.

## Human-only approvals + elicitation + fallback code lock
- All budget approvals (`estimate`/`approve_budget`), proposal approvals (`approve_proposal`), batch approvals (`approve_batch`), and clip approvals (`approve_shot`) are human-only. Agents cannot call these tools—they are classified as `approval` or `human_only` in the tool registry and are hard-excluded from crew agents.
- MCP clients that advertise form elicitation receive an `elicitation/create` dialog showing the exact request, model, and price. The human must check the approval box and accept.
- Clients without elicitation receive a one-time HMAC-derived challenge code. The code is computed from the challenge ID using an external keychain secret (OS keychain or `~/.aistudio/secrets.json`). The code is shown **only** in the local web notification and `aistudio serve` stderr. It is never returned in the MCP response, never stored in project files, and never logged. The agent must pass the code and its ID back only after the human has read it.
- `confirm=true` is explicitly rejected by all approval endpoints. No boolean supplied by an agent is ever accepted as approval.

## Spend locks/reservations
- Every proposal reserves its exact price against the approved budget ceiling.
- The stop-loss is 130% of the approved budget; the engine refuses to start any job that would push projected spend over this limit.
- A batch approval is bound to the exact `batch_hash` and total price. When the batch runs, each item is re-checked: if the model, price, or request hash has changed, that item stops at `needs_reapproval` and the batch pauses.
- Max 3 final attempts per shot (first + 2 retries) is enforced by the engine; an override requires a deliberate human action via `set_max_attempts` (human-only tool).

## Consent (real_person flag limits, sha-bound consent)
- An asset marked `real_person` (set by a human via the upload or consent-mark route) cannot be used as a generation subject or reference until a matching consent record exists in `consent.json`.
- Consent records contain: subject name, statement, date, kind (`real_person` or `voice`), and the asset file SHA at the time of consent.
- Consent is bound to the exact file bytes (SHA). If the asset file is replaced or edited, the SHA changes and the existing consent no longer applies—consent must be re-recorded.
- API keys, MCP tools, and crew agents **cannot** create or modify consent records; only human-session HTTP routes can.
- A recipe with `consent: "required"` is refused at plan time and again at run time unless at least one input asset is marked `real_person` and has a valid, SHA-matching consent record.

## Crew limits
- Crew agents (from `aistudio/crew/`) can only be given tools of cost class `free` or `paid`. Tools of class `approval` or `human_only` are **never** available to crew agents, regardless of agent definition, override file, or the `agents` field in the tool registry.
- Each agent has hard limits enforced at the engine level: `max_steps` (default 12, hard cap 50), `max_tokens` (default 20,000, hard cap 200,000), `max_llm_usd` (default $0.25, hard cap $5.00). Settings overrides are clamped to these caps.
- Agents never approve budgets, proposals, batches, or clips. They never execute unapproved proposals. They never see or handle approval codes (fallback codes or elicitation responses).
- A crew run is a ledger job; its steps, tool calls, token usage, and LLM cost are logged. Undo restores documents to pre-run versions.

## Recipes safety
- Recipes (`catalog/recipes/*.json`) are declarative data files, not code. They are strictly validated on load (schema, unknown keys, placeholder references, consent requirements).
- Inputs are validated (type, range, options, file existence inside project, suffix allow-list) and then **only ever substituted as plain text** in a single pass. A substituted value is never scanned again for placeholders.
- Planning a recipe creates exactly **one** awaiting-approval batch containing all paid steps at their exact current prices. Nothing is approved, run, or spent during planning.
- Only a human can approve the batch (at its exact total, bound to its `batch_hash`) and start it. Every item is re-checked at run time (model, price, request hash, input file SHA, consent).
- Recipes using tasks that involve real people (`face_swap`, `headshot`, `outfit_swap`, `lipsync`, `character_swap`, `motion_transfer`, `voice_clone`, `tts_clone`) must declare `consent: "required"` and are refused without a valid consent record.
- Free text inputs never steer image or video generation in recipes with `consent: "required"`.

## API keys header-only
- API keys (for agents/scripts) and provider secrets are accepted **only** in the `x-aistudio-token` header (for keys) or in the request body with the session token in a header (for provider secrets). They are never accepted in URLs, query parameters, or cookies.
- Provider secret-saving endpoints (`PUT /api/providers/{pid}/secret`, `POST /api/providers`) require the session token in a header, never in the URL.

## Library human-only
- The workspace library search (`search_library` MCP tool, `/api/library*` HTTP routes) is human-session only because it can reveal data across projects. API keys and crew agents cannot access it.

## YouTube uploads (human-only, opt-in)
- The YouTube OAuth client ID and client secret, access token, refresh token, and token expiry are stored through `aistudio/secrets.py` under the `youtube` reference, using the OS keychain when available or the private 0600 `~/.aistudio/secrets.json` file otherwise. They are write-only from Settings and are never returned by the API.
- Upload requests can be started only from the human-session Publish page after preflight passes and the human confirms the saved title and reviews the exact export path, size, SHA-256, channel, metadata, and privacy.
- The POST request must carry the previewed SHA-256, title, and privacy setting, and refuses on any mismatch.
- Timeline and asset consent is strictly enforced: videos containing assets marked `real_person` or marked SHAs cannot be uploaded without recorded consent.
- API keys, MCP, crew, recipes, and batches cannot upload.

## Media provenance and clearance (fail closed)
- A file counts as **verified** only when the server can prove where it came from: pipeline output with a grant, an editor render, a local tool output, or a derived file whose every input is verified. Each such file carries a `.meta.json` lineage record signed with a server-held HMAC key (kept in the OS keychain or the 0600 secrets file, never in a project), so a hand-written, copied or edited record is worthless.
- Everything else is **unverified**: uploads, imports, files returned by external editors, and anything outside the known folders. Registering a file in `images.json` or `shots.json` does not make it verified. Unverified files cannot be used for consent-gated work (face and voice tasks, character swap, motion transfer, replace or restyle with a person, voice cloning, library promotion, YouTube upload) until a **human** clears the exact file bytes in the page ("Clear for use": not a real person, or a recorded consent bound to that file).
- An editor render inherits the real-person mark from any input clip, and is verified only when every input is. A re-encoded or cropped copy made outside the app has new bytes and no lineage, so it is unverified. Zip import discards imported lineage and consent files.
- Clearance and consent routes are human-session only. API keys, device tokens, MCP, crew and recipes cannot create them, and `confirm=true` is never accepted.

## Paired devices
- A paired device (for example an editor panel) gets a revocable `aisd_` token from a short human-confirmed pairing code. It can read project media and create proposals, but it cannot approve, spend, change settings, record consent or upload. Tokens are accepted only in a header, never in a URL, and are stored hashed.

## Hosted mode (foundation only, not a supported deployment)
- With `AISTUDIO_HOSTED` set, project folders, locks, spend reservations, approvals and trash live under `<root>/tenants/<tenant_id>/`, tenant ids are validated (no separators, `..` or symlinks), and the request context fails closed when no tenant is set. The local single-user layout is unchanged. Hosted authentication, organisation management and Postgres are **not implemented**; do not expose a hosted deployment to the internet. See `docs/adr-hosted-multitenant.md`.

## Known limits
- This is a single-user local tool. A hostile process running as you on the same machine can read project metadata and the external local state. The fallback HMAC secret is kept in the OS keychain when available (or the 0600 external secrets file); challenge codes are never stored in a project. The approval design stops accidents and agent self-approval, not a malicious local user.
- Do not expose the server to a network. If you change the bind address, add real authentication first.
- Live grant capabilities are intentionally kept in memory and fail closed after a server restart; the consumed approval cannot be replayed.
- AI clips can contain unwanted people, garbled text, or logos: always review frames and listen to audio yourself. The vision check is advisory.
- Face/voice recognition is not performed; the `real_person` flag and clearances are human declarations only.
- Provider adapters are tested against recorded fixtures, not live accounts, except where stated. Check a new provider with one cheap request first.
- Provider prices and model availability change; verify before large runs.
- The vision check cannot hear audio or understand all languages; it is a second pair of eyes, not a judge.

## Reporting
Open a private security advisory on the repository, or email the maintainers. Please do not post keys or exploit details in public issues.
