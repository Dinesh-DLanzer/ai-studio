# {{PROJECT}}: your to-do list
Run commands from the toolkit folder (the repo folder). Nothing is generated and no money is spent until you approve the budget.

## 1. Owner sign-off
- [ ] Read `Story.md` and `brief.md`; fix anything wrong (they are plain files, edit freely).
- [ ] Set the budget cap in `brief.md`.

## 2. Language check
- [ ] A native speaker checks every spoken line (in `shots.json`, inside each prompt).

## 3. Images (see `images.json`)
Make in this order: character master sheets (with expressions) → background sets → scene frames.
- [ ] (list is filled from images.json)

## 4. Brand assets for the editor
- [ ] Logo, colours, font, CTA text

## 5. Estimate and approve the budget
```
python3 vidad.py estimate {{PROJECT}} --failure 0.2 --draft-rounds 0
python3 vidad.py approve {{PROJECT}} budget
```

## 6. Generate one shot at a time
For each shot: dry run → run → `check` (look at EVERY frame) → approve or discard → ask before the next.
```
python3 vidad.py run {{PROJECT}} <shot> --stage final --dry-run
python3 vidad.py run {{PROJECT}} <shot> --stage final
python3 vidad.py check {{PROJECT}} <shot>
python3 vidad.py approve {{PROJECT}} <shot> final
python3 vidad.py discard {{PROJECT}} <file> -m "why"
```

## 7. Edit (CapCut / Premiere)
- [ ] Assemble, trim to the end of speech, add on-screen text, logo/end card, music, the platform's AI label.

## 8. Close-out
- [ ] `python3 vidad.py costs {{PROJECT}}` (USED vs DISCARDED) and compare with openrouter.ai/activity.
