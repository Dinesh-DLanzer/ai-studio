import type { ReactNode } from "react";

/** All the prose of the Help page. Each fact is stated once, in the place where a reader would look for it. */

export const BENEFITS: { title: string; text: string }[] = [
  { title: "One place, idea to MP4", text: "Interview, storyboard, character sheets, clips, a timeline editor and the final export live in one app. No file shuffling between five tools." },
  { title: "Characters that stay the same", text: "Every character and place gets a master image first, and a shared style is added to every prompt, so shot 9 still looks like shot 1." },
  { title: "You decide every cent", text: "Every paid action shows its exact price and waits for your approval. A budget ceiling and a stop-loss stop runaway spending." },
  { title: "Practice for free", text: "A test project runs the whole workflow with placeholders, so you can learn it, or demo it, at no cost and with no key." },
  { title: "Nothing is lost", text: "Replaced and rejected files move to Discarded and can be restored. Deleted projects are archived. Your files are plain files you can open anywhere." },
  { title: "Works with your agents", text: "Claude Code, OpenCode or your own scripts can drive the story and propose work through MCP or the HTTP API. They can never approve spending." },
];

export const SETUP: { title: string; text: ReactNode }[] = [
  { title: "Install the three things it needs", text: <>Python 3.10 or newer, Node 18 or newer (only once, to build the screens) and <b>ffmpeg</b> (needed to export videos; on macOS run <code>brew install ffmpeg</code>).</> },
  { title: "Start it", text: <>Run <code>./scripts/start.sh</code> (macOS/Linux) or double-click <code>scripts\start.bat</code> (Windows). It prints a link like <code>http://127.0.0.1:8765/?token=...</code>. Open that link: the token is your session key, so keep it private.</> },
  { title: "Pick how to begin", text: <>With no provider connected you are asked: <b>Set up a provider</b> to make real videos, or <b>Try a test project</b> to explore for free. You can connect a provider later from the banner or Settings.</> },
  { title: "Connect a provider and choose models", text: <>Add OpenRouter, Google, OpenAI, Anthropic, Runway, Kling, Replicate or any OpenAI-compatible server with its API key. Then give <b>Chat</b> at least one model (required), and choose <b>Image</b> and <b>Video</b> models before you generate. Keys are write-only and stored in your OS keychain or a private file.</> },
  { title: "Create your first project", text: <>Press <b>Generate New Video</b> or use the form on the Projects page. Leave "Test project" off for a real one. You land in the chat with Tara, your producer.</> },
];

export const FLOW: { n: string; name: string; you: string; app: string }[] = [
  { n: "1", name: "Brief", you: "Answer Tara's questions: idea, goal, length, language, characters, places, logo and brand colours, budget cap.", app: "Fills brief.md and TODO.md as you talk. Says which required answers are still missing." },
  { n: "2", name: "Storyboard", you: "Read the drafted story, ask for changes.", app: "Writes Story.md: shared style, characters, backgrounds, and one block per shot. It becomes the shot list and the asset list." },
  { n: "3", name: "Budget", you: "Check the estimate and approve it once.", app: "Sets the ceiling and the stop-loss (130% of the estimate). Nothing can be generated before this." },
  { n: "4", name: "Characters and places", you: "Generate or upload a master image for each.", app: "These must exist before any scene frame that uses them." },
  { n: "5", name: "Scene frames", you: "Generate or upload the first frame of every shot.", app: "Each frame uses its characters and places as references." },
  { n: "6", name: "Clips", you: "Generate one clip per shot; watch and listen.", app: "A clip needs its scene frame. Up to 3 final attempts per shot." },
  { n: "7", name: "Approve", you: "Approve the good clips; discard the bad ones.", app: "Discarded clips are kept with their cost and reason." },
  { n: "8", name: "Review & Export", you: "Join, trim, add transitions, text and music; export.", app: "Renders one MP4 on your computer with ffmpeg. Free." },
];

export const KINDS: { row: string; test: string; real: string }[] = [
  { row: "Images, clips, reviews", test: "Simulated placeholders", real: "Made by your providers" },
  { row: "Cost", test: "Nothing", real: "Exact price shown, approved by you each time" },
  { row: "Chat", test: "Your chat model if one is connected, else a built-in scripted interviewer", real: "Your chat model (free models unless you allow paid)" },
  { row: "Needs a provider", test: "No", real: "Yes" },
  { row: "How it is decided", test: "The Test project switch, or a project whose files hold only placeholders", real: "Anything else. A project with real media or real costs is always real." },
];

export interface Guide { id: string; title: string; summary: string; body: ReactNode }
const Li = ({ children }: { children: ReactNode }) => <li>{children}</li>;

export const GUIDES: Guide[] = [
  {
    id: "producer", title: "Work with Tara, your producer (Chat)", summary: "How the interview, the logo upload and the checklist fit together.",
    body: (
      <>
        <ol className="list-decimal space-y-1.5 pl-5">
          <Li>Say hello or describe the video. Tara asks at most two short questions at a time and keeps the brief up to date.</Li>
          <Li>It also asks who appears, where it happens, whether you have a logo or product photo, and whether the video should use your brand colours. Answer <i>none</i> if nobody or nothing applies; the matching sections are then left out.</Li>
          <Li>Press the image button to attach a logo or photo. It is saved in Uploads, shown in the chat, and its main colours are read so the story's shared style can use them.</Li>
          <Li>When the brief is complete, Tara writes Story.md and your first budget prompt appears.</Li>
          <Li>Use the <b>Production checklist</b> under the messages: it shows each stage with counts and one <b>Next</b> button. <b>Generate</b> opens the normal price approval; <b>Generate all</b> lists every remaining image and clip with its price, you approve once, and they run in order.</Li>
        </ol>
        <p className="mt-3 text-slate-400">Tara cannot generate, approve or upload anything: Tara only talks, and is told the project's real state every turn. If it ever claims otherwise, trust the checklist. If it changes its mind about the plan, it re-sends the full story as a draft that you apply.</p>
      </>
    ),
  },
  {
    id: "story", title: "Write or edit Story.md", summary: "The exact format; what each part becomes.",
    body: (
      <>
        <p>Story.md is plain Markdown. Saving it rebuilds the shot list and the asset list, and your uploads stay.</p>
        <pre className="mt-2 overflow-x-auto rounded-xl border border-slate-800 bg-black/40 p-3 text-[0.75rem] leading-relaxed">{`# My Ad: AI VIDEO STORYBOARD
## Shared style                      -> added to EVERY image prompt
Warm teal and gold, soft evening light.
## Characters
### Ramesh                           -> one master image, id: ramesh
40s, white shirt, warm smile.
## Backgrounds
### Shop front                       -> one master image, id: shop_front
Busy saree shop at dusk.
## Shot 01 — 0:00–0:04               -> shot s01
### Purpose: HOOK
**Visual** ... **Camera** ... **Action** ...
**Voice** (ON-CAMERA)                (or OFF-CAMERA, or SILENT)
> One short sentence in the voice language.
**English**
> The meaning in English.
**Uses**: ramesh, shop_front, logo    -> the scene frame's references
**Image**: s01                       -> the scene frame (the clip's first frame)
**AI Video Prompt**
> SUBJECT / ACTION / CAMERA / LIGHTING / STYLE / NEGATIVE`}</pre>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-slate-300">
          <Li>One short spoken sentence per clip; clips are 4, 6 or 8 seconds. Voice lines are written in the language's own script plus an English meaning.</Li>
          <Li>On-screen text, logos and end cards are added later in the editor; they are never generated.</Li>
          <Li>Leave out Characters or Backgrounds when there are none. Ids are lowercase with underscores.</Li>
        </ul>
      </>
    ),
  },
  {
    id: "assets", title: "Assets: upload, generate, replace", summary: "Four categories, one fixed order, and how references work.",
    body: (
      <ul className="list-disc space-y-1.5 pl-5">
        <Li><b>Characters</b> and <b>Backgrounds</b> are master images. <b>Scene frames</b> are the first frame of each shot and reference the masters. <b>Uploads</b> are files you keep with the project (a logo, a product photo).</Li>
        <Li>Each asset can be uploaded (PNG, JPEG, WebP, GIF, BMP, TIFF, HEIC; converted automatically) or generated from its prompt. Edit the prompt and pick its references on the right.</Li>
        <Li>Replacing an image moves the old one to Discarded. Renaming an asset updates every reference, file and the cost log.</Li>
        <Li>Order is enforced by the server: a scene frame is refused until its characters and places exist, and a clip is refused until its scene frame exists.</Li>
        <Li>Images found in <code>stills/</code> that are not in the list are offered for import with a category guess.</Li>
      </ul>
    ),
  },
  {
    id: "shots", title: "Shots, clips and approval", summary: "Generate carefully, review, keep only what you like.",
    body: (
      <ul className="list-disc space-y-1.5 pl-5">
        <Li>Generate one clip at a time. Each shows its price first. Watch it and listen: check faces, hands, extra people, text and cut-offs.</Li>
        <Li><b>Re-check</b> extracts frames across the whole clip and asks your vision model for an advisory verdict; your own eyes decide.</Li>
        <Li><b>Approve</b> the good clip. <b>Discard</b> a bad one with a reason: it moves to <code>_discarded/</code> and its cost is counted as discarded spend.</Li>
        <Li>Each shot allows 3 final attempts (the first and two retries). Past that, change the prompt or override deliberately.</Li>
        <Li>If a job times out or the page was closed, use <b>Sync</b>: it fetches the real cost and the clip if the job finished.</Li>
      </ul>
    ),
  },
  {
    id: "editor", title: "Review & Export (the editor)", summary: "Timeline, text, music, 36 transitions, export.",
    body: (
      <>
        <ul className="list-disc space-y-1.5 pl-5">
          <Li>Your shot clips are already on the Video track. Drag a clip to reorder it, drag its edges to trim, press <kbd>S</kbd> to split at the playhead.</Li>
          <Li><b>Text:</b> add a title, subtitle or caption bubble, then drag and resize it in the preview. Set font (Poppins, Anton, Bebas Neue, Pacifico), size, colours, bubble, alignment, opacity and shadow. Up to 100 characters per item.</Li>
          <Li><b>Audio:</b> upload music or a voice-over (mp3, wav, m4a, aac, ogg). Set volume, start time, trim and fades; the waveform is drawn on the track.</Li>
          <Li><b>Transitions:</b> pick the way each clip comes in from 36 choices: dissolve, dips to black or white, wipes, slides, cover and reveal, circle, doors, pixelate, zoom, blur and more. The preview shows a cut; the export has the transition.</Li>
          <Li><b>Aspect ratio:</b> 9:16, 16:9 or 1:1 (black bars where a clip does not match).</Li>
          <Li><b>Export Video</b> renders one MP4 with ffmpeg on your computer (free) into the project's <code>exports/</code> folder. Edits save automatically and survive reloads.</Li>
        </ul>
        <p className="mt-3 text-slate-400">Not in this version: stickers, filters, effects, automatic captions. Underline and shadow blur are exported as shown; italic uses a real italic font only for Poppins Regular and Bold.</p>
      </>
    ),
  },
  {
    id: "budget", title: "Budget, prices and spending limits", summary: "How the estimate, stop-loss and caps work together.",
    body: (
      <ul className="list-disc space-y-1.5 pl-5">
        <Li><b>Estimate</b> = clips plus images still to make, divided by (1 − retry allowance). The retry allowance (default 0.2) plans for 20% of shots needing a retry.</Li>
        <Li><b>Approving</b> the budget only sets a ceiling. Generation still needs your approval for each exact price, and stops when spend plus the next job would pass 130% of the estimate (the stop-loss).</Li>
        <Li><b>Prices</b> come from the built-in price list and from Settings &gt; Model Configuration, where you can set a price for any model. A model with no price cannot make images or clips until you set one.</Li>
        <Li><b>Costs</b> splits spend into used and discarded, so a bad clip's cost stays visible.</Li>
        <Li><b>AI text calls</b> (chat, verify) are free with free models. Paid or unpriced text models are refused unless you turn on <i>Allow paid models</i>, and then stop at the per-project AI spending cap (default $0.50).</Li>
        <Li>If a fallback model costs more than the price you approved, you are asked again.</Li>
      </ul>
    ),
  },
  {
    id: "projects", title: "Export, import, delete and restore projects", summary: "Move work between computers and recover from mistakes.",
    body: (
      <ul className="list-disc space-y-1.5 pl-5">
        <Li><b>Export project</b> (the 3-dot menu on a card, the sidebar project menu, or Review &amp; Export) downloads the whole folder as a zip. Discarded files are left out unless you choose the menu entry that includes them.</Li>
        <Li><b>Import project (zip)</b> accepts a zip made by Export. Every file is checked first and the whole zip is refused, with a list of reasons, if anything is wrong: unsafe paths, links, wrong file types, files that are not what their name says, invalid project files, missing clips, oversized archives. Approvals and the budget approval inside the zip are reset on purpose; you approve again here.</Li>
        <Li><b>Delete project</b> asks you to type its name, then moves it to the trash folder. Nothing is erased. It appears in the <b>Archived</b> tab with a Restore button.</Li>
        <Li><b>Favorites:</b> use the 3-dot menu on a card; the Favorites tab lists them.</Li>
      </ul>
    ),
  },
];

export const FEATURES: { title: string; text: string }[] = [
  { title: "Model chains with fallback", text: "Give each job (chat, verify, vision, image, video) an ordered list of models. If the first is busy, rate-limited or out of credit, the next one is used, and never a dearer one than you approved." },
  { title: "Many providers, one app", text: "OpenRouter, Google, OpenAI, Anthropic, Runway, Kling, Replicate and any OpenAI-compatible server, side by side." },
  { title: "Verification", text: "Free rule checks run after every change; an optional AI review reads the brief, story, assets and shots and lists concrete problems." },
  { title: "Languages", text: "English and Tamil are tested with the video model; other languages are offered with a clear warning. Voice lines use the language's own script." },
  { title: "Rename without breaking", text: "Renaming an asset or a shot updates files, references, the cost log and discard history together." },
  { title: "Honest costs", text: "Every call is logged with its provider and whether the price was exact or estimated. Used and discarded spend are shown apart." },
  { title: "Safe by design", text: "The server listens on 127.0.0.1 only, needs a session token, and rejects requests that carry a foreign Host or Origin, so a website you visit cannot drive it." },
  { title: "Agents and scripts", text: "An MCP server and an HTTP API with revocable keys let outside tools do the writing and proposing, while approvals stay with you." },
];

export const SHORTCUTS: [string, string][] = [
  ["⌘K / Ctrl K", "Command box: jump to a page or project, or type an idea to start a new project"],
  ["Space", "Editor: play / pause"],
  ["S", "Editor: split at the playhead"],
  ["Delete", "Editor: remove the selected clip, text or sound"],
  ["⌘Z / Shift ⌘Z", "Editor: undo / redo"],
  ["← →", "Editor: move the playhead 0.1 s (hold Shift for 1 s)"],
  ["Ctrl + scroll", "Editor: zoom the timeline"],
  ["Enter / Shift Enter", "Chat: send / new line"],
];

export const TROUBLE: { problem: string; fix: ReactNode }[] = [
  { problem: "Export Video is off, or says ffmpeg is not installed", fix: <>Install ffmpeg (<code>brew install ffmpeg</code> on macOS) and restart AI Studio. Clip frame checks need it too.</> },
  { problem: "\"No price set for ...\" when generating", fix: <>Open Settings &gt; Model Configuration, press <b>Set price</b> on that model and enter its price per image or per second, or pick a model that already has one.</> },
  { problem: "Generation says the budget is not approved, or stops at the stop-loss", fix: <>Approve the budget first (the checklist's <b>Set the budget</b>). At the stop-loss, re-estimate with a higher retry allowance, or override deliberately for one job.</> },
  { problem: "\"A scene frame is refused\" or \"first frame missing\"", fix: <>Generate the characters and places first, then the scene frames, then the clips. The checklist always shows the next valid step.</> },
  { problem: "The provider key is rejected (401/403)", fix: <>Press <b>Replace key</b> on the provider card and paste a valid key with credit, then <b>Test</b>. Keys are never shown, so you cannot copy one back out.</> },
  { problem: "The chat answered with odd symbols or said it generated something", fix: <>The app re-asks the model once when an answer is unreadable and hides raw tool output. Free models vary: put a more reliable model first in Settings &gt; Chat. Tara cannot generate anything; the checklist is the truth.</> },
  { problem: "I see a black or plain picture, or a clip that will not play", fix: <>That is a test project: images and clips are placeholders by design. Make a real project (without the Test switch) after connecting a provider.</> },
  { problem: "Import project (zip) was refused", fix: <>Read the list shown: it names every file and the reason. Fix or remove those files in the zip and try again. A name that already exists must be changed.</> },
  { problem: "The page says Project not found", fix: <>The project was renamed, deleted or never imported on this computer. The 404 page offers Restore if it is in the trash, and suggests similar names.</> },
  { problem: "\"Session token\" asked, or every call returns 401", fix: <>Open the link printed in the terminal when you started the app (it carries the token), or start it again to get a new one.</> },
  { problem: "Port 8765 is already in use", fix: <>Start with another port: <code>AISTUDIO_PORT=8800 ./scripts/start.sh</code>.</> },
  { problem: "Text in the export looks different from the preview", fix: <>Fonts are bundled and used by both, so differences are small. The preview shows hard cuts; the export has the transitions.</> },
];

export const FAQ: { q: string; a: ReactNode }[] = [
  { q: "Does it run in the cloud?", a: "No. It runs on your computer and listens only on 127.0.0.1. Your projects are folders you own. Only the calls to your chosen AI providers leave your machine." },
  { q: "What does it cost?", a: "AI Studio itself is free and open source (MIT). You pay your providers for images and clips, and only after approving each exact price. Test projects, the editor and exports cost nothing." },
  { q: "Which models are supported?", a: "Any model your connected providers offer for chat, vision, image or video. Defaults lean on OpenRouter (for example a Qwen image model and Veo 3.1 Lite for video). Prices vary, so set or check them in Settings." },
  { q: "Can I use my own images and videos?", a: "Images, yes: upload any image as a character, background, frame or upload. Your own video clips can be placed into the editor by putting them in the project's clips folder." },
  { q: "Where are my files and keys?", a: "Projects are in the projects folder of your workspace. Provider keys are in your OS keychain, or a private file at ~/.aistudio, never in a project or an export." },
  { q: "How do I back up or move a project?", a: "Export project (zip) from the card menu, then Import project (zip) on the other computer. The zip holds everything except discarded files unless you ask for them." },
  { q: "Can several people use it?", a: "It is a single-user local tool with no accounts. Share projects by exporting and importing zips." },
  { q: "Can I use the videos commercially?", a: "AI Studio does not restrict it, but each model provider has its own terms for generated content. Check those for the models you use." },
  { q: "Why did a clip fail, and was I charged?", a: "Providers can reject or time out a job. A failed job is logged; whether it was billed depends on the provider, so compare the log with your provider's activity page. Sync resolves interrupted jobs." },
  { q: "How do I change the voice language?", a: "Pick it in the brief form on the Storyboard page (or tell Tara). Untested languages show a warning; always have a native speaker check the lines." },
  { q: "How do I update?", a: "Pull the latest code and run the start script again (it reinstalls the Python requirements). If the screens look old, run npm run build in the web folder. Your projects and settings are not touched." },
];
