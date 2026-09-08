import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import torch

PLUGIN = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("COMFYUI_ROOT", PLUGIN.parents[1])).resolve()
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("h3_official_test", PLUGIN / "nodes.py")
h3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h3)

BASE = "integrated_multimodal_description: [Shot 1] A cat walks through a garden.\n\noverall_soundscape: Soft footsteps.\n\nnon_diegetic_music: N/A"
REF = "subject_definitions: <Subject 1> is the cat from <Picture 1>.\n\nsummary: [reference generation] <Subject 1> walks.\n\nretention_analysis: <Subject 1> (appears in [Shot 1]): fully_preserved - appearance.\n\ndetailed_description: Natural daylight. [Shot 1] <Subject 1> walks through a garden.\n\noverall_soundscape: Soft footsteps.\n\nnon_diegetic_music: N/A"
REF_MEDIA = "subject_definitions: <Subject 1> is the cat from <Picture 1>, also visible in <Video 1>.\n\nsummary: [reference generation] <Subject 1> walks.\n\nretention_analysis: <Subject 1> (appears in [Shot 1]): fully_preserved - appearance and motion.\n\ndetailed_description: Natural daylight. [Shot 1] <Subject 1> walks through a garden while following the rhythm of <Audio 1>.\n\noverall_soundscape: Preserve the character of <Audio 2>.\n\nnon_diegetic_music: N/A"


class Tests(unittest.TestCase):
    def test_official_loading_and_frame_grid(self):
        for mode in h3.MODES:
            skill, frames, rules = h3.H3OfficialSkill().load(mode, 5.0)
            self.assertEqual(frames, 124)
            self.assertEqual(skill["duration"], 124 / 24)
            self.assertIn("# H3 Prompt Writing", rules)
            self.assertIn("# Video Prompt Writing Guide", rules)
            self.assertEqual("# Full-Reference Mode Rewrite Output Format Guide" in rules, mode == "Ref2VA")
        for seconds in [4, 4.5, 8, 10, 15]:
            skill, frames, _ = h3.H3OfficialSkill().load("T2VA", seconds)
            self.assertEqual(frames % 17, 5)
            self.assertEqual(skill["duration"], frames / 24)

    def test_valid_prompt(self):
        h3.check_prompt(BASE, "T2VA", 5.0, 0)
        h3.check_prompt(REF, "Ref2VA", 5.0, 1)
        h3.check_prompt(REF_MEDIA, "Ref2VA", 5.0, 1, 1, 2)

    def test_nine_images_and_media_helpers(self):
        pictures = " ".join(f"<Picture {index}>" for index in range(1, 10))
        prompt = REF.replace("<Picture 1>", pictures)
        h3.check_prompt(prompt, "Ref2VA", 5.0, 9)
        video = torch.zeros((12, 8, 8, 3))
        frames = h3.encode_video_frames(video, fps=6, max_frames=8)
        self.assertEqual(len(frames), 8)
        self.assertEqual(frames[0][1], 0)
        self.assertAlmostEqual(frames[-1][1], 11 / 6)
        audio = {"waveform": torch.zeros((1, 2, 48000)), "sample_rate": 48000}
        self.assertEqual(h3.audio_metadata(audio), "1.000s, 48000 Hz, 2 channel(s)")
        self.assertEqual(h3.H3OptionalReferenceMedia().load("(none)", "(none)"),
                         (None, None, 24.0, None))
        empty_images = {f"image{index}": "(none)" for index in range(1, 10)}
        self.assertIs(h3.H3OptionalReferenceImages.VALIDATE_INPUTS(**empty_images), True)
        self.assertEqual(h3.H3OptionalReferenceImages().load(**empty_images), (None,) * 9)

    def test_connected_media_must_be_referenced(self):
        with self.assertRaises(ValueError):
            h3.check_prompt(REF_MEDIA.replace("<Audio 2>", "ambient sound"),
                            "Ref2VA", 5.0, 1, 1, 2)

    def test_invalid_prompts(self):
        cases = [BASE.replace("overall_soundscape:", "bad_field:"),
                 BASE + "\noverall_soundscape: duplicate", BASE.replace("A cat", "<Audio 1> A cat"),
                 BASE.replace("A cat", "<Picture 1> A cat"),
                 BASE.replace("[Shot 1]", "[Shot 2]"),
                 BASE.replace("[Shot 1]", "[Shot 1] At 00:00.000,"),
                 BASE.replace("garden.", "garden. [Shot 2] At 00:06.000, cut."),
                 BASE.replace("garden.", "garden. [Shot 2] cut."),
                 BASE + "\n<d>unclosed", "```text\n" + BASE + "\n```"]
        for prompt in cases:
            with self.subTest(prompt=prompt), self.assertRaises(ValueError):
                h3.check_prompt(prompt, "T2VA", 5.0, 0)

    def test_missing_model_blocks_before_http(self):
        skill, _, _ = h3.H3OfficialSkill().load("T2VA", 5.0)
        with patch.object(h3, "local_request") as call, self.assertRaises(ValueError):
            h3.H3OfficialSkillOptimize().optimize(skill, "cat", "Ollama", "", "", 42, .3, 4096, 10)
        call.assert_not_called()

    def test_remote_urls_rejected(self):
        for url in ["https://example.com", "http://example.com", "http://127.0.0.1.evil.test", "http://user:secret@localhost:1234", "file:///tmp/foo"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                h3.local_request(url, {}, 1)

    def test_http_transport_and_repair(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captured.append(payload)
                content = "bad format" if len(captured) == 1 else BASE
                if self.path == "/api/chat":
                    result = {"message": {"content": content}, "done_reason": "stop"}
                else:
                    result = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            skill, _, _ = h3.H3OfficialSkill().load("T2VA", 5.0)
            for backend, path in [("Ollama", "/api/chat"), ("OpenAI-compatible local", "/v1/chat/completions")]:
                captured.clear()
                result, report = h3.H3OfficialSkillOptimize().optimize(skill, "a cat", backend,
                    f"http://127.0.0.1:{server.server_port}{path}", "test-fixture-not-real-llm", 42, .3, 4096, 10)
                self.assertEqual(result, BASE)
                self.assertEqual(len(captured), 2)
                self.assertIn(skill["rules"], captured[0]["messages"][0]["content"])
                self.assertEqual(len(captured[1]["messages"]), 4)
                self.assertIn("attempts: 2", report)
                if backend == "Ollama":
                    self.assertEqual(captured[0]["keep_alive"], 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_bad_repair_blocks(self):
        skill, _, _ = h3.H3OfficialSkill().load("T2VA", 5.0)
        with patch.object(h3, "local_request", return_value={"message": {"content": "bad"}}) as call:
            with self.assertRaises(RuntimeError):
                h3.H3OfficialSkillOptimize().optimize(skill, "a cat", "Ollama", "local", "fixture", 42, .3, 4096, 10)
        self.assertEqual(call.call_count, 2)

    def test_truncation_blocks(self):
        skill, _, _ = h3.H3OfficialSkill().load("T2VA", 5.0)
        with patch.object(h3, "local_request", return_value={"message": {"content": BASE}, "done_reason": "length"}):
            with self.assertRaises(RuntimeError):
                h3.H3OfficialSkillOptimize().optimize(skill, "cat", "Ollama", "local", "fixture", 42, .3, 4096, 10)

    def test_workflow_links(self):
        for file in (PLUGIN / "workflows").glob("H3_*.json"):
            data = json.loads(file.read_text(encoding="utf-8"))
            nodes = {n["id"]: n for n in data["nodes"]}
            self.assertEqual(len(nodes), len(data["nodes"]))
            for id, src, out, dst, inp, type in data["links"]:
                self.assertEqual(nodes[dst]["inputs"][inp]["link"], id)
                self.assertIn(id, nodes[src]["outputs"][out]["links"])
                self.assertEqual(nodes[src]["outputs"][out]["type"], type)
            if 136 in nodes:
                def source(name):
                    id = next(s["link"] for s in nodes[136]["inputs"] if s["name"] == name)
                    return next(l[1] for l in data["links"] if l[0] == id)
                self.assertEqual(source("prompt"), 142)
                self.assertEqual(source("length"), 141)
                self.assertEqual(source("ref_images.ref_image_0"), 137)
                self.assertEqual(source("ref_images.ref_image_8"), 137)
                self.assertEqual(source("ref_videos.ref_video_0"), 154)
                self.assertEqual(source("ref_video_audios.ref_video_audio_0"), 154)
                self.assertEqual(source("ref_audios.ref_audio_0"), 154)
                self.assertEqual(nodes[155]["type"], "LoraLoaderModelOnly")
                self.assertEqual(nodes[156]["type"], "MiniMaxH3MemoryEfficientSageAttentionPatch")
                self.assertNotIn("PathchSageAttentionKJ", {node["type"] for node in nodes.values()})


if __name__ == "__main__":
    unittest.main(verbosity=2)
