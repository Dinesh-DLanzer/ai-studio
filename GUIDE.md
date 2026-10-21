# AI Studio user guide

The same material is in the app under **Help & Documentation** (with the live API reference). This file is the printable version.

## Part A. One-time setup (about 15 minutes)

1. Start the app: `./start` (or `.\start.bat` on Windows). Prerequisites like Python, Node.js, and FFmpeg are automatically checked and installed if missing. Open the link it prints; it carries your session token.
2. Choose **Set up a provider** (or **Try a test project** first, to learn the app for free).
3. **Settings > AI Providers > Add Provider.** Pick OpenRouter, OpenCode, OpenAI, Anthropic, Google, Runway, Kling, Replicate, ComfyUI, ChatGPT (subscription), Codex CLI, OpenCode CLI, Claude Code CLI, Antigravity CLI, ElevenLabs, Hedra, HeyGen, Tavus, Google Cloud TTS, Azure Speech, Sarvam AI, Stability AI, Cartesia, fal.ai, whisper.cpp (local), sync.so, or a custom OpenAI-compatible server and paste its API key. Create the key with a spending limit on the provider's site. Press **Test**.
4. **Settings > Model Configuration.** Give **Chat** at least one model (free models work for chat). Choose **Image** and **Video** models and set a price on any model that has none. Add a model by id if it is not listed.
5. **Try one cheap clip** (about $0.40 with a 4 s clip) in a throwaway real project, then compare the project's Costs page with your provider's activity page. Failed or rejected jobs may or may not be billed: write down what your provider does.

## Part B. Making a video (repeat per video)

| Step | Do this | Gate |
|---|---|---|
| 1 Brief | Create a project and answer Tara in **Chat** (idea, goal, length, voice language, who appears, places, logo, brand colours, budget cap). Attach a logo with the image button. | Required answers filled |
| 2 Storyboard | Tara writes Story.md; read it on the **Storyboard** page, change anything, apply it. | You approve the story |
| 3 Budget | Check the estimate and **approve** it (a ceiling, not a spend). | Within your budget |
| 4 Characters and places | Generate or upload a master image for each. Look at every image. | Faces and places look right |
| 5 Scene frames | Generate or upload the first frame of every shot (they use the masters as references). | Frames match the shots |
| 6 Clips | Generate one clip per shot (**Generate**, or **Generate all** for the rest). Watch and listen. Max 3 final attempts per shot. | Stop-loss at 130% is enforced |
| 7 Approve | **Approve** good clips, **Discard** bad ones with a reason. | Motion and speech are right |
| 8 Review & Export | Trim, add transitions, text, music; **Export Video**. Add the platform's AI label when you publish. | QA checklist |
| 9 Costs | Check used versus discarded spend; note your real failure rate for the next estimate. | |

### Recipes (one-click tools)

Recipes are declarative data files in `catalog/recipes/*.json`. Available recipes:
- **product-ad-9x16**: Product ad for vertical video
- **product-showcase-360**: 360° product showcase
- **explainer-from-script**: Explainer video from a script
- **talking-head-ad**: Talking head advertisement
- **face-swap**: Face swap on a video
- **photo-to-cinematic-clip**: Turn a photo into a cinematic clip
- **product-placement**: Product placement in a scene
- **upscale-and-reframe-pack**: Upscale and reframe a clip pack
- **headshot**: Professional headshot generation
- **outfit-swap**: Outfit swap on a character

To use a recipe: **Chat > Recipes**, pick one, fill the inputs, and it creates one awaiting-approval batch. You approve the exact total and start it. Every step is re-checked (model, price, request, input bytes, consent) when it runs. A recipe never approves or spends by itself.

**The Chat page (Tara, the producer).** Tara interviews you and writes Story.md. Press the image button to attach a logo or photo: it is saved in Uploads, shown in the chat, and its main colours are read so the story's *Shared style* can use your brand colours. Tara never generates or approves anything herself and is told the project's real state each turn (budget approved or not, which images and clips exist). When Tara suggests generation, the chat shows an **Action ready for review** card; its button opens the normal human budget/proposal dialog. Under the messages, the **Production checklist** shows the fixed order and one Next button: storyboard, budget, characters, backgrounds, scene frames, video clips, approve, Review & Export. **Generate all** lists every remaining image and clip with its exact price and total; you approve once and the items run one after the other (each still goes through propose, approve and run, within the budget and stop-loss, and the run stops at the first problem). While anything is being made, the generate buttons are disabled and show a loader. A single **Generate** opens the usual price approval, and the server refuses a scene frame before its characters and places, and a clip before its scene frame.

**Review & Export (free).** The clips of your shots are already on the Video track. Drag a clip to reorder it, drag its edges to trim, press `S` (or the scissors) to split at the playhead. Pick a transition for a clip in the right panel (or in Transitions). Add text from Text and drag it in the preview; add music from Audio. Press Export Video; the MP4 appears in `projects/<name>/exports/`. Shortcuts: Space play, S split, Delete remove, Ctrl/Cmd+Z undo, arrows move the playhead. The preview shows hard cuts (the export has the transitions); italic uses a real italic font only for Poppins Regular and Bold.

**Projects.** The 3-dot menu on a card (or the sidebar project menu) has Add to favorites, Export project (zip) and Delete project. **Import project (zip)** checks every file and refuses the whole zip, with reasons, if anything is wrong; approvals inside a zip are reset. Delete asks you to type the project name and moves the folder to `_trash/`; restore it from the **Archived** tab. Nothing is erased.

**Test or real?** A project is a test project if you switched on *Test project* when creating it, or if it holds only placeholders. Test projects simulate images, clips and reviews and cost nothing. A project with real generated media or real costs is always real.

## What the app enforces for you

- No generation without an approved budget.
- Every paid action shows its exact price and needs your approval; a change to the prompt, model, price or input image voids it.
- Max 3 final attempts per shot (first + 2 retries); an override is deliberate.
- Refuses to run once spend plus the next job would pass 130% of the estimate.
- A scene frame needs its characters and places; a clip needs its scene frame.
- A job that times out or is interrupted is logged at its planned cost. **Sync** fetches the real cost and the clip if it finished.
- Every job is logged to `projects/<name>/cost_log.csv` (provider, and whether the price was exact or estimated). Reconcile with your provider's activity page.
- Paid text models (chat, verify) are refused unless you allow them in Settings, and then stop at the per-project AI spending cap.
- Agents cannot approve through the HTTP API. MCP uses `elicitation/create` when supported; without it, the one-time fallback code is HMAC-derived from the challenge id using an external keychain secret, shown only in the local web notification and terminal stderr, and never stored in a project.
- **Human-only approvals:** Budget approval, proposal approval, batch approval, clip approval, and attempt limit changes are human-only. MCP elicitation is used when the client advertises it; otherwise a one-time HMAC-derived code is shown only in the local web notification and `aistudio serve` stderr. The code is never in the MCP response or project files. `confirm=true` is always rejected.
- **Spend locks/reservations:** Every proposal reserves its exact price against the approved budget. The stop-loss is 130% of the approved budget. A batch approval is bound to the exact batch_hash and total; if any item's model, price, or request changes, it stops at `needs_reapproval`.
- **Consent (real_person flag, sha-bound):** An asset marked `real_person` (by human upload decision) requires a recorded consent (subject, statement, date, kind=real_person\|voice) before any generation can use it. Consent is bound to the exact file SHA; if the asset's file changes, consent must be re-recorded. API keys, MCP, and crew cannot record consent—only human sessions can.
- **Crew limits:** Crew agents can only use free and paid tools (never approval or human_only tools). Their steps are capped at max_steps (default 12, hard cap 50), max_tokens (default 20k, hard cap 200k), max_llm_usd (default $0.25, hard cap $5). Agents never approve, never execute unapproved proposals, and never see or handle approval codes.
- **Recipes safety:** Recipes are data, not code. Inputs are validated and only ever substituted as plain text (single pass, never re-scanned). Planning creates one awaiting-approval batch; only a human approves the exact total and starts it. Every item is re-checked at run time. Recipes cannot target public figures; real-person recipes require `consent: "required"` and a human-marked real_person asset with recorded consent.
- **API keys header-only:** API keys and provider secrets are accepted only in the `x-aistudio-token` header, never in URLs.
- **Library human-only:** The workspace library search (`search_library` tool, `/api/library` routes) is human-session only because it can reveal data across projects.
- **No uploads/publishing:** The app never uploads media to any external service. Publishing exports are local renders packaged for delivery presets (YouTube, TikTok, etc.); no API calls are made to upload or post.

## Prompt template (one action, one camera move)

`SUBJECT: ... ACTION: ... CAMERA: ... LIGHTING: ... STYLE: ... NEGATIVE: no on-screen text, no logos, no close-up hands`

## Tips

- Keep `audio` false in `shots.json` unless a shot has speech; add music in the editor.
- Mix models: hero shots on a premium model, B-roll on a cheaper one (set `model` per shot).
- If a model rejects a duration or resolution the app tells you before spending.
- Never share your key file (`~/.aistudio`) or your session token.

## Appendix: the original command-line tool

`vidad.py` is the first, one-file version. It still works and uses the OpenRouter key you saved in the app. Handy for scripting; the app is easier.

```
python3 vidad.py models                                   # video models with durations and resolutions (free)
python3 vidad.py new <name>                               # make a project from the templates
python3 vidad.py estimate <name> --failure 0.2            # budget (writes budget.json), then:  approve <name> budget
python3 vidad.py image <name> <id> --dry-run              # one still from images.json (about $0.04 without --dry-run)
python3 vidad.py run <name> s01 --stage final --dry-run   # exact cost first; drop --dry-run to run
python3 vidad.py check <name> s01                         # frames across the whole clip
python3 vidad.py approve <name> s01 final                 # keep it
python3 vidad.py sync <name>                              # resolve timed-out jobs
python3 vidad.py costs <name>                             # used vs discarded
```

## Known limits

- Single-user, local-only. No multi-user, no hosted deployment.
- Vision check is advisory only; it cannot hear audio or understand all languages.
- Provider prices and model availability change; verify before large runs.
- Face/voice recognition is not performed; `real_person` flag is a human declaration only.
- The fallback HMAC secret is in the OS keychain (or `~/.aistudio/secrets.json`); a malicious local process could read it.
- Do not expose the server to a network without adding real authentication first.