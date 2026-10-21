from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest
from urllib.parse import urlparse

PANEL_DIR = Path(__file__).resolve().parent.parent / "integrations" / "premiere-uxp"
MANIFEST_PATH = PANEL_DIR / "manifest.json"
INDEX_HTML_PATH = PANEL_DIR / "index.html"
INDEX_JS_PATH = PANEL_DIR / "index.js"
STYLES_CSS_PATH = PANEL_DIR / "styles.css"
README_PATH = PANEL_DIR / "README.md"
ICONS_DIR = PANEL_DIR / "icons"


class _HTMLResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.resources = []
        self.element_ids = set()
        self.button_texts = []
        self._current_tag = None
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        self._current_tag = tag
        self._current_text = []
        attrs_dict = dict(attrs)
        self.tags.append((tag, attrs_dict))

        if "id" in attrs_dict:
            self.element_ids.add(attrs_dict["id"])

        for attr in ("src", "href"):
            if attr in attrs_dict:
                self.resources.append((tag, attr, attrs_dict[attr]))

    def handle_endtag(self, tag):
        if tag == "button" and self._current_text:
            self.button_texts.append("".join(self._current_text).strip())
        self._current_tag = None
        self._current_text = []

    def handle_data(self, data):
        if self._current_tag == "button":
            self._current_text.append(data)


class TestPremierePanelPackage(unittest.TestCase):
    def test_directory_and_core_files_exist(self):
        self.assertTrue(PANEL_DIR.is_dir(), f"Panel directory not found at {PANEL_DIR}")
        self.assertTrue(MANIFEST_PATH.is_file(), f"manifest.json not found at {MANIFEST_PATH}")
        self.assertTrue(INDEX_HTML_PATH.is_file(), f"index.html not found at {INDEX_HTML_PATH}")
        self.assertTrue(INDEX_JS_PATH.is_file(), f"index.js not found at {INDEX_JS_PATH}")
        self.assertTrue(STYLES_CSS_PATH.is_file(), f"styles.css not found at {STYLES_CSS_PATH}")
        self.assertTrue(README_PATH.is_file(), f"README.md not found at {README_PATH}")
        self.assertTrue(ICONS_DIR.is_dir(), f"icons directory not found at {ICONS_DIR}")

        # Check placeholder note in icons directory
        icons_note = ICONS_DIR / "README.md"
        self.assertTrue(
            icons_note.is_file() or any(ICONS_DIR.iterdir()),
            "icons directory must contain a placeholder note or icon files",
        )

    def test_manifest_parses_and_has_required_keys(self):
        self.assertTrue(MANIFEST_PATH.is_file(), f"Manifest file missing at {MANIFEST_PATH}")
        content = MANIFEST_PATH.read_text(encoding="utf-8")
        manifest = json.loads(content)

        # UXP manifest version 5
        self.assertEqual(manifest.get("manifestVersion"), 5, "manifestVersion must be 5")
        self.assertIn("id", manifest)
        self.assertIsInstance(manifest["id"], str)
        self.assertTrue(manifest["id"].strip())

        self.assertIn("name", manifest)
        self.assertIn("version", manifest)
        self.assertEqual(manifest.get("main"), "index.html")

        # Host application: premierepro
        host = manifest.get("host")
        self.assertIsNotNone(host, "manifest must declare 'host'")
        if isinstance(host, list):
            self.assertTrue(len(host) >= 1)
            host_entry = host[0]
        else:
            host_entry = host

        self.assertIsInstance(host_entry, dict)
        self.assertEqual(host_entry.get("app"), "premierepro", "Host app must be 'premierepro'")
        self.assertIn("minVersion", host_entry, "Host entry must specify 'minVersion'")

        # Entrypoints: a panel entry "AI Studio"
        entrypoints = manifest.get("entrypoints")
        self.assertIsInstance(entrypoints, list, "entrypoints must be a list")
        self.assertTrue(len(entrypoints) >= 1, "entrypoints must contain at least one entry")

        panel_entries = [e for e in entrypoints if e.get("type") == "panel"]
        self.assertTrue(len(panel_entries) >= 1, "entrypoints must contain at least one panel entry")

        main_panel = panel_entries[0]
        self.assertIn("id", main_panel)
        label = main_panel.get("label", {})
        label_text = label.get("default") if isinstance(label, dict) else str(label)
        self.assertEqual(label_text, "AI Studio", "Panel entry label must be 'AI Studio'")

    def test_manifest_network_permissions_limited_to_localhost(self):
        content = MANIFEST_PATH.read_text(encoding="utf-8")
        manifest = json.loads(content)

        perms = manifest.get("requiredPermissions", {})
        network = perms.get("network", {})
        domains = network.get("domains")

        self.assertIsInstance(domains, list, "network.domains must be a list of allowed endpoints")
        self.assertFalse(domains == "all", "network.domains must not be unrestricted 'all'")

        allowed_localhost = {"http://127.0.0.1:8765", "http://localhost:8765"}
        for domain in domains:
            parsed = urlparse(domain)
            self.assertIn(
                parsed.hostname,
                {"127.0.0.1", "localhost"},
                f"Domain {domain} is not localhost or 127.0.0.1",
            )
            self.assertIn(
                domain,
                allowed_localhost,
                f"Domain {domain} must be one of {allowed_localhost}",
            )

        # Must include both 127.0.0.1:8765 and localhost:8765
        self.assertTrue(
            any("127.0.0.1:8765" in d for d in domains),
            "network.domains must include http://127.0.0.1:8765",
        )
        self.assertTrue(
            any("localhost:8765" in d for d in domains),
            "network.domains must include http://localhost:8765",
        )

    def test_index_js_no_eval_new_function_or_remote_scripts(self):
        js_content = INDEX_JS_PATH.read_text(encoding="utf-8")

        # No eval(...)
        self.assertIsNone(
            re.search(r"\beval\s*\(", js_content),
            "index.js must not contain eval() calls",
        )

        # No new Function(...)
        self.assertIsNone(
            re.search(r"\bnew\s+Function\s*\(", js_content),
            "index.js must not construct functions dynamically with new Function()",
        )

        # No setTimeout/setInterval with string code
        self.assertIsNone(
            re.search(r"\bset(?:Timeout|Interval)\s*\(\s*['\"`]", js_content),
            "index.js must not pass string code to setTimeout/setInterval",
        )

        # No remote script creation (e.g. script.src = "http...")
        remote_script_match = re.search(
            r"""src\s*=\s*['"`](?:https?:|//)""",
            js_content,
            re.IGNORECASE,
        )
        self.assertIsNone(
            remote_script_match,
            "index.js must not load or inject remote scripts",
        )

        # Must only call local server URLs
        for match in re.finditer(r"""fetch\s*\(\s*['"`](https?:[^\s'"`]+)""", js_content):
            url = match.group(1)
            parsed = urlparse(url)
            self.assertIn(
                parsed.hostname,
                {"127.0.0.1", "localhost"},
                f"fetch() called with non-localhost URL: {url}",
            )

    def test_index_html_loads_only_local_files(self):
        html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")
        parser = _HTMLResourceParser()
        parser.feed(html_content)

        # Check all referenced resources (scripts, links, styles, images)
        for tag, attr, uri in parser.resources:
            uri_stripped = uri.strip()
            self.assertFalse(
                uri_stripped.startswith(("http://", "https://", "//", "ftp://")),
                f"<{tag} {attr}='{uri}'> references a remote URL; only local files allowed",
            )
            self.assertFalse(
                uri_stripped.startswith("data:text/javascript"),
                f"<{tag} {attr}='{uri}'> uses inline javascript URI",
            )

        # Ensure index.js and styles.css are linked
        script_srcs = [uri for tag, attr, uri in parser.resources if tag == "script" and attr == "src"]
        css_hrefs = [uri for tag, attr, uri in parser.resources if tag == "link" and attr == "href"]
        self.assertTrue(
            any("index.js" in s for s in script_srcs),
            "index.html must load index.js locally",
        )
        self.assertTrue(
            any("styles.css" in c for c in css_hrefs),
            "index.html must load styles.css locally",
        )

    def test_index_html_has_required_ui_elements(self):
        html_content = INDEX_HTML_PATH.read_text(encoding="utf-8")
        parser = _HTMLResourceParser()
        parser.feed(html_content)

        # Required fields and controls
        element_ids = parser.element_ids
        html_lower = html_content.lower()

        # Server URL input
        self.assertTrue(
            "server-url" in element_ids
            or "serverurl" in element_ids
            or 'name="server-url"' in html_lower
            or 'id="server' in html_lower,
            "index.html must contain a server URL input field",
        )

        # Token input
        self.assertTrue(
            "token" in element_ids
            or "api-token" in element_ids
            or "auth-token" in element_ids
            or 'id="token' in html_lower,
            "index.html must contain an auth/token input field",
        )

        # Project list
        self.assertTrue(
            "projects" in element_ids
            or "project-select" in element_ids
            or "project-list" in element_ids
            or 'id="project' in html_lower,
            "index.html must contain a project list or selector",
        )

        # Media list
        self.assertTrue(
            "media-list" in element_ids
            or "medialist" in element_ids
            or 'id="media' in html_lower,
            "index.html must contain a media list container",
        )

        # Buttons: Import to bin and Create sequence
        button_texts_lower = [t.lower() for t in parser.button_texts]
        all_text = " ".join(button_texts_lower) + " " + html_lower
        self.assertTrue(
            any("import to bin" in t for t in button_texts_lower) or "import to bin" in all_text,
            "index.html must contain an 'Import to bin' button",
        )
        self.assertTrue(
            any("create sequence" in t for t in button_texts_lower) or "create sequence" in all_text,
            "index.html must contain a 'Create sequence' button",
        )

    def test_readme_contains_required_sections(self):
        readme_content = README_PATH.read_text(encoding="utf-8")
        readme_lower = readme_content.lower()

        # UXP Developer Tool installation
        self.assertIn("uxp developer tool", readme_lower)

        # .ccx packaging/installation
        self.assertIn(".ccx", readme_lower)

        # Minimum Premiere version
        self.assertIn("minimum premiere", readme_lower)

        # Security notes
        self.assertIn("security", readme_lower)

        # Needed server routes
        self.assertIn("server routes", readme_lower)

        # UNVERIFIED section
        self.assertIn("unverified", readme_lower)


if __name__ == "__main__":
    unittest.main()
