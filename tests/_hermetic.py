"""Import this FIRST in any test that builds a Workspace, the CLI, the MCP server or the web app.
Guarantees tests never see a real key or a forced mode, and can never reach the network."""
import os

os.environ["AISTUDIO_NO_NETWORK"] = "1"     # real providers refuse to send anything
os.environ["AISTUDIO_NO_KEYRING"] = "1"     # never touch the OS keychain
import tempfile as _tf
os.environ["AISTUDIO_SECRETS_DIR"] = _tf.mkdtemp(prefix="aistudio-test-secrets-")   # never touch ~/.aistudio
for _k in ("AISTUDIO_ALL_TEST", "OPENROUTER_API_KEY", "AISTUDIO_TOKEN", "AISTUDIO_HOME"):
    os.environ.pop(_k, None)


def all_test(case):
    """Make every project in this test a TEST project (simulated, free): sets AISTUDIO_ALL_TEST=1 for the duration of the test."""
    os.environ["AISTUDIO_ALL_TEST"] = "1"
    case.addCleanup(os.environ.pop, "AISTUDIO_ALL_TEST", None)


def real_projects(case):
    """Projects behave as real projects in this test (the default); restores the previous setting afterwards."""
    old = os.environ.pop("AISTUDIO_ALL_TEST", None)
    if old is not None:
        case.addCleanup(os.environ.__setitem__, "AISTUDIO_ALL_TEST", old)
