---
name: game-art-workbench
description: Use the local Frame Studio workbench to create or manage 2D game character animation projects using Codex, ComfyUI, Qwen Image, and MiniMax H3. Use when the user requests character keyframes, motion video, candidate sprite sequences, or export from this workbench.
---

# Game art workbench

Read the project README for current prerequisites and setup. This skill coordinates a local workbench; it does not itself install drivers or model weights.

1. Check whether the local workbench is running and whether its configured ComfyUI service is reachable. Resolve missing paths, dependencies and model weights using the README and model providers' official documentation. Treat model licenses and GPU/backend compatibility separately by machine.
2. Preserve the requested stages: use the user's brief with the workbench's game-animation constraints, create or use first, optional last, and timed intermediate keyframes, let the user approve the frames, generate a video, allow approval or regeneration, then preview and select a full-range animation with an editable loop offset before exporting.
3. Use the web interface or the local API to submit each stage. API mutations require the ephemeral token from GET `/api/config` in `X-Workbench-Token`; status is available at `/api/status`. Do not expose the token externally. The service is designed for localhost only.
4. Preserve the user's requested animation length, maximum dimensions, frame rate and output formats. Candidates preserve all sampled frames in the selected range; phase offsets only rotate the loop starting point and do not add frames or repair transitions. Color-key transparency is approximate; report its limits and inspect critical edges. Video itself remains opaque.
5. Report what actually completed and link deliverables. Never claim a generation or installation succeeded without observing its result. Do not commit models, project data, local paths, credentials, or generated files to a repository.
