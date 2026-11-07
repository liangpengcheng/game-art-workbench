# Frame Studio — Codex 游戏动画工作台

本地工作台：输入动作描述，生成或上传首尾帧及多个中间关键帧，确认后生成 H3 视频；可编辑时间范围、帧率和循环起点，预览完整动作并导出 PNG 序列、图集和动画信息。服务只监听本机 127.0.0.1。

## 已实现与限制

- Qwen-Image-2.1 本地文生图和参考图编辑；MiniMax H3 图生视频，448×448、8 步，时长可设置 0.5～15 秒。模型会按 24 FPS 的有效帧数生成后裁剪；长时长会更慢且更占内存。
- 可生成或上传首尾帧，最多增加 8 个中间关键帧并指定时间；通过 H3 Add Guide 节点锚定。上传的 PNG 透明通道保留，输入视频模型前合成到浅灰色背景。待机模式采用单动作约束并默认生成相同首尾图。
- 候选默认覆盖整个视频，也可按秒选定连续范围、帧率和三个起点偏移值。偏移采用循环换位，保留完整范围的全部帧，不会自动补帧、修复接缝或消除额外动作。
- 动画候选提供棋盘格透明预览，自动从视频角落取样背景色，也可手动调整颜色及容差。导出按所选候选顺序输出 PNG 序列和固定 6 列图集。颜色键只是近似抠图，容易误删相似颜色、保留阴影或产生边缘，须目检；不是 AI 抠图或帧间遮罩稳定。MP4 视频本身不包含透明通道。
- 任务一次只运行一个；生成过程中保持服务运行。模型和硬件兼容性、首次运行时间因机器而异。
- 自动附加单角色、固定镜头和纯色背景等约束；待机模式额外要求原地细微动作、不新增道具、不切镜头。模型仍可能偏离，须预览并重试。

## 前置条件

1. Python 3.10+ 和 Pillow：`python -m pip install -r requirements.txt`。
2. 已安装、可运行的 ComfyUI；本项目不会自动安装 PyTorch、显卡驱动或模型。
3. FFmpeg 和 ffprobe 可运行；如不在 PATH 中，在配置中填写 FFmpeg 可执行文件的绝对路径。
4. Codex 是可选的操作助手；工作台不再依赖 Codex CLI 优化提示词。
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

工作台不会调用 Codex 来改写提示词。

可选项 qwen_url 可以指定独立的原画 ComfyUI 服务；留空或与 comfy_url 相同时使用同一个服务。使用不同服务时，工作台会在切换生成任务前请求另一服务释放模型显存。两者必须使用同一台机器和同一个 ComfyUI 输入/输出目录。环境变量 GAME_ART_QWEN_URL 可覆盖该设置。

安装前可运行 `python doctor.py` 检查本地依赖、服务和必需模型。此检查不会安装模型或驱动，也不能代替实际生成测试。要在 Codex 中启用仓库附带的 Skill，可将 `skills/game-art-workbench` 复制到 Codex 的用户 skills 目录；新会话会加载可发现的 Skill。
