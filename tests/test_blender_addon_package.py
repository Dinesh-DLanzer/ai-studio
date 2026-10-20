import ast
from pathlib import Path
import unittest
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

ADDON_DIR = Path(__file__).resolve().parent.parent / "integrations" / "blender" / "aistudio_bridge"
MANIFEST_PATH = ADDON_DIR / "blender_manifest.toml"


class TestBlenderAddonPackage(unittest.TestCase):
    def test_manifest_exists_and_parses(self):
        self.assertTrue(MANIFEST_PATH.is_file(), f"Manifest not found at {MANIFEST_PATH}")
        content = MANIFEST_PATH.read_text(encoding="utf-8")
        manifest = tomllib.loads(content)

        self.assertEqual(manifest.get("id"), "aistudio_bridge")
        self.assertEqual(manifest.get("version"), "0.1.0")
        self.assertEqual(manifest.get("blender_version_min"), "4.2.0")

        # License can be string or list containing SPDX:GPL-3.0-or-later
        lic = manifest.get("license")
        if isinstance(lic, list):
            self.assertTrue(
                any("GPL-3.0-or-later" in str(item) for item in lic),
                f"Expected GPL-3.0-or-later in license list, got {lic}",
            )
        else:
            self.assertIn("GPL-3.0-or-later", str(lic))

        # Permissions check
        permissions = manifest.get("permissions", {})
        self.assertIn("network", permissions)
        self.assertIn("files", permissions)
        self.assertEqual(permissions["network"], "talk to the local AI Studio server")
        self.assertEqual(permissions["files"], "save rendered frames temporarily")

    def test_init_and_python_files_compile(self):
        init_file = ADDON_DIR / "__init__.py"
        self.assertTrue(init_file.is_file(), "__init__.py not found")

        py_files = list(ADDON_DIR.glob("**/*.py"))
        self.assertTrue(len(py_files) >= 1)

        for py_file in py_files:
            source = py_file.read_text(encoding="utf-8")
            try:
                compiled = compile(source, str(py_file), "exec")
                self.assertIsNotNone(compiled)
            except SyntaxError as e:
                self.fail(f"Syntax error compiling {py_file}: {e}")

    def test_no_forbidden_network_imports(self):
        py_files = list(ADDON_DIR.glob("**/*.py"))
        forbidden_modules = {"requests", "httpx", "aiohttp", "socket", "http.client", "websocket"}

        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        self.assertNotIn(
                            top,
                            forbidden_modules,
                            f"Disallowed network module {alias.name} imported in {py_file}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top = node.module.split(".")[0]
                        self.assertNotIn(
                            top,
                            forbidden_modules,
                            f"Disallowed network module {node.module} imported in {py_file}",
                        )

    def test_no_shell_true_or_os_system(self):
        py_files = list(ADDON_DIR.glob("**/*.py"))

        for py_file in py_files:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # Check for os.system calls
                    if isinstance(node.func, ast.Attribute):
                        self.assertNotEqual(
                            node.func.attr,
                            "system",
                            f"os.system or similar call found in {py_file} at line {node.lineno}",
                        )
                    elif isinstance(node.func, ast.Name):
                        self.assertNotEqual(
                            node.func.id,
                            "system",
                            f"system() call found in {py_file} at line {node.lineno}",
                        )

                    # Check for shell=True or truthy shell keyword argument
                    for kw in node.keywords:
                        if kw.arg == "shell":
                            if isinstance(kw.value, ast.Constant):
                                self.assertFalse(
                                    bool(kw.value.value),
                                    f"shell=True found in {py_file} at line {node.lineno}",
                                )
                            else:
                                self.fail(
                                    f"Non-literal shell= argument found in {py_file} at line {node.lineno}"
                                )


if __name__ == "__main__":
    unittest.main()
