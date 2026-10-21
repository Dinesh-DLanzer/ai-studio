"""Self-contained offline review package exporter.

Exports:
- index.html (self-contained, strict CSP, inline CSS/JS, no network requests)
- video.mp4 (from existing exports/ MP4)
- frames/<shot_id>.<ext> (poster frames per shot)
- Shot list (prompts HIDDEN unless include_prompts=True)
- Existing open comments
- Reviewer timecoded commenting and "Download feedback" -> feedback.json (Blob download)
"""
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Optional
import zipfile

from aistudio import comments as comments_mod, project as project_mod


def _build_html(
    project_name: str,
    shots: list[dict],
    open_comments: list[dict],
    shot_frames: dict[str, str],
    include_prompts: bool,
) -> str:
    escaped_project = html.escape(project_name, quote=True)
    generated_at = html.escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), quote=True)

    # Render shot list
    shot_items = []
    for s in shots:
        sid = s.get("id", "")
        escaped_sid = html.escape(sid, quote=True)
        note = s.get("note") or s.get("title") or ""
        escaped_note = html.escape(note, quote=True) if note else ""
        dur = s.get("seconds")
        dur_str = f"{dur}s" if dur is not None else ""
        frame_rel = shot_frames.get(sid)

        frame_html = f'<img src="{html.escape(frame_rel, quote=True)}" alt="{escaped_sid}" class="shot-thumb">' if frame_rel else '<div class="shot-thumb placeholder">No frame</div>'

        prompt_html = ""
        if include_prompts and s.get("prompt"):
            escaped_prompt = html.escape(s["prompt"], quote=True)
            prompt_html = f'<div class="shot-prompt"><strong>Prompt:</strong> {escaped_prompt}</div>'

        shot_items.append(f"""
        <div class="shot-card" data-shot-id="{escaped_sid}">
          {frame_html}
          <div class="shot-info">
            <div class="shot-header">
              <span class="shot-id">{escaped_sid}</span>
              <span class="shot-dur">{dur_str}</span>
            </div>
            {f'<div class="shot-note">{escaped_note}</div>' if escaped_note else ''}
            {prompt_html}
            <button type="button" class="btn-select-target" onclick="selectTarget('shot:{escaped_sid}')">Comment on shot</button>
          </div>
        </div>
        """)
    shots_html = "\n".join(shot_items) if shot_items else "<p class='empty-text'>No shots defined.</p>"

    # Render target dropdown options
    target_options = ['<option value="edit">Timeline / Whole video (edit)</option>']
    for s in shots:
        sid = s.get("id", "")
        if sid:
            esc = html.escape(sid, quote=True)
            target_options.append(f'<option value="shot:{esc}">Shot {esc}</option>')
    target_options_html = "\n".join(target_options)

    # Render existing open comments
    existing_items = []
    for c in open_comments:
        c_id = html.escape(c.get("id", ""), quote=True)
        c_target = html.escape(c.get("target", "edit"), quote=True)
        c_author = html.escape(c.get("author", "Unknown"), quote=True)
        c_text = html.escape(c.get("text", ""), quote=True)
        c_time = c.get("time")
        time_str = f"{c_time:.1f}s" if c_time is not None else "No timecode"
        seek_attr = f'onclick="seekTo({c_time})"' if c_time is not None else ""
        time_btn = f'<button type="button" class="btn-time" {seek_attr}>{time_str}</button>' if c_time is not None else f'<span class="btn-time inert">{time_str}</span>'

        existing_items.append(f"""
        <div class="comment-card" id="{c_id}">
          <div class="comment-header">
            <span class="comment-author">{c_author}</span>
            <span class="comment-target">{c_target}</span>
            {time_btn}
          </div>
          <div class="comment-body">{c_text}</div>
        </div>
        """)
    existing_html = "\n".join(existing_items) if existing_items else "<p class='empty-text'>No open comments.</p>"

    # Full HTML document
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src 'self' blob:; img-src 'self' data:;">
  <title>Review: {escaped_project}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #0f1117;
      color: #e2e8f0;
      line-height: 1.5;
      padding: 1.5rem;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 1rem;
      border-bottom: 1px solid #1e293b;
      margin-bottom: 1.5rem;
    }}
    h1 {{ font-size: 1.4rem; font-weight: 700; color: #f8fafc; }}
    .meta-sub {{ font-size: 0.85rem; color: #94a3b8; }}
    .badge {{
      display: inline-block;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
      background: #334155;
      color: #cbd5e1;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 1.5rem;
    }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
    }}
    .panel {{
      background: #181d28;
      border: 1px solid #1e293b;
      border-radius: 8px;
      padding: 1rem;
      margin-bottom: 1.5rem;
    }}
    .panel h2 {{
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 0.75rem;
      color: #f1f5f9;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    video {{
      width: 100%;
      max-height: 520px;
      background: #000;
      border-radius: 6px;
      display: block;
      margin-bottom: 0.75rem;
    }}
    .form-group {{ margin-bottom: 0.75rem; }}
    label {{ display: block; font-size: 0.8rem; font-weight: 600; color: #94a3b8; margin-bottom: 0.25rem; }}
    input[type="text"], input[type="number"], select, textarea {{
      width: 100%;
      background: #0f1117;
      border: 1px solid #334155;
      border-radius: 4px;
      color: #e2e8f0;
      padding: 0.5rem 0.6rem;
      font-size: 0.9rem;
    }}
    input:focus, select:focus, textarea:focus {{
      outline: none;
      border-color: #38bdf8;
    }}
    textarea {{ resize: vertical; min-height: 70px; }}
    .row-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }}
    .time-sync {{ display: flex; gap: 0.5rem; }}
    button {{
      background: #2563eb;
      color: #fff;
      border: none;
      border-radius: 4px;
      padding: 0.5rem 0.8rem;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }}
    button:hover {{ background: #1d4ed8; }}
    .btn-secondary {{ background: #334155; color: #f8fafc; }}
    .btn-secondary:hover {{ background: #475569; }}
    .btn-download {{
      background: #10b981;
      color: #fff;
      font-size: 0.95rem;
      padding: 0.6rem 1.2rem;
      width: 100%;
      border-radius: 6px;
    }}
    .btn-download:hover {{ background: #059669; }}
    .btn-time {{
      background: #0284c7;
      color: #fff;
      font-size: 0.75rem;
      padding: 0.15rem 0.4rem;
      border-radius: 3px;
    }}
    .btn-time.inert {{ background: #334155; cursor: default; }}
    .btn-select-target {{
      background: transparent;
      border: 1px solid #334155;
      color: #38bdf8;
      font-size: 0.75rem;
      padding: 0.2rem 0.5rem;
      margin-top: 0.35rem;
    }}
    .btn-select-target:hover {{ background: #1e293b; }}
    .comment-card {{
      background: #0f1117;
      border: 1px solid #1e293b;
      border-radius: 6px;
      padding: 0.6rem 0.75rem;
      margin-bottom: 0.5rem;
    }}
    .comment-card.reviewer {{
      border-left: 3px solid #10b981;
    }}
    .comment-header {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 0.3rem;
      font-size: 0.8rem;
    }}
    .comment-author {{ font-weight: 600; color: #f8fafc; }}
    .comment-target {{ color: #94a3b8; }}
    .comment-body {{ font-size: 0.88rem; color: #cbd5e1; white-space: pre-wrap; }}
    .empty-text {{ font-size: 0.85rem; color: #64748b; font-style: italic; padding: 0.5rem 0; }}
    .shot-card {{
      display: flex;
      gap: 0.75rem;
      background: #0f1117;
      border: 1px solid #1e293b;
      border-radius: 6px;
      padding: 0.6rem;
      margin-bottom: 0.5rem;
    }}
    .shot-thumb {{
      width: 90px;
      height: 54px;
      object-fit: cover;
      border-radius: 4px;
      background: #000;
      flex-shrink: 0;
    }}
    .shot-thumb.placeholder {{
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.7rem;
      color: #64748b;
      background: #1e293b;
    }}
    .shot-info {{ flex: 1; min-width: 0; }}
    .shot-header {{ display: flex; justify-content: space-between; font-size: 0.85rem; }}
    .shot-id {{ font-weight: 700; color: #f8fafc; }}
    .shot-dur {{ color: #94a3b8; font-size: 0.8rem; }}
    .shot-note {{ font-size: 0.8rem; color: #94a3b8; margin-top: 0.2rem; }}
    .shot-prompt {{ font-size: 0.78rem; color: #cbd5e1; background: #1e293b; padding: 0.3rem 0.5rem; border-radius: 4px; margin-top: 0.3rem; }}
    .scroll-list {{ max-height: 380px; overflow-y: auto; padding-right: 0.25rem; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Review: {escaped_project}</h1>
      <div class="meta-sub">Generated {generated_at} &bull; Offline Review Package</div>
    </div>
    <div>
      <span class="badge">{len(open_comments)} open project comments</span>
    </div>
  </header>

  <div class="layout">
    <div>
      <div class="panel">
        <video id="video-player" src="video.mp4" controls playsinline preload="metadata"></video>
        <h2>Add Reviewer Comment</h2>
        <form id="comment-form" onsubmit="event.preventDefault(); addReviewerComment();">
          <div class="row-2">
            <div class="form-group">
              <label for="input-author">Your Name / Title</label>
              <input id="input-author" type="text" placeholder="e.g. Priya (reviewer)" value="Reviewer" maxlength="64" required>
            </div>
            <div class="form-group">
              <label for="select-target">Target</label>
              <select id="select-target">
                {target_options_html}
              </select>
            </div>
          </div>
          <div class="form-group">
            <label for="input-time">Timecode (seconds)</label>
            <div class="time-sync">
              <input id="input-time" type="number" step="0.1" min="0" value="0.0">
              <button type="button" class="btn-secondary" onclick="syncWithVideo()">Use Video Time</button>
            </div>
          </div>
          <div class="form-group">
            <label for="input-text">Feedback / Note</label>
            <textarea id="input-text" placeholder="Type your comment here..." maxlength="2000" required></textarea>
          </div>
          <button type="submit" style="width: 100%;">Add Comment</button>
        </form>
      </div>
    </div>

    <div>
      <div class="panel">
        <h2>
          <span>Your Feedback <span id="feedback-count" class="badge">0</span></span>
        </h2>
        <div id="reviewer-comments-list" class="scroll-list" style="margin-bottom: 1rem;">
          <p id="empty-feedback-msg" class="empty-text">No comments added yet. Add comments on the left, then download feedback below.</p>
        </div>
        <button id="btn-download" type="button" class="btn-download" onclick="downloadFeedback()">Download feedback (feedback.json)</button>
      </div>

      <div class="panel">
        <h2>Existing Project Comments <span class="badge">{len(open_comments)}</span></h2>
        <div class="scroll-list">
          {existing_html}
        </div>
      </div>

      <div class="panel">
        <h2>Shot List <span class="badge">{len(shots)}</span></h2>
        <div class="scroll-list">
          {shots_html}
        </div>
      </div>
    </div>
  </div>

  <script>
    const video = document.getElementById('video-player');
    const inputTime = document.getElementById('input-time');
    const selectTarget = document.getElementById('select-target');
    const inputAuthor = document.getElementById('input-author');
    const inputText = document.getElementById('input-text');
    const reviewerList = document.getElementById('reviewer-comments-list');
    const feedbackCount = document.getElementById('feedback-count');
    const emptyMsg = document.getElementById('empty-feedback-msg');

    const reviewerComments = [];

    function seekTo(sec) {{
      if (video && !isNaN(sec)) {{
        video.currentTime = sec;
        video.play().catch(() => {{}});
      }}
    }}

    function syncWithVideo() {{
      if (video) {{
        inputTime.value = video.currentTime.toFixed(1);
      }}
    }}

    function selectTarget(targetVal) {{
      if (selectTarget) {{
        selectTarget.value = targetVal;
        syncWithVideo();
        inputText.focus();
      }}
    }}

    function escapeHtml(str) {{
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }}

    function addReviewerComment() {{
      const author = inputAuthor.value.trim();
      const text = inputText.value.trim();
      const target = selectTarget.value;
      const timeVal = parseFloat(inputTime.value);
      const time = !isNaN(timeVal) && timeVal >= 0 ? parseFloat(timeVal.toFixed(2)) : null;

      if (!author || !text) return;

      const cid = 'c_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8);
      const comment = {{
        id: cid,
        target: target,
        time: time,
        author: author,
        text: text,
        status: 'open',
        created: new Date().toISOString(),
        source: 'reviewer'
      }};

      reviewerComments.push(comment);
      feedbackCount.textContent = reviewerComments.length;

      if (emptyMsg) emptyMsg.style.display = 'none';

      const card = document.createElement('div');
      card.className = 'comment-card reviewer';
      const timeDisplay = time !== null ? time.toFixed(1) + 's' : 'No timecode';
      const timeBtn = time !== null ? '<button type="button" class="btn-time" onclick="seekTo(' + time + ')">' + timeDisplay + '</button>' : '<span class="btn-time inert">' + timeDisplay + '</span>';

      card.innerHTML = '<div class="comment-header">' +
        '<span class="comment-author">' + escapeHtml(author) + '</span>' +
        '<span class="comment-target">' + escapeHtml(target) + '</span>' +
        timeBtn +
        '</div>' +
        '<div class="comment-body">' + escapeHtml(text) + '</div>';

      reviewerList.appendChild(card);
      inputText.value = '';
    }}

    function downloadFeedback() {{
      if (reviewerComments.length === 0) {{
        alert('Please add at least one comment before downloading feedback.');
        return;
      }}
      const doc = {{
        schema_version: 1,
        comments: reviewerComments
      }};
      const jsonStr = JSON.stringify(doc, null, 2);
      const blob = new Blob([jsonStr], {{ type: 'application/json' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'feedback.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }}
  </script>
</body>
</html>"""


def export(
    ws: Any,
    project: str,
    out: Optional[Path | str] = None,
    include_prompts: bool = False,
) -> Path:
    """Export self-contained review package to a folder or zip archive.

    If out ends with '.zip', writes a zip archive.
    If out is a directory path, writes folder contents.
    If out is None, creates and returns a temporary zip archive path.
    """
    pdir = ws.pdir(project) if hasattr(ws, "pdir") else Path(ws) / str(project)
    pdir = Path(pdir)

    # 1. Check for existing MP4 export
    exports_dir = pdir / "exports"
    mp4s = (
        sorted(exports_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        if exports_dir.is_dir()
        else []
    )
    if not mp4s:
        raise ValueError(
            f"Project '{project}' has no exported video in exports/. Please render the video before exporting a review package."
        )
    src_video = mp4s[0]

    # 2. Load shots and open comments
    shots_data = (
        project_mod.load_json(pdir, "shots.json")
        if (pdir / "shots.json").is_file()
        else {"shots": []}
    )
    shots = shots_data.get("shots", []) if isinstance(shots_data, dict) else []
    open_comments = comments_mod.list_comments(pdir, status="open")

    # Determine output mode
    is_zip = out is None or str(out).lower().endswith(".zip")
    if is_zip:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"aistudio-review-{project}-"))
        pkg_dir = temp_dir
    else:
        pkg_dir = Path(out)
        pkg_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = None

    try:
        # Copy video
        dst_video = pkg_dir / "video.mp4"
        shutil.copy2(src_video, dst_video)

        # Copy frames
        frames_dir = pkg_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        shot_frames = {}

        for s in shots:
            sid = s.get("id")
            if not sid:
                continue
            frame_path = None
            if s.get("first_frame"):
                candidate = pdir / s["first_frame"]
                if candidate.is_file():
                    frame_path = candidate
            if not frame_path and (pdir / "stills").is_dir():
                matches = list((pdir / "stills").glob(f"{sid}.*"))
                if matches and matches[0].is_file():
                    frame_path = matches[0]

            if frame_path:
                dst_frame = frames_dir / f"{sid}{frame_path.suffix.lower()}"
                shutil.copy2(frame_path, dst_frame)
                shot_frames[sid] = f"frames/{dst_frame.name}"

        # Write index.html
        html_content = _build_html(
            project_name=project,
            shots=shots,
            open_comments=open_comments,
            shot_frames=shot_frames,
            include_prompts=include_prompts,
        )
        (pkg_dir / "index.html").write_text(html_content, encoding="utf-8")

        # Create zip if requested
        if is_zip:
            if out is not None:
                final_zip = Path(out)
                final_zip.parent.mkdir(parents=True, exist_ok=True)
            else:
                fd = tempfile.NamedTemporaryFile(
                    prefix=f"aistudio-review-{project}-", suffix=".zip", delete=False
                )
                fd.close()
                final_zip = Path(fd.name)

            with zipfile.ZipFile(final_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for root_path, _, files in os.walk(pkg_dir):
                    for file_name in files:
                        file_path = Path(root_path) / file_name
                        rel_path = file_path.relative_to(pkg_dir)
                        zf.write(file_path, rel_path)
            return final_zip
        else:
            return pkg_dir

    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
