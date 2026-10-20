"""AI Studio Bridge - HTTP Client Module

Uses only standard library urllib and json.
Designed for Blender's bundled Python environment.
"""

import json
import urllib.error
import urllib.parse
import urllib.request


class AIStudioError(Exception):
    """Custom exception raised when an AI Studio API call fails."""

    pass


class AIStudioClient:
    """Lightweight HTTP client communicating with the local AI Studio server."""

    def __init__(self, base_url="http://127.0.0.1:8765", token="", timeout=5.0):
        self.base_url = (base_url or "http://127.0.0.1:8765").rstrip("/")
        self.token = (token or "").strip()
        self.timeout = float(timeout)

    def _headers(self, content_type="application/json"):
        headers = {
            "Accept": "application/json",
            "Origin": "http://127.0.0.1",
        }
        if content_type:
            headers["Content-Type"] = content_type
        if self.token:
            headers["x-aistudio-token"] = self.token
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, endpoint, method="GET", data=None, content_type="application/json"):
        url = f"{self.base_url}{endpoint}"
        body = None
        if data is not None:
            if isinstance(data, (bytes, bytearray)):
                body = data
            elif isinstance(data, str):
                body = data.encode("utf-8")
            else:
                body = json.dumps(data).encode("utf-8")

        headers = self._headers(content_type)
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                resp_bytes = response.read()
                ct = response.headers.get("Content-Type", "")
                if "application/json" in ct or resp_bytes.strip().startswith((b"{", b"[")):
                    try:
                        return json.loads(resp_bytes.decode("utf-8"))
                    except Exception:
                        return resp_bytes
                return resp_bytes
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
                try:
                    err_json = json.loads(err_body)
                    msg = err_json.get("detail") or err_json.get("error") or err_body
                except Exception:
                    msg = err_body
            except Exception:
                msg = str(e)
            raise AIStudioError(f"HTTP {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise AIStudioError(f"Connection failed: {e.reason}") from e
        except TimeoutError:
            raise AIStudioError(f"Request timed out after {self.timeout}s")
        except Exception as e:
            raise AIStudioError(f"Request failed: {e}") from e

    def pair(self):
        """Verify server connection and auth token by fetching project list."""
        return self.list_projects()

    def list_projects(self):
        """GET /api/projects -> list of project objects or dicts."""
        res = self._request("/api/projects", method="GET")
        if isinstance(res, dict) and "projects" in res:
            return res["projects"]
        if isinstance(res, list):
            return res
        return []

    def get_shots(self, project_name):
        """Fetch shots for a project.

        Tries GET /api/projects/{name}/shots first.
        Falls back to GET /api/projects/{name} overview if /shots is not present (404/405).
        """
        safe_name = urllib.parse.quote(project_name)
        try:
            res = self._request(f"/api/projects/{safe_name}/shots", method="GET")
            if isinstance(res, dict) and "shots" in res:
                return res
        except AIStudioError as e:
            err_msg = str(e)
            if "HTTP 404" in err_msg or "HTTP 405" in err_msg:
                pass
            else:
                raise

        overview = self._request(f"/api/projects/{safe_name}", method="GET")
        if isinstance(overview, dict):
            shots_doc = overview.get("shots")
            if isinstance(shots_doc, dict):
                return shots_doc
            elif isinstance(shots_doc, list):
                return {"shots": shots_doc}
        return {"shots": []}

    def put_shots(self, project_name, shots_doc):
        """PUT /api/projects/{name}/shots with updated shots document."""
        safe_name = urllib.parse.quote(project_name)
        return self._request(f"/api/projects/{safe_name}/shots", method="PUT", data=shots_doc)

    def upload_frame(self, project_name, rel_path, image_bytes, replace=1):
        """POST /api/projects/{name}/upload?rel={rel}&replace={replace}

        Uploads raw image bytes to stills/ directory.
        """
        safe_name = urllib.parse.quote(project_name)
        query = urllib.parse.urlencode({"rel": rel_path, "replace": int(bool(replace))})
        endpoint = f"/api/projects/{safe_name}/upload?{query}"
        return self._request(endpoint, method="POST", data=image_bytes, content_type="image/png")

    def send_camera_move(self, project_name, shot_id, payload):
        """POST /api/projects/{name}/shots/{shot}/camera-move

        Sends camera matrix samples and lens info for classification.
        """
        safe_name = urllib.parse.quote(project_name)
        safe_shot = urllib.parse.quote(shot_id)
        endpoint = f"/api/projects/{safe_name}/shots/{safe_shot}/camera-move"
        return self._request(endpoint, method="POST", data=payload)

    def download_file(self, project_name, rel_path):
        """GET /files/{name}/{path}

        Downloads static media file (e.g. clips/<shot>.mp4).
        """
        safe_name = urllib.parse.quote(project_name)
        safe_path = urllib.parse.quote(rel_path.lstrip("/"), safe="/")
        endpoint = f"/files/{safe_name}/{safe_path}"
        return self._request(endpoint, method="GET")
