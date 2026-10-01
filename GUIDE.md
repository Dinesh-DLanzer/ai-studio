# AI Studio user guide

The same material is in the app under **Help & Documentation** (with the live API reference). This file is the printable version.

## Part A. One-time setup (about 15 minutes)
1. Start the app: `./scripts/start.sh` (macOS/Linux) or `scripts\start.bat` (Windows). Open the link it prints; it carries your session token.
2. Choose **Set up a provider** (or **Try a test project** first, to learn the app for free).
3. **Settings > AI Providers > Add Provider.** Pick OpenRouter, Google, OpenAI, Anthropic, Runway, Kling, Replicate or a custom OpenAI-compatible server and paste its API key. Create the key with a spending limit on the provider's site. Press **Test**.
4. **Settings > Model Configuration.** Give **Chat** at least one model (free models work for chat). Choose **Image** and **Video** models and set a price on any model that has none. Add a model by id if it is not listed.
5. **Try one cheap clip** (about $0.40 with a 4 s clip) in a throwaway real project, then compare the project's Costs page with your provider's activity page. Failed or rejected jobs may or may not be billed: write down what your provider does.
6. Install `ffmpeg` (`brew install ffmpeg`) so Review & Export can render videos.

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

**The Chat page (Tara, the producer).** Tara interviews you and writes Story.md. Press the image button to attach a logo or photo: it is saved in Uploads, shown in the chat, and its main colours are read so the story's *Shared style* can use your brand colours. Tara never generates anything herself and is told the project's real state each turn (budget approved or not, which images and clips exist). Under the messages, the **Production checklist** shows the fixed order and one Next button: storyboard, budget, characters, backgrounds, scene frames, video clips, approve, Review & Export. **Generate all** lists every remaining image and clip with its exact price and total; you approve once and the items run one after the other (each still goes through propose, approve and run, within the budget and stop-loss, and the run stops at the first problem). While anything is being made, the generate buttons are disabled and show a loader. A single **Generate** opens the usual price approval, and the server refuses a scene frame before its characters and places, and a clip before its scene frame.

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
