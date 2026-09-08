import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("COMFYUI_ROOT", PLUGIN.parents[1])).resolve()
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("h3qwen_test", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
qwen = sys.modules["h3qwen_test.managed_qwen"]


class Tests(unittest.TestCase):
    def test_registered(self):
        self.assertIn("H3OfficialSkillQwenLocal", package.NODE_CLASS_MAPPINGS)
        self.assertIn("H3OptionalReferenceImages", package.NODE_CLASS_MAPPINGS)
        self.assertIn("H3OptionalReferenceMedia", package.NODE_CLASS_MAPPINGS)
        self.assertIn(qwen.DEFAULT_MODEL, qwen.model_files())
        inputs = qwen.H3OfficialSkillQwenLocal.INPUT_TYPES()
        self.assertIn("image9", inputs["optional"])
        self.assertIn("reference_video", inputs["optional"])
        self.assertEqual(inputs["required"]["context_length"][1]["default"], 32768)

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            qwen.model_path("../../outside.gguf")

    def test_runtime_cleanup_on_success_and_failure(self):
        for fail in [False, True]:
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temp:
                response = io.BytesIO(b'{"status":"ok"}')
                opener = Mock()
                opener.open.return_value = response
                process = Mock()
                process.poll.return_value = None
                with patch.object(qwen, "runtime_path", return_value=Path(temp) / "llama-server.exe"), \
                     patch.object(qwen, "model_path", return_value=Path(temp) / "model.gguf"), \
                     patch.object(qwen.folder_paths, "get_temp_directory", return_value=temp), \
                     patch.object(qwen.urllib.request, "build_opener", return_value=opener), \
                     patch.object(qwen.subprocess, "Popen", return_value=process) as spawn, \
                     patch.object(qwen.mm, "unload_all_models") as unload, \
                     patch.object(qwen.mm, "soft_empty_cache"):
                    try:
                        with qwen.managed_server(qwen.DEFAULT_MODEL, False, 16384, 99) as (url, log):
                            self.assertTrue(url.startswith("http://127.0.0.1:"))
                            if fail:
                                raise ValueError("test failure")
                    except ValueError:
                        self.assertTrue(fail)
                    process.terminate.assert_called_once()
                    process.wait.assert_called_once_with(timeout=10)
                    unload.assert_called_once()
                    arguments = spawn.call_args.args[0]
                    self.assertIn("--offline", arguments)
                    self.assertIn("--no-webui", arguments)
                    self.assertIn("--reasoning", arguments)
                    self.assertEqual(arguments[arguments.index("--host") + 1], "127.0.0.1")
                    self.assertEqual(spawn.call_args.kwargs["creationflags"], qwen.subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
