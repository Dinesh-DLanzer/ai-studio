"""Chat domain: producer chat turns, chat history, attachments, and pending story management."""
from datetime import datetime
from pathlib import Path
import re

from aistudio import chat as chat_mod, palette as palette_mod, project as project_mod
from aistudio.domain.common import ServiceError


class ChatDomain:
    def __init__(self, ws):
        self.ws = ws

    def chat_history(self, name):
        p = self.ws.pdir(name)
        msgs = [
            (
                {**m, "text": "(This answer was in an unreadable format and is hidden. Please ask again.)"}
                if m.get("role") == "assistant" and chat_mod.unreadable(m.get("text"))
                else m
            )
            for m in self.ws._read(p, "chat.json", [])
        ]
        return {
            "messages": msgs,
            "pending_story": (p / "pending_story.md").exists(),
            "brief": self.ws.brief_get(name),
            "test_pipeline": (p / "sandbox.json").exists(),
            "mode": "test" if self.ws.is_test(p) else "real",
            "progress": self.ws.production_progress(name),
        }

    def _chat_state(self, p):
        """The compact JSON the chat model sees every turn, so it never has to guess (or invent) what has been done."""
        st = self.ws._production(p)
        nxt = self.ws.production_progress(p.name)["next"]
        return {
            "brief_so_far": {k: st["brief"].get(k, "") for k in chat_mod.FIELD_KEYS if st["brief"].get(k)},
            "still_missing_required": st["progress"]["missing"],
            "storyboard": {"applied_shots": st["story"]["shots"], "draft_waiting_for_user": st["story"]["pending"], "shared_style": st["story"]["style"]},
            "budget": st["budget"],
            "assets": [{"id": x["id"], "kind": x["kind"], "made": x["made"]} for x in st["assets"]],
            "uploads": [{"id": u["id"], "colors": u["colors"]} for u in st["uploads"]],
            "shots": [{"id": x["id"], "clip_made": x["clip"], "approved": x["approved"]} for x in st["shots"]],
            "money_spent_usd": st["spent"],
            "next_step_for_the_user": nxt["label"] if nxt else "",
        }

    def _chat_attachments(self, name, p, ids):
        """Images the user attached to a chat message: can be an upload or any asset that exists. Returns [{id, file, colors}]."""
        if not ids:
            return []
        if not isinstance(ids, list) or len(ids) > 4:
            raise ServiceError("attach up to 4 images per message")
        imgs = {i["id"]: i for i in self.ws._read(p, "images.json", {"images": []})["images"]}
        out = []
        for aid in ids:
            i = imgs.get(aid)
            rel_file = None
            if i and (p / i.get("out", "")).is_file():
                rel_file = i["out"]
            else:
                # check if aid matches a filename directly in stills/
                for f in (p / "stills").glob(f"{aid}.*"):
                    if f.is_file():
                        rel_file = f"stills/{f.name}"
                        break
            if not rel_file or not (p / rel_file).is_file():
                raise ServiceError(f"attached image not found: {aid}")
            info = {"id": aid, "file": Path(rel_file).name, "colors": palette_mod.dominant_colors(p / rel_file)}
            out.append(info)
        return out

    def _detect_action_intent(self, p, text):
        """Infer action from user prompt if model missed or didn't output action field."""
        t = (text or "").lower().strip()
        if not t:
            return None
        if re.search(r"\b(generate|make|create|run|start)\s+(all|everything|whole|entire)\b", t) or re.search(r"\bgenerate\s+all\b", t):
            return {"type": "generate_all"}
        if (p / "pending_story.md").exists() and (re.search(r"\b(apply|save|use|confirm)\b.*\b(story|storyboard)\b", t) or "apply" in t):
            return {"type": "apply_story"}
        budget = self.ws._read(p, "budget.json", {})
        if not budget.get("approved") and budget.get("estimate") is not None:
            if re.search(r"\b(approve|set|confirm|accept)\b.*\b(budget)\b", t) or "approve budget" in t:
                return {"type": "approve_budget"}
        if re.search(r"\b(generate|create|make|render|draw|produce|start)\b", t):
            imgs = self.ws._read(p, "images.json", {"images": []}).get("images", [])
            shots = self.ws._read(p, "shots.json", {"shots": []}).get("shots", [])
            t_clean = re.sub(r"[^a-z0-9]", "", t)
            for img in imgs:
                if (p / img.get("out", "")).is_file():
                    continue
                iid = img["id"]
                iid_clean = re.sub(r"[^a-z0-9]", "", iid.lower())
                if iid.lower() in t or iid.replace("_", " ").lower() in t or (len(iid_clean) >= 4 and iid_clean in t_clean):
                    return {"type": "generate", "kind": "image", "target": iid}
            for sh in shots:
                sid = sh["id"]
                sid_clean = re.sub(r"[^a-z0-9]", "", sid.lower())
                if sid.lower() in t or sid.replace("s0", "shot ").lower() in t or sid_clean in t_clean:
                    return {"type": "generate", "kind": "clip", "target": sid}
            prog = self.ws.production_progress(p.name)
            nxt = prog.get("next") or {}
            if nxt.get("kind") in ("image", "clip") and nxt.get("target"):
                return {"type": "generate", "kind": nxt["kind"], "target": nxt["target"]}
            if nxt.get("kind") == "apply-story":
                return {"type": "apply_story"}
            if nxt.get("kind") == "budget":
                return {"type": "approve_budget"}
        return None

    def chat_send(self, name, text, prefs=None, attachments=None):
        """One producer-chat turn. Free models only (or the scripted test interviewer in a test project); never spends money."""
        p = self.ws.pdir(name)
        text = str(text or "").strip()
        if not text or len(text) > 50000:
            raise ServiceError("message must be 1 to 50000 characters")
        files = self._chat_attachments(name, p, attachments)
        history = self.ws._read(p, "chat.json", [])
        brief = self.ws._read(p, "brief.json", {})
        now = datetime.now().isoformat(timespec="seconds")
        res = {}
        test = self.ws.is_test(p)
        fake_chat = self.ws._fake_for("chat", p)
        if fake_chat:
            turn = chat_mod.scripted_turn(brief, history, text, files)
            model = "fake/scripted-interviewer"
        else:
            msgs = chat_mod.build_messages(history, text, self._chat_state(p), test, prefs, files)
            res = self.ws._ai_call(name, "chat", msgs)
            turn, model = chat_mod.parse_turn(res["text"]), res["model"]
            if turn.get("malformed") or (turn["storyboard_md"] and not chat_mod.valid_storyboard(turn["storyboard_md"])):
                # the model answered in the wrong format: ask once more, with the rules repeated, before showing the user anything
                try:
                    res2 = self.ws._ai_call(name, "chat", msgs + [{"role": "assistant", "content": (res["text"] or "")[:1500]}, {"role": "user", "content": chat_mod.RETRY_NOTE}])
                except ServiceError:
                    res2 = None  # the second try is best effort: keep the first answer
                if res2:
                    turn2 = chat_mod.parse_turn(res2["text"])
                    if not turn2.get("malformed"):
                        turn, model = turn2, res2["model"]
                        res = {**res2, "cost": (res.get("cost") or 0) + (res2.get("cost") or 0)}
            if turn.get("malformed"):
                turn = {
                    "reply": "Sorry, the chat model answered in a format I could not read. Please send your message again, or choose another chat model in Settings.",
                    "brief_updates": {},
                    "todos_add": [],
                    "storyboard_md": None,
                }
        if turn["brief_updates"]:
            self.ws.brief_put(name, turn["brief_updates"])
        if files and not fake_chat:  # remember the logo and its colours in the brief, whatever the model did with them
            cur = str(self.ws._read(p, "brief.json", {}).get("brand_assets", ""))
            add = "".join(f" Logo file: {f['id']}." + (f" Brand colours: {', '.join(f['colors'])}." if f["colors"] else "") for f in files if f"Logo file: {f['id']}" not in cur)
            if add:
                self.ws.brief_put(name, {"brand_assets": (cur + add).strip()})
        for t in turn["todos_add"]:
            self.ws.todo_add(name, t)
        reply = turn["reply"]
        applied = False
        if turn["storyboard_md"]:
            if chat_mod.valid_storyboard(turn["storyboard_md"]):
                (p / "pending_story.md").write_text(turn["storyboard_md"], encoding="utf-8")
                fresh = not self.ws._read(p, "shots.json", {"shots": []})["shots"]
                if fresh and (prefs or {}).get("auto_storyboard", True) is not False:
                    try:
                        res2 = self.apply_pending_story(name)
                        applied = True
                        reply += f"\n\nI wrote Story.md ({len(res2['shots']['shots'])} shots) from your brief and updated your TODO list."
                    except ServiceError:
                        pass
            else:
                reply += "\n\n(I drafted a storyboard but it was not in the right format, so I did not save it. Ask me to try again.)"

        # Pipeline action execution
        action = turn.get("action")
        if not action and not fake_chat:
            action = self._detect_action_intent(p, text)

        executed_info = None
        assistant_attachments = []
        if action:
            atype = action.get("type")
            if atype == "apply_story":
                if (p / "pending_story.md").exists():
                    try:
                        res2 = self.apply_pending_story(name)
                        applied = True
                        reply += f"\n\n✓ Applied Story.md ({len(res2['shots']['shots'])} shots) and updated TODO.md."
                        executed_info = {"type": "apply_story"}
                    except ServiceError as e:
                        reply += f"\n\n⚠️ Could not apply storyboard: {e}"
            elif atype == "approve_budget":
                try:
                    self.ws.approve_budget(name)
                    reply += "\n\n✓ Budget approved."
                    executed_info = {"type": "approve_budget"}
                except Exception as e:
                    reply += f"\n\n⚠️ Could not approve budget: {e}"
            elif atype == "generate":
                kind = action.get("kind") or "image"
                target = action.get("target")
                if target == "next" or not target:
                    nxt = self.ws.production_progress(name).get("next") or {}
                    target = nxt.get("target") or target
                    kind = nxt.get("kind") or kind
                if target:
                    already_made = False
                    if kind == "image":
                        for ext in (".png", ".jpg", ".webp"):
                            if (p / "stills" / f"{target}{ext}").is_file():
                                already_made = True
                                assistant_attachments.append({"id": target, "file": f"{target}{ext}"})
                                break
                    if already_made:
                        if re.search(r"I can'?t generate it myself|I cannot generate", reply, re.I):
                            reply = re.sub(r"I can'?t generate it myself[^.\n]*[.]?", f"**{target}** is already generated.", reply, flags=re.I).strip()
                        if "✓" not in reply:
                            reply += f"\n\n✓ **{target}** is already generated."
                        executed_info = {"type": "generate", "kind": kind, "target": target, "status": "already_done"}
                    else:
                        b = self.ws._read(p, "budget.json", {})
                        if not b.get("approved") and b.get("estimate") is not None:
                            try:
                                self.ws.approve_budget(name)
                            except Exception:
                                pass
                        try:
                            prop = self.ws.propose(name, kind, target, reveal_code=True)
                            self.ws.approve(name, prop["id"], prop["code"])
                            exec_res = self.ws.execute(name, prop["id"])
                            executed_info = {"type": "generate", "kind": kind, "target": target, "result": exec_res}
                            if re.search(r"I can'?t generate it myself|I cannot generate", reply, re.I):
                                reply = re.sub(r"I can'?t generate it myself[^.\n]*[.]?", f"Generating {kind} **{target}**.", reply, flags=re.I).strip()
                            if kind == "image":
                                out_file = None
                                if exec_res.get("file"):
                                    out_file = Path(exec_res["file"]).name
                                else:
                                    for ext in (".png", ".jpg", ".webp"):
                                        if (p / "stills" / f"{target}{ext}").is_file():
                                            out_file = f"{target}{ext}"
                                            break
                                if out_file:
                                    assistant_attachments.append({"id": target, "file": out_file})
                                if "✓" not in reply:
                                    reply += f"\n\n✓ Generated image for **{target}**."
                            elif kind == "clip":
                                if exec_res.get("pending"):
                                    reply += f"\n\n✓ Video clip generation for **{target}** has started."
                                else:
                                    reply += f"\n\n✓ Generated video clip for **{target}**."
                        except Exception as e:
                            if re.search(r"I can'?t generate it myself|I cannot generate", reply, re.I):
                                reply = re.sub(r"I can'?t generate it myself[^.\n]*[.]?", "", reply, flags=re.I).strip()
                            reply += f"\n\n⚠️ Could not generate {kind} '{target}': {e}"
            elif atype == "generate_all":
                executed_info = {"type": "generate_all"}
                if "✓" not in reply:
                    reply += "\n\n✓ Starting batch generation for all remaining assets."

        history += [
            {"role": "user", "text": text, "ts": now, **({"attachments": files} if files else {})},
            {
                "role": "assistant",
                "text": reply,
                "ts": now,
                "model": model,
                **({"attachments": assistant_attachments} if assistant_attachments else {}),
                **({"asked": turn["asked"]} if turn.get("asked") else {}),
                **({"cost": res["cost"]} if not fake_chat and res.get("cost") else {}),
            },
        ]
        project_mod.save_json(p, "chat.json", history[-200:])
        return {**self.chat_history(name), "reply": reply, "applied": applied, "action": action, "executed": executed_info}

    def pending_story(self, name):
        f = self.ws.pdir(name) / "pending_story.md"
        return {"text": f.read_text(encoding="utf-8") if f.exists() else ""}

    def apply_pending_story(self, name):
        """Human action: turn the drafted storyboard into Story.md + shots.json + images.json (refuses if clips are already approved)."""
        p = self.ws.pdir(name)
        f = p / "pending_story.md"
        if not f.exists():
            raise ServiceError("no drafted storyboard is waiting")
        if any(s.get("final_ok") for s in self.ws._read(p, "shots.json", {"shots": []})["shots"]):
            raise ServiceError("this project already has approved clips; start a new project instead of replacing its storyboard")
        (p / "Story.md").write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        res = self.ws.convert_story(name)
        self.ws._sync_md(name, "TODO.md")  # the to-do list follows the story
        f.replace(p / "last_applied_story.md")
        return res

    def discard_pending_story(self, name):
        f = self.ws.pdir(name) / "pending_story.md"
        if f.exists():
            f.replace(f.with_name("discarded_story.md"))
        return {"ok": True}
