from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import comfy.model_management as mm
import folder_paths

from .nodes import H3OfficialSkillOptimize, NoRedirect


MODEL_DIR = Path(folder_paths.models_dir) / "LLM"
DEFAULT_MODEL = "Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q4_K_M.gguf"
RUNTIME_DIR = Path(__file__).parent / "runtime" / "llama-b10621"


def model_files():
    return sorted(p.relative_to(MODEL_DIR).as_posix() for p in MODEL_DIR.rglob("*.gguf")
                  if "mmproj" not in p.name.lower()) or [DEFAULT_MODEL]


def model_path(name):
    path = (MODEL_DIR / name).resolve()
    if not path.is_relative_to(MODEL_DIR.resolve()) or path.suffix.lower() != ".gguf":
        raise ValueError("Choose a GGUF model inside ComfyUI/models/LLM.")
    if not path.is_file():
        raise FileNotFoundError(f"Qwen GGUF not installed: {path}")
    return path


def runtime_path():
    candidates = list(RUNTIME_DIR.rglob("llama-server.exe"))
    if len(candidates) != 1:
        raise FileNotFoundError(f"Expected one official llama-server.exe in {RUNTIME_DIR}")
    return candidates[0]


@contextmanager
def managed_server(model, vision, context_length, gpu_layers):
    executable = runtime_path()
    weight = model_path(model)
    projector = weight.parent / "mmproj-F16.gguf"
    if vision and not projector.is_file():
        raise FileNotFoundError(f"Matching vision projector not installed: {projector}")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [str(executable), "-m", str(weight), "--alias", "h3-qwen-local",
               "--host", "127.0.0.1", "--port", str(port), "--offline", "--no-webui",
               "--ctx-size", str(context_length), "--parallel", "1", "--batch-size", "512",
               "--ubatch-size", "256", "--gpu-layers", str(gpu_layers), "--flash-attn", "on",
               "--jinja", "--reasoning", "off", "--chat-template-kwargs", '{"enable_thinking":false}',
               "--no-warmup"]
    if vision:
        command.extend(["--mmproj", str(projector), "--image-max-tokens", "1024"])
    mm.throw_exception_if_processing_interrupted()
    mm.unload_all_models()
    mm.soft_empty_cache()
    log_dir = Path(folder_paths.get_temp_directory()) / "h3-qwen"
    log_dir.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    environment = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
    environment["HF_HUB_OFFLINE"] = "1"
    process = None
    with tempfile.NamedTemporaryFile(prefix="qwen-", suffix=".log", dir=log_dir, delete=False) as log:
        log_path = Path(log.name)
        try:
            process = subprocess.Popen(command, cwd=executable.parent, env=environment,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 300
            url = f"http://127.0.0.1:{port}"
            while True:
                mm.throw_exception_if_processing_interrupted()
                if process.poll() is not None:
                    raise RuntimeError(f"Qwen runtime exited ({process.returncode}). See {log_path}")
                if time.monotonic() > deadline:
                    raise RuntimeError(f"Qwen model loading exceeded 300s. See {log_path}")
                try:
                    with opener.open(url + "/health", timeout=1) as response:
                        if json.load(response).get("status") == "ok":
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.25)
            yield url + "/v1/chat/completions", log_path
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            mm.soft_empty_cache()


class H3OfficialSkillQwenLocal:
    @classmethod
    def VALIDATE_INPUTS(cls, gguf_model):
        try:
            model_path(gguf_model)
            runtime_path()
        except (ValueError, FileNotFoundError) as exc:
            return str(exc)
        return True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "skill": ("H3_OFFICIAL_SKILL",),
            "description": ("STRING", {"multiline": True}),
            "gguf_model": (model_files(), {"default": DEFAULT_MODEL}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 2147483647}),
            "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.05}),
            "max_tokens": ("INT", {"default": 4096, "min": 512, "max": 16384}),
            "context_length": ("INT", {"default": 16384, "min": 16384, "max": 32768, "step": 4096}),
            "gpu_layers": ("INT", {"default": 99, "min": 0, "max": 99}),
        }, "optional": {"image1": ("IMAGE",), "image2": ("IMAGE",)}}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("optimized_prompt", "validation_report")
    FUNCTION = "optimize"
    CATEGORY = "MiniMax H3/Official Skill"
    DESCRIPTION = "ComfyUI-managed local Qwen GGUF: automatically starts an offline runtime, applies the complete official H3 skill and closes the runtime to release VRAM. No Ollama, LM Studio or cloud service required."

    def optimize(self, skill, description, gguf_model, seed, temperature, max_tokens,
                 context_length, gpu_layers, image1=None, image2=None):
        if not description.strip():
            raise ValueError("请填写原始创作描述。")
        vision = image1 is not None or image2 is not None
        with managed_server(gguf_model, vision, context_length, gpu_layers) as (endpoint, log_path):
            prompt, report = H3OfficialSkillOptimize().optimize(
                skill, description, "OpenAI-compatible local", endpoint, "h3-qwen-local",
                seed, temperature, max_tokens, 600, image1, image2,
                request_options={"top_p": 0.8, "top_k": 20, "min_p": 0.0,
                                 "presence_penalty": 1.5, "repeat_penalty": 1.0,
                                 "chat_template_kwargs": {"enable_thinking": False}})
        report += f"\nLocal GGUF: {gguf_model}\nQwen process closed; its GPU memory released.\nRuntime log: {log_path}"
        return prompt, report
