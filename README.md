# Frame Studio — Codex 游戏动画工作台

本地工作台：输入描述，调用 Codex 优化提示词，生成并确认首尾帧，生成 H3 视频，预览三个连续片段，并导出 PNG 序列、图集和动画信息。服务只监听本机 127.0.0.1，不上传项目素材到本工作台服务之外。Codex 及其模型服务的数据处理另按你的 Codex 配置执行。

## 已实现与限制

- Qwen-Image-2.1 本地文生图和参考图编辑；MiniMax H3 图生视频，内置 448×448、8 步和最多 5 秒的示例设置。
- 可上传首尾帧；用户确认后生成视频，再确认进入候选。尾帧约束可关闭。
- 三个候选是视频的开头、中间和结尾的连续 2 秒片段（不做动作语义识别或自动循环优化）。
- 可选择导出 8、12、24 FPS 的 PNG 序列及固定 6 列图集；可选浅灰色键抠图。颜色键适用于背景接近浅灰的画面，可能损失角色细节或产生边缘，请务必目检；不是 AI 抠图或帧间遮罩稳定。
- 任务一次只运行一个；生成过程中保持服务运行。模型和硬件兼容性、首次运行时间因机器而异。
- Codex 优化由单独的 `codex exec` 进程执行，需已安装并登录 Codex，可能受账号、权限及网络影响；也可以自行编辑描述。

## 前置条件

1. Python 3.10+ 和 Pillow：`python -m pip install -r requirements.txt`。
2. 已安装、可运行的 ComfyUI；本项目不会自动安装 PyTorch、显卡驱动或模型。
3. FFmpeg 和 ffprobe 可运行；如不在 PATH 中，在配置中填写 FFmpeg 可执行文件的绝对路径。
4. 本机已安装并登录 Codex，供“让 Codex 优化”按钮调用。
5. 在 ComfyUI 安装以下模型（文件名与工作流一致）：
   - `models/diffusion_models/qwen_image_2.1_int8_convrot.safetensors`
   - `models/text_encoders/qwen3vl_8b_int8_convrot.safetensors`
   - `models/vae/qwen_image_2.1_vae_bf16.safetensors`
   - `models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors`
   - `models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`
   - `models/vae/minimax_h3_video_vae_fp16.safetensors` 和 `minimax_h3_audio_vae_fp32.safetensors`
   - `models/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors`

以 [Qwen 官方工作流及下载](https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1) 和 [MiniMax H3 官方工作流](https://docs.comfy.org/tutorials/video/minimax/minimax-h3) 为准。请分别核对模型许可证，尤其是商业使用。模型文件不包含在本项目中。

## 配置与启动

复制 `config.example.json` 为 `config.json`，填写 `comfy_path`（ComfyUI 根目录或 Windows portable 根目录）、`comfy_url` 和 `ffmpeg_path`。这个文件被 Git 忽略。也可使用环境变量 `GAME_ART_COMFY`、`GAME_ART_COMFY_URL`、`GAME_ART_FFMPEG` 覆盖。

先按本机平台启动 ComfyUI，再在项目目录运行：

```text
python server.py
```

浏览器打开 http://127.0.0.1:8765 。工作台只支持本机连接的 ComfyUI；它需要读取本机 ComfyUI 输入输出目录。

Windows NVIDIA 使用与你的显卡匹配的 CUDA 版 PyTorch；AMD AI Max 395 应按 AMD 官方文档安装支持对应系统的 ROCm/PyTorch；macOS 或其他 GPU 的模型和节点兼容性必须单独验证。安装了 Codex 并不代表硬件、模型和运行环境已满足要求。本项目当前在 Windows + RTX 3090 上开发，其他平台尚未实测。

项目及导出写入 `projects/`，不会被 Git 跟踪；不要将本地配置、图片、视频或模型提交到公开仓库。

如 Codex CLI 默认模型与登录账号不兼容，在 config.json 中设置 codex_model 为该 CLI 和账号实际支持的模型；留空则使用 Codex 默认配置。优化失败时可直接手动编辑描述。

可选项 qwen_url 可以指定独立的原画 ComfyUI 服务；留空或与 comfy_url 相同时使用同一个服务。使用不同服务时，工作台会在切换生成任务前请求另一服务释放模型显存。两者必须使用同一台机器和同一个 ComfyUI 输入/输出目录。环境变量 GAME_ART_QWEN_URL 可覆盖该设置。
