# Security

AI Studio runs **on your own machine** and calls paid AI APIs with **your own key**.

## Model
- Server binds to `127.0.0.1` only; every API call needs the session token printed at start-up; unknown `Host`/`Origin` headers are rejected; files are served only from a project's `stills/`, `clips/`, `checks/`, `audio/` and `exports/` with an extension allow-list and path-traversal checks. Only `/api/health` and the bundled fonts are reachable without a token, and they hold nothing private.
- Your API keys are **write-only**: saved from Settings into the OS keychain (or `~/.aistudio/secrets.json`, mode 0600, outside the repo and every project). They are never read from a `.env` file or the environment. The API only ever returns whether a key is set and its last 4 characters. Keys are never sent to the browser after saving, logged, put in error messages (they are scrubbed), written into project files or exports, or readable through MCP. The key-saving endpoints accept the session token only in a header, never in a URL.
- **Fallback never raises a price silently.** A fallback image/video model is only used automatically when its price is known and not higher than the price a human approved; otherwise the action stops and asks again. A video job that was accepted and then failed is not resubmitted to another model.
- **Paid actions need a human.** Every image, clip or review is a *proposal* bound to the exact request (prompt, model, price, input images). It runs only after a human approves that proposal, once. The MCP server exposes no approval tools.
- **API keys (agents and scripts).** Created in Settings > Integrations, shown once, stored only as a SHA-256 hash in `settings/api_keys.json` (mode 0600), revocable at once. A key is an *agent* key: the server lets it call only the routes the MCP tools can reach (read, write the story and brief, estimate, propose, run what a human already approved). Approving a budget, a proposal or a clip, providers and their keys, limits, prices, other API keys, deleting, exporting and importing projects all need the page's session token (403 for a key). A proposal made with a key does not include its approval code. Keys and provider secrets are accepted in a header only, never in a URL.
- **Importing a project zip** is validated before anything is installed: safe relative paths only, no links, an allow-list of file types whose contents must match their names, valid project files, size and compression-ratio limits, and approvals plus the budget approval inside the zip are reset so a zip cannot approve spending on your machine.
- **The chat AI (Tara) cannot act.** It can only talk and propose text; it is told the project's real state each turn and its answers are parsed as data, never executed.
- Nothing is deleted: discard moves files to `_discarded/`, and deleting a project moves it to the trash folder.
- There is no app-wide mode. A project is a test project (no network, no cost) or a real one; real projects need a provider and every paid action needs your approval.

## Limits (be honest)
- This is a single-user local tool. A hostile process running as you on the same machine can read `proposals.json` and the key file. The approval design stops accidents and agent self-approval, not a malicious local user.
- Do not expose the server to a network. If you change the bind address, add real authentication first.
- AI clips can contain unwanted people, garbled text, or logos: always review frames and listen to audio yourself. The vision check is advisory.

## Reporting
Open a private security advisory on the repository, or email the maintainers. Please do not post keys or exploit details in public issues.
