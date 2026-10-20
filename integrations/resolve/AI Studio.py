"""AI Studio DaVinci Resolve utility script. Run from Workspace > Scripts."""

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request


TIMEOUT_SECONDS = 8


def _request(url, token, timeout=TIMEOUT_SECONDS):
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json, application/octet-stream",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def _api_url(base, path):
    return base.rstrip("/") + path


def _projects(base, token):
    data, _ = _request(_api_url(base, "/api/projects"), token)
    value = json.loads(data.decode("utf-8"))
    projects = value.get("projects", value) if isinstance(value, dict) else value
    result = []
    for project in projects:
        if isinstance(project, str):
            result.append((project, project))
        elif isinstance(project, dict):
            name = project.get("name") or project.get("id")
            if name:
                result.append((str(name), str(project.get("title") or name)))
    return result


def _download_timeline(base, token, project):
    quoted = urllib.parse.quote(project, safe="")
    errors = []
    for extension in ("otioz", "otio"):
        url = _api_url(base, "/api/projects/%s/export/%s" % (quoted, extension))
        try:
            content, _ = _request(url, token)
            handle = tempfile.NamedTemporaryFile(prefix="aistudio-", suffix="." + extension, delete=False)
            try:
                handle.write(content)
                return handle.name
            finally:
                handle.close()
        except (urllib.error.URLError, ValueError) as exc:
            errors.append("%s: %s" % (extension, exc))
    raise RuntimeError("No OTIO export is available (%s)" % "; ".join(errors))


def _media_items(base, token, project):
    quoted = urllib.parse.quote(project, safe="")
    url = _api_url(base, "/api/projects/%s/media?approved=1" % quoted)
    body, _ = _request(url, token)
    value = json.loads(body.decode("utf-8"))
    return value.get("media", value) if isinstance(value, dict) else value


def _fallback_import(base, token, project, media_pool):
    items = _media_items(base, token, project)
    imported = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        source = entry.get("path") or entry.get("src") or entry.get("url")
        if not source:
            continue
        if str(source).startswith(("http://", "https://")):
            data, _ = _request(str(source), token)
            suffix = os.path.splitext(urllib.parse.urlparse(str(source)).path)[1] or ".media"
            handle = tempfile.NamedTemporaryFile(prefix="aistudio-media-", suffix=suffix, delete=False)
            try:
                handle.write(data)
                source = handle.name
            finally:
                handle.close()
        imported.extend(media_pool.ImportMedia([source]) or [])
    if not imported:
        raise RuntimeError("The media endpoint returned no importable approved clips")
    timeline_items = []
    timeline_items.extend(imported)
    result = media_pool.AppendToTimeline(timeline_items)
    if result is False or result is None:
        raise RuntimeError("Resolve could not append imported media to the timeline")


def _run_import(base, token, project, media_pool):
    try:
        timeline_path = _download_timeline(base, token, project)
        try:
            if media_pool.ImportTimelineFromFile(timeline_path):
                return "Timeline imported."
        finally:
            try:
                os.unlink(timeline_path)
            except OSError:
                pass
    except (urllib.error.URLError, RuntimeError, ValueError) as exc:
        timeline_error = str(exc)
    else:
        timeline_error = "Resolve rejected the OTIO timeline."
    _fallback_import(base, token, project, media_pool)
    return "Timeline import failed (%s); imported approved media in API order." % timeline_error


def main():
    resolve = bmd.scriptapp("Resolve")
    fusion = bmd.scriptapp("Fusion")
    if not resolve or not fusion:
        print("AI Studio: Resolve scripting is unavailable.")
        return
    ui = fusion.UIManager
    dispatcher = bmd.UIDispatcher(ui)
    window = dispatcher.AddWindow({
        "ID": "AIStudioResolve",
        "WindowTitle": "AI Studio",
        "Geometry": [300, 300, 470, 190],
    }, ui.VGroup([
        ui.Label({"Text": "AI Studio server URL"}),
        ui.LineEdit({"ID": "server", "Text": "http://127.0.0.1:8000"}),
        ui.Label({"Text": "API token"}),
        ui.LineEdit({"ID": "token", "EchoMode": "Password"}),
        ui.Label({"Text": "Project"}),
        ui.ComboBox({"ID": "projects"}),
        ui.Button({"ID": "load", "Text": "Load projects"}),
        ui.Button({"ID": "import", "Text": "Import timeline"}),
        ui.Label({"ID": "status", "Text": "Enter the server URL and API token."}),
    ]))
    items = window.GetItems()
    state = {"projects": []}

    def on_load(_event):
        try:
            base = items["server"].Text.strip()
            token = items["token"].Text.strip()
            state["projects"] = _projects(base, token)
            combo = items["projects"]
            combo.Clear()
            for name, label in state["projects"]:
                combo.AddItem(label)
            items["status"].Text = "Loaded %d project(s)." % len(state["projects"])
        except Exception as exc:
            items["status"].Text = "Could not load projects: %s" % exc

    def on_import(_event):
        try:
            selected = int(items["projects"].CurrentIndex)
            if selected < 0 or selected >= len(state["projects"]):
                raise RuntimeError("Load projects and select a project first")
            project = state["projects"][selected][0]
            pool = resolve.GetProjectManager().GetCurrentProject().GetMediaPool()
            items["status"].Text = _run_import(items["server"].Text.strip(), items["token"].Text.strip(), project, pool)
        except Exception as exc:
            items["status"].Text = "Import failed: %s" % exc

    window.On["load"].Clicked = on_load
    window.On["import"].Clicked = on_import
    window.On["AIStudioResolve"].Close = lambda _event: dispatcher.ExitLoop()
    window.Show()
    dispatcher.RunLoop()
    window.Hide()


if __name__ == "__main__":
    main()
