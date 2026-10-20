import ast
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "integrations" / "resolve" / "AI Studio.py"


class ResolveScriptPackageTests(unittest.TestCase):
    def test_script_compiles(self):
        source = SCRIPT.read_text(encoding="utf-8")
        compile(source, str(SCRIPT), "exec")

    def test_script_uses_no_shell_and_only_standard_library_imports(self):
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                self.assertFalse(
                    isinstance(node.func, ast.Attribute) and node.func.attr == "system",
                    "os.system is not allowed",
                )
                if isinstance(node.func, ast.Name) and node.func.id == "Popen":
                    self.assertFalse(any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords))
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                self.assertNotIn(name.split(".")[0], {"requests", "PySide2", "bmd"})
                self.assertIn(name.split(".")[0], {
                    "ast", "json", "os", "tempfile", "urllib", "urllib.error", "urllib.parse",
                    "urllib.request",
                })


if __name__ == "__main__":
    unittest.main()
