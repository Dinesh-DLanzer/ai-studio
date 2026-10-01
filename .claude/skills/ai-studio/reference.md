# ai-studio reference: what we learned (godpromo project, 2026-09-30)

## Models and prices (OpenRouter, checked 2026-09-30)
| Use | Model | Price |
|---|---|---|
| Video + audio | `google/veo-3.1-lite`, 720p | $0.05/s with audio ($0.20 per 4s), $0.03/s silent ($0.12 per 4s). Durations 4/6/8 s only |
| Images | `qwen/qwen-image-3` via `/api/v1/images` | about $0.036 per 2K image |
Catalog "list prices" for image models can show the input price only; real cost appears after a call (logged in `cost_log.csv`).

## Tamil / language audio
- **Veo 3.1 Lite produced Tamil the owner judged good, with lip-sync.** Seedance 2.5 got the same Tamil completely wrong. Google officially evaluates English only, so other languages are untested: test one cheap clip and have a native speaker listen before making the rest.
- Put the line in the language's script, then the English meaning in brackets: `AUDIO: X says this line in Tamil, clearly, in a natural conversational tone, lips synced to the words: "<Tamil script>" (<English>).`
- One short sentence per clip. Speech usually ends ~2-3 s into a 4 s clip; trim in the editor.
- Loanwords (like "business") can be mispronounced; reword with a native word or another spelling and retry.
- Voice consistency: describe the voice in the prompt ("the same voice as Suresh: a confident, calm, friendly middle-aged Indian man"). Veo cannot clone a voice but the same description gave similar voices across clips.
- Off-camera narration: "an off-camera narrator, <voice description>, says ..." and forbid people in the image.

## Images as first frames
- Veo accepted **realistic** first-frame photos of people. **Seedance rejected them** ("may contain real person"); do not use Seedance for realistic people.
- A first frame keeps the face, clothes and background. **Without a first frame Veo invents a new person** (an unknown man appeared in two clips). Give every clip with people a first frame.
- Character sheet first, then scene frames built from sheet + background (max 4 refs for Qwen). Request 9:16 for frames.

## Prompt recipe (video)
`SUBJECT: <who/what, "same face/hair/clothes as the first frame"> ACTION: <one action> CAMERA: <one move> LIGHTING: <...> STYLE: premium commercial advertisement, realistic, cinematic but believable. AUDIO: <line> NEGATIVE: no on-screen text, no subtitles, no logos, no background music, no watermark, no distorted faces or hands.`
Do NOT:
- put hex colour codes in prompts (Veo prints them on screen): say "deep teal and warm gold";
- say "empty centre / space for a logo" (it invites a person to fill it);
- ask for "no people" alone to stop a person: say "no person, no face, no hands, nobody appears on screen" AND do not leave the shot without a first frame;
- expect clean text or logos on generated screens (UI text comes out garbled, real social-media logos may appear): cover with editor overlays or prompt for plain geometric icons.

## Checking a clip (mandatory)
- Look at frames across the WHOLE clip: `vidad.py check`. A bad ending (an extra shirtless man, a double-exposure dissolve) can appear after the first 4 seconds; one sampled frame is not a check.
- Check: only the intended characters, same face/clothes, no stray text/logos, clean last second, audio present and speech timing.
- You cannot hear Tamil: the owner listens.

## Chaining and other tried-and-dropped ideas
- Starting a clip from the previous clip's last frame (+ a target last frame) made the voice collapse after 2 s. Do scene by scene; fix continuity in the edit (dissolve / match cut).
- Local video models (LTX etc.) need 32 GB+ memory; the owner's Mac is an 8 GB M1, so use hosted models.
- HeyGen / VoiceStudio / outside TTS were not needed once Veo gave good Tamil.

## Cost habits
- Estimate with `--failure 0.2`; the tool adds a retry allowance for every shot. About a third of the godpromo spend was discarded (mistakes, tests), so dry-run and check carefully.
- Silent clips are $0.12 vs $0.20 with audio; decide audio from the storyboard (voice-over or dialogue = audio on).
- `costs <project>` shows USED vs DISCARDED; reconcile with openrouter.ai/activity.
