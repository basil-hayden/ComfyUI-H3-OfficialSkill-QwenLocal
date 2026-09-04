# ComfyUI MiniMax H3 + Official Skill + Local Qwen3.8

[English](README.md) | [简体中文](README_zh-CN.md)

Two ComfyUI workflows that turn a Chinese creative brief and one or two reference
images into a MiniMax H3 prompt using a fully local Qwen3.8-27B vision-language
model.

The node loads the pinned MiniMax H3 prompt-writing skill, starts an offline
llama.cpp server, asks Qwen to inspect the image and rewrite the brief, validates
the H3 structure, retries one repair when needed, then closes Qwen and releases
VRAM before H3 video generation starts.

No API key, Ollama or LM Studio is required. Model weights and third-party
binaries are downloaded during installation and are never committed here.

## Included workflows

- workflows/H3_QwenLocal_PromptOnly.json: inspect the optimized prompt and
  validation report without rendering video.
- workflows/H3_QwenLocal_Ref2VA.json: the optimizer connected directly to a
  MiniMax H3 Ref2VA video/audio generation chain.

The full workflow is automated; its preview node is not an approval gate.

## Tested configuration

- Windows 11 and ComfyUI 0.30.0 portable
- NVIDIA RTX 5090 Laptop with 24 GB VRAM; 64 GB system RAM
- Qwen3.8-27B UD-Q4_K_M with F16 vision projector
- llama.cpp b10621 Windows CUDA 13.3 build

A real image-to-prompt run took 316.4 seconds. Total GPU memory sampled every two
seconds peaked at 17,812 MiB and returned to 254 MiB after Qwen exited. Prompt
structure passed on the first attempt. This is a quality-oriented 27B setup, not
a fast setup.

Recommended: NVIDIA GPU with 24 GB VRAM and at least 32 GB RAM. Less VRAM can
work by lowering gpu_layers, but it will be slower. The supplied automatic
runtime installer is Windows/NVIDIA only.

## Prerequisites

1. A current ComfyUI installation with MiniMax H3 nodes.
2. Git and PowerShell 7 or newer.
3. About 18 GB free space for Qwen, plus the separate H3 models.
4. These H3 files for the full Ref2VA workflow:

| ComfyUI folder | Filename |
| --- | --- |
| models/unet | minimax_h3_ref2va_pruned_int8_convrot.safetensors |
| models/text_encoders | qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors |
| models/vae | minimax_h3_video_vae_fp16.safetensors |
| models/vae | minimax_h3_audio_vae_fp32.safetensors |

The workflow contains ComfyUI model metadata. If a file is missing, use
ComfyUI's model downloader/Manager or follow the
[Comfy-Org MiniMax-H3 repository](https://huggingface.co/Comfy-Org/MiniMax-H3).
This installer downloads Qwen, the official skill and llama.cpp; it does not
download the much larger H3 weights.

## One-command Windows installation

Open PowerShell 7 in ComfyUI/custom_nodes:

~~~powershell
git clone https://github.com/basil-hayden/ComfyUI-H3-OfficialSkill-QwenLocal.git
cd ComfyUI-H3-OfficialSkill-QwenLocal
pwsh -ExecutionPolicy Bypass -File .\install_windows.ps1
~~~

The installer verifies its location, downloads the three official H3 skill
files, downloads and extracts the pinned llama.cpp runtime, downloads both Qwen
GGUF files in resumable 32 MiB ranges, verifies all SHA256 hashes, and copies the
two workflows into ComfyUI/user/default/workflows.

Interrupted model downloads resume when the command is run again. Temporary
chunks live under the ignored download-cache directory and are removed after
successful verification.

Useful switches:

~~~powershell
pwsh -File .\install_windows.ps1 -SkipModel -SkipRuntime
pwsh -File .\install_windows.ps1 -ParallelDownloads 4
pwsh -File .\install_windows.ps1 -SkipWorkflowCopy
~~~

After installation, restart ComfyUI and open H3_QwenLocal_PromptOnly first.

## Usage

1. Replace the example image.
2. Enter the creative description in Chinese or English.
3. Run H3_QwenLocal_PromptOnly and review both text outputs.
4. State important identity details explicitly in the creative description.
5. Use H3_QwenLocal_Ref2VA with the same image and brief.

For two images, connect both to the optimizer and H3 in the same order. The node
does not analyze reference video or audio. H3 may still generate dialogue,
ambience and music.

The official skill expects English section bodies; user-provided dialogue,
lyrics and visible text remain in their original language. Five seconds is
aligned to 124 frames at 24 fps, or about 5.17 seconds.

## Validation limits

The node rejects missing or out-of-order fields, unconnected reference IDs,
undefined subjects, invalid shot numbering/timing, and lost exact quoted user
text. It never silently falls back to the raw brief after failed optimization.

This is structural validation, not a semantic guarantee. A VLM can misidentify
visual details. In the real test, Qwen described an ear-like yellow shape as
hair. Review identity, motion, camera, audio and text before a long H3 render.

## Security and resources

- The managed server listens on a random 127.0.0.1 port only.
- llama.cpp uses offline mode with its web UI disabled.
- The client rejects remote endpoints, redirects, proxies and URL credentials.
- Existing ComfyUI GPU models are unloaded before Qwen starts.
- The Qwen process is terminated in success and error paths.
- H3 and Qwen use VRAM sequentially, not simultaneously.

## Pinned versions and integrity

Exact URLs, revisions, byte sizes and hashes are in qwen_artifacts.json and
install_windows.ps1.

- MiniMax H3 skill: d21241f0a4b3acbb34c97dae47fa417b7065e438
- Qwen GGUF: 4ca720788d1e01f1bff70c033e0d0028fd02e502
- llama.cpp: b10621 / v0.3.0 stable channel

Qwen's published non-thinking settings are used: temperature 0.7, top-p 0.8,
top-k 20, min-p 0, presence penalty 1.5 and repetition penalty 1.0.

## Development checks

Install the repository under custom_nodes and run:

~~~powershell
$env:COMFYUI_ROOT = 'C:\path\to\ComfyUI'
& "$env:COMFYUI_ROOT\..\python_embeded\python.exe" -s .\tests\test_h3_official.py
& "$env:COMFYUI_ROOT\..\python_embeded\python.exe" -s .\tests\test_qwen_managed.py
~~~

The tested release passed 12 automated tests and native ComfyUI validation for
the workflows. The real Qwen optimizer was exercised with an image. A complete
H3 video render has not been benchmarked by this project.

## Attribution and license

The bridge code and workflows are MIT-licensed. Third-party weights, binaries
and the MiniMax skill use their upstream terms and are not redistributed here.
See NOTICE.md.

- [MiniMax H3 skill](https://github.com/MiniMax-AI/MiniMax-H3/tree/d21241f0a4b3acbb34c97dae47fa417b7065e438/skills/h3-prompt-writing)
- [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Unsloth Qwen3.8-27B GGUF](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF)
- [llama.cpp b10621](https://github.com/ggml-org/llama.cpp/releases/tag/b10621)

This is an independent integration, not an official MiniMax, Qwen, Unsloth,
llama.cpp or ComfyUI project.
