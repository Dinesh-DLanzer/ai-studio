"""Service layer: everything the web API, MCP server and CLI can do, in one place.

Obeying core rules:
  * every paid action (image, clip, review) is a PROPOSAL; it runs only after a human approves,
  * gates: approved budget, stop-loss, max attempts,
  * nothing is ever deleted (discard moves files),
  * there is no app-wide mode: every project is either a TEST project or a real one.
Decomposed into domain modules under aistudio/domain/ with Workspace as a facade.
"""
import json
import os
from pathlib import Path
import threading

from aistudio import activity, catalog as catalog_mod, kind as kind_mod, migrate as migrate_mod, pricing as pricing_mod, roles as roles_mod, secrets as secrets_mod
from aistudio.domain.agents import AgentDomain
from aistudio.domain.characters import CharacterDomain
from aistudio.domain.chat import ChatDomain
from aistudio.domain.common import (
    DOC_FILES,
    ID_RE,
    MD_MARK,
    REPO,
    REVIEW_PRICE,
    ServiceError,
    _ident,
    _sha,
)
from aistudio.domain import spec as spec_mod
from aistudio.domain.batches import BatchDomain
from aistudio.domain.costs import CostDomain
from aistudio.domain.pipeline import PipelineDomain
from aistudio.domain.projects import ProjectDomain
from aistudio.domain.storyboard import StoryboardDomain
from aistudio.domain.todos import TodoDomain
from aistudio.domain.verify import VerifyDomain
from aistudio.providers import config as pconf, openrouter
from aistudio.settings_api import SettingsMixin


class Workspace(SettingsMixin):
    VERIFY_DELAY = 1.5

    def __init__(self, root, rates_path=None, transport=None, auto_verify=False, catalog_fetch=None, secrets=None):
        self.auto_verify = auto_verify
        self.catalog_fetch = catalog_fetch
        self._verify_lock, self._verify_running, self._catalog_cache = threading.Lock(), set(), None
        self.root = Path(root)
        (self.root / "projects").mkdir(parents=True, exist_ok=True)
        self.rates_path = Path(rates_path) if rates_path else (self.root / "rates.json" if (self.root / "rates.json").exists() else REPO / "rates.json")
        self.transport = transport
        self.settings_dir = self.root / "settings"
        self.secrets = secrets or secrets_mod.SecretStore()
        self._runner, self._health = None, roles_mod.Health()

        # Domain controllers
        self._projects = ProjectDomain(self)
        self._todos = TodoDomain(self)
        self._storyboard = StoryboardDomain(self)
        self._pipeline = PipelineDomain(self)
        self._chat = ChatDomain(self)
        self._characters = CharacterDomain(self)
        self._costs = CostDomain(self)
        self._verify = VerifyDomain(self)
        self._agents = AgentDomain(self)
        self.batches = BatchDomain(self)

        # Public domain accessors
        self.projects = self._projects
        self.todos_domain = self._todos
        self.storyboard_domain = self._storyboard
        self.pipeline_domain = self._pipeline
        self.chat_domain = self._chat
        self.characters_domain = self._characters
        self.costs_domain = self._costs
        self.verify_domain = self._verify
        self.agents_domain = self._agents

    # ---------------------------------------------------------------- providers and roles (settings v2)
    def ensure_settings(self):
        if not (self.settings_dir / "roles.json").exists() or not (self.settings_dir / "providers.json").exists():
            migrate_mod.migrate(self.root, force_openrouter=self.transport is not None)
        if self.transport is not None and not getattr(self, "_or_defaults_done", False):
            self._or_defaults_done = True
            provs = pconf.load_providers(self.settings_dir)
            if not any(x["type"] == "openrouter" for x in provs):
                new_provs, new_roles, _ = migrate_mod.plan(self.root, force_openrouter=True)
                doc = pconf.load_roles(self.settings_dir)
                for role, r in new_roles["roles"].items():
                    if not doc["roles"][role]["chain"]:
                        doc["roles"][role]["chain"] = r["chain"]
                provs = [x for x in new_provs if x["type"] == "openrouter"] + provs
                pconf.save_providers(self.settings_dir, provs)
                pconf.save_roles(self.settings_dir, doc, provs)

    def pricing(self):
        return pricing_mod.Pricing.load(self.rates_path, self.settings_dir)

    def catalog(self):
        return catalog_mod.Catalog(self.settings_dir, self.pricing())

    def runner(self):
        self.ensure_settings()
        if self._runner is None:
            t, shim = self.transport, None
            if t is not None:
                shim = lambda method, url, headers=None, body=None, raw=False, timeout=None: t(method, url[len(openrouter.API):] if url.startswith(openrouter.API) else url, body, raw)
            self._runner = roles_mod.RoleRunner(self.settings_dir, self.secrets, self.pricing(), transport=shim, fake_mode=self.forced_test, fake_for=self._fake_for,
                                                health=self._health, trust_transport=t is not None)
        self._runner.pricing = self.pricing()
        self._runner.catalog = self.catalog()
        return self._runner

    def forced_test(self):
        return os.environ.get("AISTUDIO_ALL_TEST", "").strip() == "1"

    def is_test(self, p):
        return self.forced_test() or (p is not None and kind_mod.is_test_project(p))

    def _chat_ready(self):
        return any(e["problem"] is None and e["ptype"] != "fake" for e in self.runner().resolve("chat", None, configured=True))

    def _fake_for(self, role, p=None):
        if not self.is_test(p):
            return False
        return role != "chat" or not self._chat_ready()

    def _primary(self, role, p=None):
        entries = self.runner().resolve(role, p)
        if not entries:
            raise ServiceError(f"No {pconf.ROLE_INFO[role]['title'].lower()} model is set. Open Settings, add a provider and choose a model for '{role}'.")
        ok = [e for e in entries if e["problem"] is None]
        if not ok:
            raise ServiceError(f"The {role} models cannot be used: " + "; ".join(f"{e['model']} ({e['problem']})" for e in entries) + ". Open Settings to fix the provider.")
        return ok[0]

    # ---------------------------------------------------------------- basics
    def rates(self):
        return self._costs.rates()

    def pdir(self, name):
        _ident(name, "project name")
        p = self.root / "projects" / name
        if p.is_symlink() or (p.is_dir() and p.resolve().parent != (self.root / "projects").resolve()):
            raise ServiceError(f"refusing project {name}: a project folder must be a real folder inside projects/")
        if not p.is_dir():
            projs_dir = self.root / "projects"
            if projs_dir.is_dir():
                matches = [d for d in projs_dir.iterdir() if d.is_dir() and not d.name.startswith(("_", ".")) and (d.name.lower() == name.lower() or d.name.lower().startswith(name.lower()))]
                if len(matches) == 1 and not matches[0].is_symlink():
                    return matches[0]
            raise ServiceError(f"no such project: {name}")
        return p

    def _read(self, pdir, fn, default=None):
        f = pdir / fn
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default

    # ---------------------------------------------------------------- projects domain delegation
    def list_projects(self):
        return self._projects.list_projects()

    def create_project(self, name, test_pipeline=False):
        return self._projects.create_project(name, test_pipeline=test_pipeline)

    def set_favorite(self, name, on):
        return self._projects.set_favorite(name, on)

    def overview(self, name):
        return self._projects.overview(name)

    def get_text(self, name, fn):
        return self._projects.get_text(name, fn)

    def _sync_md(self, name, fn):
        return self._projects._sync_md(name, fn)

    def _apply_brief_md(self, name, text):
        return self._projects._apply_brief_md(name, text)

    def put_text(self, name, fn, text):
        return self._projects.put_text(name, fn, text)

    def add_file(self, name, rel, data, replace=False):
        return self._projects.add_file(name, rel, data, replace=replace)

    def brief_get(self, name):
        return self._projects.brief_get(name)

    def brief_put(self, name, updates):
        return self._projects.brief_put(name, updates)

    def rename_project(self, name, new):
        return self._projects.rename_project(name, new)

    def import_project(self, zip_path, name=None, filename=""):
        return self._projects.import_project(zip_path, name=name, filename=filename)

    def export_project(self, name, include_discarded=False):
        return self._projects.export_project(name, include_discarded=include_discarded)

    def delete_project(self, name, confirm):
        return self._projects.delete_project(name, confirm)

    def trash_list(self):
        return self._projects.trash_list()

    def trash_restore(self, tid, as_name=None):
        return self._projects.trash_restore(tid, as_name=as_name)

    def rename_asset(self, name, old, new):
        return self._projects.rename_asset(name, old, new)

    def rename_shot(self, name, old, new):
        return self._projects.rename_shot(name, old, new)

    def discard(self, name, rel, reason=""):
        return self._projects.discard(name, rel, reason=reason)

    def restore(self, name, rel):
        return self._projects.restore(name, rel)

    def _rewrite_log(self, p, fn):
        return self._projects._rewrite_log(p, fn)

    def _retarget_discarded(self, p, old_prefix, new_prefix):
        return self._projects._retarget_discarded(p, old_prefix, new_prefix)

    def _plan_moves(self, p, dirs, old_prefix, new_prefix, pattern):
        return self._projects._plan_moves(p, dirs, old_prefix, new_prefix, pattern)

    # ---------------------------------------------------------------- todos domain delegation
    def _todo_store(self, p):
        return self._todos._todo_store(p)

    def todos(self, name):
        return self._todos.todos(name)

    def todo_add(self, name, title):
        return self._todos.todo_add(name, title)

    def todo_toggle(self, name, tid):
        return self._todos.todo_toggle(name, tid)

    def todo_remove(self, name, tid):
        return self._todos.todo_remove(name, tid)

    def _render_todo_md(self, name):
        return self._todos._render_todo_md(name)

    def _apply_todo_md(self, name, text):
        return self._todos._apply_todo_md(name, text)

    # ---------------------------------------------------------------- characters domain delegation
    def _image_spec(self, p, img_id):
        return self._characters._image_spec(p, img_id)

    def remix(self, name, meta_rel, reveal_code=False):
        return self.pipeline_domain.remix(name, meta_rel, reveal_code=reveal_code)

    def propose_variants(self, name, kind, target, count, actor="local"):
        return self.batches.create_variants(name, kind, target, count, actor=actor)

    def select_version(self, name, kind, target, k):
        return self.pipeline_domain.select_version(name, kind, target, k)

    def drift_check(self, name, target):
        return self.pipeline_domain.drift_check(name, target)

    def identity_sheet(self, name, char_id, views=None, actor="local"):
        return self._characters.identity_sheet(name, char_id, views=views, actor=actor)

    def analyze_character_image(self, name, rel):
        return self._characters.analyze_character_image(name, rel)

    # ---------------------------------------------------------------- costs domain delegation
    def estimate(self, name, failure=0.2):
        return self._costs.estimate(name, failure=failure)

    def _estimate(self, p, shots, images, existing, failure):
        return self._costs._estimate(p, shots, images, existing, failure)

    def approve_budget(self, name):
        return self._costs.approve_budget(name)

    def costs(self, name):
        return self._costs.costs(name)

    def set_max_attempts(self, name, max_attempts):
        return self._costs.set_max_attempts(name, max_attempts)

    def sync(self, name):
        return self._costs.sync(name)

    # ---------------------------------------------------------------- storyboard domain delegation
    def convert_story(self, name, write=True, model="google/veo-3.1-lite", seconds=4, resolution="720p"):
        return self._storyboard.convert_story(name, write=write, model=model, seconds=seconds, resolution=resolution)

    def put_shots(self, name, doc):
        return self._storyboard.put_shots(name, doc)

    def put_images(self, name, doc):
        return self._storyboard.put_images(name, doc)

    @staticmethod
    def _slug(stem):
        return StoryboardDomain._slug(stem)

    @staticmethod
    def _guess_kind(stem, used_as_first_frame):
        return StoryboardDomain._guess_kind(stem, used_as_first_frame)

    def unregistered_stills(self, name):
        return self._storyboard.unregistered_stills(name)

    def import_stills(self, name, items):
        return self._storyboard.import_stills(name, items)

    def upload_image(self, name, aid=None, path=None, data=None, kind=None, replace=False, prompt="", real_person=False, subject=""):
        return self._storyboard.upload_image(name, aid=aid, path=path, data=data, kind=kind, replace=replace, prompt=prompt, real_person=real_person, subject=subject)

    def consent_list(self, name):
        from aistudio import consent
        return consent.read(self.pdir(name))

    def _asset_sha(self, name, asset_id):
        p = self.pdir(name)
        img = next((i for i in self._read(p, "images.json", {"images": []})["images"] if i.get("id") == asset_id), None)
        f = p / str(img["out"]) if img and img.get("out") else None
        if not f or not f.is_file():
            raise ServiceError(f"asset {asset_id} has no file to bind consent to")
        return _sha(f)

    def consent_record(self, name, subject, statement, kind="real_person", asset_id=None):
        """HUMAN session only (the one route is agent=False). Not an MCP/crew tool. With asset_id the consent is bound to that file's bytes."""
        from aistudio import consent
        return consent.record(self.pdir(name), subject, statement, kind, sha=self._asset_sha(name, asset_id) if asset_id else None)

    def consent_mark(self, name, asset_id):
        """HUMAN session only: mark the asset's current file bytes as a real person, so consent bound to those bytes is required whatever the flag says."""
        from aistudio import consent
        return consent.mark_real_person(self.pdir(name), asset_id, self._asset_sha(name, asset_id))

    def edit_get(self, name):
        return self._storyboard.edit_get(name)

    def edit_put(self, name, doc):
        return self._storyboard.edit_put(name, doc)

    def edit_export(self, name, progress=None):
        return self._storyboard.edit_export(name, progress=progress)

    def exports(self, name):
        return self._storyboard.exports(name)

    def export_fcpxml(self, name):
        return self._storyboard.export_fcpxml(name)

    def export_edl(self, name):
        return self._storyboard.export_edl(name)

    def export_subtitles(self, name, fmt="srt"):
        return self._storyboard.export_subtitles(name, fmt)

    def export_bundle(self, name):
        return self._storyboard.export_bundle(name)

    def add_audio(self, name, filename, data):
        return self._storyboard.add_audio(name, filename, data)

    def add_element(self, name, filename, data):
        return self._storyboard.add_element(name, filename, data)

    def list_elements(self, name):
        return self._storyboard.list_elements(name)

    def edit_still(self, name, still_id, prompt, edit_mode="inpaint_insertion", mask_mode="MASK_MODE_BACKGROUND"):
        return self._storyboard.edit_still(name, still_id, prompt, edit_mode=edit_mode, mask_mode=mask_mode)

    def clip_tool(self, name, tool, clip_id, **kw):
        return self._storyboard.clip_tool(name, tool, clip_id, **kw)

    def extend_clip(self, name, clip_id, prompt, seconds=5):
        return self._storyboard.extend_clip(name, clip_id, prompt, seconds=seconds)

    # ---------------------------------------------------------------- pipeline domain delegation
    def _production(self, p):
        return self._pipeline._production(p)

    def production_progress(self, name):
        return self._pipeline.production_progress(name)

    @staticmethod
    def _queue(st):
        return PipelineDomain._queue(st)

    def generate_all_plan(self, name):
        return self._pipeline.generate_all_plan(name)

    def _clip_spec_loose(self, p, shot_id):
        return self._pipeline._clip_spec_loose(p, shot_id)

    def _clip_spec(self, p, shot_id):
        return self._pipeline._clip_spec(p, shot_id)

    def _payload_and_price(self, name, kind, target):
        return self._pipeline._payload_and_price(name, kind, target)

    def _review_file(self, p, target):
        return self._pipeline._review_file(p, target)

    def propose(self, name, kind, target, reveal_code=False, options=None):
        return self._pipeline.propose(name, kind, target, reveal_code=reveal_code, options=options)

    def approve_human(self, name, pid):
        return self._pipeline.approve_human(name, pid)

    def spec(self, name, kind, target):
        """Read-only GenerationSpec preview: the model, snapped seconds, frames, references, price and warnings a generation would use."""
        _ident(target, "target")
        return spec_mod.resolve(self, self.pdir(name), kind, target, loose=True).to_dict()

    def proposal_status(self, name, pid):
        return self._pipeline.proposal_status(name, pid)

    def approve(self, name, pid, code):
        return self._pipeline.approve(name, pid, code)

    def reject(self, name, pid):
        return self._pipeline.reject(name, pid)

    def execute(self, name, pid, override=False):
        return self._pipeline.execute(name, pid, override=override)

    def _execute_kind(self, p, kind, target, payload, model, price, attempt, log):
        return self._pipeline._execute_kind(p, kind, target, payload, model, price, attempt, log)

    def _do_review(self, p, target, payload, model, log):
        return self._pipeline._do_review(p, target, payload, model, log)

    def approve_shot(self, name, shot_id):
        return self._pipeline.approve_shot(name, shot_id)

    def _void_proposals(self, p, pred):
        return self._pipeline._void_proposals(p, pred)

    def activity(self, name):
        p = self.pdir(name)
        return activity.load_activity(p)

    # ---------------------------------------------------------------- chat domain delegation
    def chat_history(self, name):
        return self._chat.chat_history(name)

    def _chat_state(self, p):
        return self._chat._chat_state(p)

    def chat_send(self, name, text, prefs=None, attachments=None):
        return self._chat.chat_send(name, text, prefs=prefs, attachments=attachments)

    def _chat_attachments(self, name, p, ids):
        return self._chat._chat_attachments(name, p, ids)

    def pending_story(self, name):
        return self._chat.pending_story(name)

    def apply_pending_story(self, name):
        return self._chat.apply_pending_story(name)

    def discard_pending_story(self, name):
        return self._chat.discard_pending_story(name)

    # ---------------------------------------------------------------- verify domain delegation
    def _legacy_view(self):
        return self._verify._legacy_view()

    def ai_settings(self):
        return self._verify.ai_settings()

    def put_ai_settings(self, new):
        return self._verify.put_ai_settings(new)

    def ai_catalog(self, refresh=False):
        return self._verify.ai_catalog(refresh=refresh)

    def ai_spent(self, name):
        return self._verify.ai_spent(name)

    def _ai_call(self, name, role, messages):
        return self._verify._ai_call(name, role, messages)

    def languages(self):
        return self._verify.languages()

    def _verify_inputs(self, p, scope):
        return self._verify._verify_inputs(p, scope)

    def _verify_ai(self, name, scope, art, brief, lang, rules):
        return self._verify._verify_ai(name, scope, art, brief, lang, rules)

    def verify_run(self, name, scope, ai=True):
        return self._verify.verify_run(name, scope, ai=ai)

    def verify_status(self, name):
        return self._verify.verify_status(name)

    def _changed(self, name, *scopes):
        return self._verify._changed(name, *scopes)

    def _verify_bg(self, name, scope):
        return self._verify._verify_bg(name, scope)

    def verify_now(self, name, scope):
        return self._verify.verify_now(name, scope)

    def wait_verify(self, timeout=10.0):
        return self._verify.wait_verify(timeout=timeout)

    # ---------------------------------------------------------------- agents domain delegation
    def list_agents(self):
        return self._agents.list_agents()

    def run_agent_stream(self, agent_id, prompt, project=None):
        return self._agents.run_agent_stream(agent_id, prompt, project=project)

    def abort_agent(self, agent_id):
        return self._agents.abort_agent(agent_id)
