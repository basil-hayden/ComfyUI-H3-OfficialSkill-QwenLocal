# Third-party components

This repository does not redistribute model weights, llama.cpp binaries, CUDA
runtime files, or the MiniMax prompt-writing skill text. `install_windows.ps1`
downloads them directly from their upstream projects at pinned revisions.

- Qwen3.8-27B model: Qwen team; see its upstream model card and license.
- Unsloth GGUF quantization: Apache-2.0 as shown by its Hugging Face repository.
- llama.cpp: MIT License, copyright the ggml authors.
- MiniMax H3 prompt-writing skill: copyright and terms belong to MiniMax and
  its contributors. It is fetched from a pinned commit and is not covered by
  this repository's MIT license.

The `workflows/` files contain ComfyUI graphs and refer to filenames only; they
do not contain any model weights.
