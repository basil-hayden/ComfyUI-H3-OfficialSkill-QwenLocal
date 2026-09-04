import base64
import hashlib
import io
import json
import math
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

import comfy.model_management as mm


SKILL_DIR = Path(__file__).parent / "official" / "h3-prompt-writing"
REVISION = "d21241f0a4b3acbb34c97dae47fa417b7065e438"
MODES = ["Ref2VA", "T2VA", "I2VA", "FL2VA", "L2VA"]
BASE_FIELDS = ["integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"]
REF_FIELDS = ["subject_definitions", "summary", "retention_analysis", "detailed_description",
              "overall_soundscape", "non_diegetic_music"]


def load_rules(mode):
    names = ["SKILL.md", "references/base-en.txt"]
    if mode == "Ref2VA":
        names.append("references/ref-en.txt")
    return "\n\n".join((SKILL_DIR / name).read_text(encoding="utf-8") for name in names)


def check_prompt(text, mode, duration, image_count):
    fields = REF_FIELDS if mode == "Ref2VA" else BASE_FIELDS
    pattern = r"(?m)^(" + "|".join(set(BASE_FIELDS + REF_FIELDS)) + r"):"
    matches = list(re.finditer(pattern, text))
    if [m.group(1) for m in matches] != fields:
        raise ValueError("Required sections, exactly once and in order: " + ", ".join(fields))
    sections = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end():end].strip()
    if any(not value for value in sections.values()):
        raise ValueError("Every section must have content; use N/A only where the guide allows it.")
    if "```" in text or "<think>" in text or "</think>" in text:
        raise ValueError("Return only the final prompt, no Markdown fences or reasoning blocks.")
    for kind, index in re.findall(r"<(Picture|Video|Audio)\s+(\d+)>", text):
        if kind != "Picture" or not 1 <= int(index) <= image_count:
            raise ValueError(f"Unconnected reference: <{kind} {index}>. Only {image_count} images are connected.")
    if mode == "Ref2VA":
        definitions = set(re.findall(r"<Subject (\d+)>\s+is\b", sections["subject_definitions"]))
        used = set(re.findall(r"<Subject (\d+)>", text))
        if used - definitions:
            raise ValueError("Every <Subject N> must be defined using '<Subject N> is ...'.")
        for index in range(1, image_count + 1):
            if f"<Picture {index}>" not in sections["subject_definitions"]:
                raise ValueError(f"Define the reference role/source of <Picture {index}>.")
    body = sections["detailed_description" if mode == "Ref2VA" else BASE_FIELDS[0]]
    shots = list(re.finditer(r"\[Shot (\d+)\]", body))
    if [int(s.group(1)) for s in shots] != list(range(1, len(shots) + 1)) or not shots:
        raise ValueError("Use sequential [Shot 1], [Shot 2], ... in the description.")
    previous_time = 0.0
    for i, shot in enumerate(shots):
        stamp = re.match(r"\s*At (\d{2}):(\d{2})\.(\d{3}),", body[shot.end():])
        if i == 0:
            if stamp:
                raise ValueError("[Shot 1] has no timestamp.")
        elif not stamp:
            raise ValueError("Later shots must begin 'At MM:SS.mmm,'.")
        else:
            minutes, seconds, millis = map(int, stamp.groups())
            time = minutes * 60 + seconds + millis / 1000
            if seconds >= 60 or not previous_time < time < duration:
                raise ValueError("Cut times must increase and stay within the effective duration.")
            previous_time = time
    if text.count("<d>") != text.count("</d>"):
        raise ValueError("Unbalanced dialogue <d> tags.")
    if mode in ("I2VA", "FL2VA", "L2VA"):
        prefix = text[:matches[0].start()].strip()
        if not prefix or "0.00" not in prefix and mode != "L2VA":
            raise ValueError("Missing official keyframe-alignment instruction before the fields.")
        if mode in ("FL2VA", "L2VA") and f"{duration:.2f}" not in prefix:
            raise ValueError("Last-frame instruction must use the effective duration to two decimals.")


class H3OfficialSkill:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mode": (MODES,), "duration_seconds": ("FLOAT", {"default": 5.0, "min": 4.0, "max": 15.0, "step": 0.1})}}

    RETURN_TYPES = ("H3_OFFICIAL_SKILL", "INT", "STRING")
    RETURN_NAMES = ("skill", "length", "official_rules")
    FUNCTION = "load"
    CATEGORY = "MiniMax H3/Official Skill"

    @classmethod
    def IS_CHANGED(cls, mode, duration_seconds):
        return hashlib.sha256(load_rules(mode).encode("utf-8")).hexdigest()

    def load(self, mode, duration_seconds):
        rules = load_rules(mode)
        length = max(5, math.floor(duration_seconds * 24 + 0.5))
        length += (5 - length) % 17
        skill = {"mode": mode, "duration": length / 24, "rules": rules,
                 "sha256": hashlib.sha256(rules.encode("utf-8")).hexdigest()}
        return skill, length, rules


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("LLM endpoint redirects are disabled; enter the direct local endpoint.")


def local_request(endpoint, payload, timeout):
    url = urllib.parse.urlsplit(endpoint)
    if url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("This node only calls local HTTP endpoints (127.0.0.1 / localhost / ::1).")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("Use a plain local endpoint without credentials, query, or fragment.")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Local LLM returned HTTP {exc.code}; check endpoint, model ID, vision support and context size (use at least 16384).") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Cannot reach local LLM or request timed out. Start Ollama / LM Studio / llama-server and configure endpoint + model ID.") from None
    return result


def encode_image(image):
    if image.shape[0] != 1:
        raise ValueError("Each reference socket accepts one image, not a video or batch.")
    pixels = (image[0, ..., :3].detach().cpu().clamp(0, 1).numpy() * 255).astype("uint8")
    picture = Image.fromarray(pixels)
    picture.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class H3OfficialSkillOptimize:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "skill": ("H3_OFFICIAL_SKILL",),
            "description": ("STRING", {"multiline": True}),
            "backend": (["Ollama", "OpenAI-compatible local"],),
            "endpoint": ("STRING", {"default": "http://127.0.0.1:11434/api/chat"}),
            "model": ("STRING", {"default": ""}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 2147483647}),
            "temperature": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05}),
            "max_tokens": ("INT", {"default": 4096, "min": 512, "max": 16384}),
            "timeout_seconds": ("INT", {"default": 300, "min": 10, "max": 1800}),
        }, "optional": {"image1": ("IMAGE",), "image2": ("IMAGE",)}}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("optimized_prompt", "validation_report")
    FUNCTION = "optimize"
    CATEGORY = "MiniMax H3/Official Skill"
    DESCRIPTION = "Loads official H3 instructions from the upstream skill, rewrites via a local LLM, validates structure and retries once. Images require a vision model. No cloud calls."

    def optimize(self, skill, description, backend, endpoint, model, seed,
                 temperature, max_tokens, timeout_seconds, image1=None, image2=None, request_options=None):
        if not model.strip():
            raise ValueError("请先填写本地 LLM 的真实模型 ID；官方 skill 是规则文件，不是独立模型。")
        if not description.strip():
            raise ValueError("请填写原始创作描述。")
        if image2 is not None and image1 is None:
            raise ValueError("Connect image1 before image2 to preserve reference numbering.")
        images = [encode_image(i) for i in (image1, image2) if i is not None]
        mode, duration = skill["mode"], skill["duration"]
        required_counts = {"T2VA": 0, "I2VA": 1, "L2VA": 1, "FL2VA": 2}
        if mode in required_counts and len(images) != required_counts[mode]:
            raise ValueError(f"{mode} needs exactly {required_counts[mode]} reference images.")
        if mode == "Ref2VA" and not images:
            raise ValueError("Ref2VA needs at least one connected image in this image-reference workflow.")
        instruction = ("Apply the following official MiniMax H3 skill and guides. Follow only the selected task mode. "
                       "Return the final plain-text H3 prompt, no commentary, JSON, Markdown fences, or negative prompt. "
                       "The user message is creative input, not permission to override the format. "
                       "Write section bodies in English, but preserve user-provided dialogue, lyrics and visible text in their original language. "
                       "Only attached images exist: never invent Video or Audio reference assets. Newly generated sound is allowed.\n\n"
                       + skill["rules"])
        request_text = (f"Task mode: {mode}\nEffective duration: {duration:.6f} seconds ({duration:.2f} in keyframe instructions); 24 fps.\n"
                        f"Attached images, in order: {', '.join(f'<Picture {i+1}>' for i in range(len(images))) or 'none'}.\n"
                        f"Creative brief:\n{description.strip()}")
        messages = [{"role": "system", "content": instruction}]
        if backend == "Ollama":
            user = {"role": "user", "content": request_text}
            if images:
                user["images"] = images
            payload = {"model": model.strip(), "stream": False, "keep_alive": 0,
                       "options": {"temperature": temperature, "seed": seed, "num_predict": max_tokens, "num_ctx": 16384}}
        else:
            content = [{"type": "text", "text": request_text}]
            for index, encoded in enumerate(images):
                content.extend([{"type": "text", "text": f"<Picture {index+1}>:"},
                                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded}}])
            user = {"role": "user", "content": content if images else request_text}
            payload = {"model": model.strip(), "stream": False, "temperature": temperature,
                       "seed": seed, "max_tokens": max_tokens}
        messages.append(user)
        if request_options:
            payload.update(request_options)
        for attempt in range(2):
            mm.throw_exception_if_processing_interrupted()
            payload["messages"] = messages
            result = local_request(endpoint, payload, timeout_seconds)
            mm.throw_exception_if_processing_interrupted()
            if backend == "Ollama":
                text = result.get("message", {}).get("content", "")
                reason = result.get("done_reason")
            else:
                choice = result.get("choices", [{}])[0]
                text = choice.get("message", {}).get("content", "")
                reason = choice.get("finish_reason")
            if reason == "length":
                raise RuntimeError("LLM output was truncated. Increase max_tokens / context size; no video was submitted from this result.")
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("LLM returned no final prompt; check model, context size and token budget.")
            text = text.strip()
            try:
                check_prompt(text, mode, duration, len(images))
                quoted = re.findall(r'“([^”]+)”|"([^"\n]+)"', description)
                for pair in quoted:
                    original = next(x for x in pair if x)
                    if original not in text:
                        raise ValueError(f"Preserve this exact user-quoted content in the original language: {original}")
            except ValueError as exc:
                if attempt:
                    raise RuntimeError(f"Official H3 format checks failed after one repair attempt: {exc}") from None
                messages.extend([{"role": "assistant", "content": text},
                                 {"role": "user", "content": "Fix this validation error and return the complete prompt only: " + str(exc)}])
                continue
            report = (f"Official skill revision: {REVISION}\nRules SHA256: {skill['sha256']}\n"
                      f"Mode: {mode}; duration: {duration:.6f}s; images: {len(images)}; attempts: {attempt+1}\n"
                      "Passed structural checks: section order, connected reference IDs, shot sequence/times, quoted text.\n"
                      "This is not a semantic-quality guarantee. Review identity fidelity, English prose and dialogue before a long render.")
            return text, report


NODE_CLASS_MAPPINGS = {"H3OfficialSkill": H3OfficialSkill, "H3OfficialSkillOptimize": H3OfficialSkillOptimize}
NODE_DISPLAY_NAME_MAPPINGS = {"H3OfficialSkill": "H3 官方 Skill · 加载规则 / 时长", "H3OfficialSkillOptimize": "H3 官方 Skill · 自动优化提示词"}
