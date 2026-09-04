# ComfyUI MiniMax H3 官方 Skill + 本地 Qwen3.8

[English](README.md) | [简体中文](README_zh-CN.md)

这是两个用于 ComfyUI 的工作流：输入中文创意描述和一至两张参考图，
由本地 Qwen3.8-27B 视觉语言模型自动生成符合 MiniMax H3 官方规则的提示词。

自定义节点会自动完成以下流程：

1. 加载固定版本的 MiniMax H3 官方 prompt-writing Skill。
2. 启动仅限本机访问、离线运行的 llama.cpp 服务。
3. 让 Qwen 分析参考图并改写创意描述。
4. 检查 H3 字段顺序、参考素材编号、主体定义、镜头和时间点。
5. 格式不合格时自动修复一次。
6. 关闭 Qwen 并释放显存，然后再开始 H3 视频生成。

不需要 API 密钥、Ollama 或 LM Studio。模型权重和第三方运行库不会提交到
GitHub，而是在安装时从固定上游版本下载并校验。

## 工作流

- workflows/H3_QwenLocal_PromptOnly.json：仅生成并检查优化后的提示词，
  不渲染视频，建议第一次先使用这个版本。
- workflows/H3_QwenLocal_Ref2VA.json：提示词优化器直接连接 MiniMax H3
  Ref2VA 视频和音频生成链。

完整工作流会自动继续生成视频，提示词预览节点不是人工审批关卡。

## 已测试配置

- Windows 11
- ComfyUI 0.30.0 便携版
- NVIDIA RTX 5090 Laptop，24GB 显存
- 64GB 系统内存
- Qwen3.8-27B UD-Q4_K_M 和 F16 视觉投影器
- llama.cpp b10621 Windows CUDA 13.3 版本

真实图片改写测试耗时 316.4 秒。每两秒采样一次的整机显存峰值为
17,812MiB，Qwen 退出后恢复到 254MiB。提示词第一次输出即通过结构检查。
这是偏向质量的 27B 配置，不属于快速方案。

建议使用 24GB 显存的 NVIDIA GPU 和至少 32GB 内存。显存更少时可以降低
节点中的 gpu_layers，但速度会明显下降。仓库提供的自动运行库安装目前只
支持 Windows 和 NVIDIA GPU。

## 前置条件

1. 已安装支持 MiniMax H3 节点的较新版本 ComfyUI。
2. 已安装 Git 和 PowerShell 7 或更高版本。
3. Qwen 需要约 18GB 空间，H3 模型需要另外计算空间。
4. 完整 Ref2VA 工作流需要以下文件：

| ComfyUI 目录 | 文件名 |
| --- | --- |
| models/unet | minimax_h3_ref2va_pruned_int8_convrot.safetensors |
| models/text_encoders | qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors |
| models/vae | minimax_h3_video_vae_fp16.safetensors |
| models/vae | minimax_h3_audio_vae_fp32.safetensors |

工作流 JSON 中包含 ComfyUI 模型下载信息。缺少文件时，可以使用 ComfyUI
的模型下载功能或 Manager，也可以查看
[Comfy-Org MiniMax-H3 模型仓库](https://huggingface.co/Comfy-Org/MiniMax-H3)。

本项目的安装脚本只下载 Qwen、官方 Skill 和 llama.cpp，不会自动下载体积
更大的 H3 模型。

## Windows 一键安装

在 ComfyUI/custom_nodes 目录中打开 PowerShell 7：

~~~powershell
git clone https://github.com/basil-hayden/ComfyUI-H3-OfficialSkill-QwenLocal.git
cd ComfyUI-H3-OfficialSkill-QwenLocal
pwsh -ExecutionPolicy Bypass -File .\install_windows.ps1
~~~

安装脚本会：

- 确认仓库位于 ComfyUI/custom_nodes 目录。
- 下载固定提交版本的三个 H3 官方 Skill 文件。
- 下载并解压固定版本的 llama.cpp CUDA 运行库。
- 将两个 Qwen GGUF 文件分成可续传的 32MiB 数据块下载。
- 对每个文件执行 SHA256 校验。
- 将两个工作流复制到 ComfyUI/user/default/workflows。

下载中断后再次运行相同命令即可续传。临时数据位于不会提交到 Git 的
download-cache 目录，校验成功后会自动删除。

常用安装选项：

~~~powershell
# 只安装官方规则和工作流
pwsh -File .\install_windows.ps1 -SkipModel -SkipRuntime

# 网络不稳定时减少并行下载数
pwsh -File .\install_windows.ps1 -ParallelDownloads 4

# 不把工作流复制到用户目录
pwsh -File .\install_windows.ps1 -SkipWorkflowCopy
~~~

安装完成后重启 ComfyUI，先打开 H3_QwenLocal_PromptOnly。

## 使用方法

1. 替换示例参考图。
2. 用中文或英文填写创意描述。
3. 运行 H3_QwenLocal_PromptOnly，检查提示词和验证报告两个输出。
4. 在创意描述中明确写出角色身份、服装和其他关键外观细节。
5. 确认内容后，用相同图片和描述运行 H3_QwenLocal_Ref2VA。

使用两张图片时，必须将两张图以相同顺序同时连接到优化器和 H3。本节点
不会自动分析参考视频或参考音频，但 H3 仍然可以生成对白、环境声和配乐。

官方 Skill 要求各字段正文使用英文；用户指定的对白、歌词和画面文字会
保留原语言。输入 5 秒会按照 H3 的帧网格对齐为 124 帧，在 24fps 下实际
约为 5.17 秒。

## 验证范围

出现以下问题时，节点会拒绝结果：

- 必需字段缺失、重复或顺序错误。
- 提示词引用了没有连接的素材编号。
- 主体没有按照官方格式定义。
- 镜头编号或切换时间不合法。
- 用户用引号明确指定的原文丢失。

修复失败时不会偷偷退回未经优化的原始描述。

这些检查只能保证结构，不能保证语义完全准确。视觉模型仍可能误认参考图
细节。真实测试中，Qwen 曾把一个黄色耳状结构描述为头发。因此在长时间
渲染之前，务必检查角色身份、动作、镜头、声音和文字。

## 安全与显存管理

- llama.cpp 只监听随机的 127.0.0.1 端口。
- 使用离线模式，并关闭 llama.cpp 网页界面。
- HTTP 客户端拒绝远程地址、重定向、代理和 URL 内嵌凭据。
- Qwen 启动前会卸载 ComfyUI 当前占用 GPU 的模型。
- 无论成功或报错，本节点创建的 Qwen 进程都会被关闭。
- Qwen 与 H3 串行使用显存，不会同时常驻显存。

## 固定版本与文件校验

完整下载地址、版本、字节数和 SHA256 位于 qwen_artifacts.json 和
install_windows.ps1。

- MiniMax H3 Skill：d21241f0a4b3acbb34c97dae47fa417b7065e438
- Qwen GGUF：4ca720788d1e01f1bff70c033e0d0028fd02e502
- llama.cpp：b10621，对应 v0.3.0 稳定通道

节点采用 Qwen 发布页面建议的非思考采样参数：temperature 0.7、top-p
0.8、top-k 20、min-p 0、presence penalty 1.5、repetition penalty 1.0。

## 开发测试

仓库安装在 custom_nodes 下并准备好官方 Skill 文件后，可以运行：

~~~powershell
$env:COMFYUI_ROOT = 'C:\path\to\ComfyUI'
& "$env:COMFYUI_ROOT\..\python_embeded\python.exe" -s .\tests\test_h3_official.py
& "$env:COMFYUI_ROOT\..\python_embeded\python.exe" -s .\tests\test_qwen_managed.py
~~~

当前版本通过了 12 项自动化测试和 ComfyUI 工作流原生校验，并使用真实
图片完成过 Qwen 优化测试。本项目尚未对完整 H3 视频渲染进行基准测试。

## 来源与许可

桥接代码和工作流使用 MIT 许可证。第三方模型、运行库和 MiniMax 官方
Skill 遵循各自的上游条款，不包含在本仓库中。详情参阅 NOTICE.md。

- [MiniMax H3 官方 Skill](https://github.com/MiniMax-AI/MiniMax-H3/tree/d21241f0a4b3acbb34c97dae47fa417b7065e438/skills/h3-prompt-writing)
- [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)
- [Unsloth Qwen3.8-27B GGUF](https://huggingface.co/unsloth/Qwen3.8-27B-GGUF)
- [llama.cpp b10621](https://github.com/ggml-org/llama.cpp/releases/tag/b10621)

这是独立集成项目，不代表 MiniMax、Qwen、Unsloth、llama.cpp 或 ComfyUI
官方。
