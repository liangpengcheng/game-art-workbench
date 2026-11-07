"""Read-only environment check; does not download or install software."""
import importlib.util,json,os,platform,shutil,subprocess,sys,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent
config_file=root/'config.json'
config=json.loads(config_file.read_text(encoding='utf-8-sig')) if config_file.exists() else {}
base=Path(os.environ.get('GAME_ART_COMFY',config.get('comfy_path',''))).expanduser()
comfy=base/'ComfyUI' if (base/'ComfyUI').is_dir() else base
models=['diffusion_models/qwen_image_2.1_int8_convrot.safetensors','text_encoders/qwen3vl_8b_int8_convrot.safetensors','vae/qwen_image_2.1_vae_bf16.safetensors','diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors','text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors','vae/minimax_h3_video_vae_fp16.safetensors','vae/minimax_h3_audio_vae_fp32.safetensors','loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors']
print('System:',platform.system(),platform.machine());print('Python:',sys.version.split()[0]);print('Pillow:',bool(importlib.util.find_spec('PIL')))
print('Codex:',bool(shutil.which('codex') or shutil.which('codex.cmd')))
ff=os.environ.get('GAME_ART_FFMPEG',config.get('ffmpeg_path','ffmpeg'));print('FFmpeg:',bool(shutil.which(ff) or Path(ff).is_file()))
print('ComfyUI path:',str(comfy),'exists:',(comfy/'main.py').is_file())
for model in models: print(('OK      ' if (comfy/'models'/model).is_file() else 'MISSING ')+model)
for label,url in [('video',os.environ.get('GAME_ART_COMFY_URL',config.get('comfy_url','http://127.0.0.1:8188'))),('image',os.environ.get('GAME_ART_QWEN_URL',config.get('qwen_url',config.get('comfy_url','http://127.0.0.1:8188'))))]:
    try:
        with urllib.request.urlopen(url+'/system_stats',timeout=3) as f: s=json.load(f)
        print(label,'service:',url,'OK, PyTorch',s.get('system',{}).get('pytorch_version','unknown'))
    except Exception as e: print(label,'service:',url,'unavailable:',str(e))
if shutil.which('nvidia-smi'):
    r=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],capture_output=True,text=True);print('NVIDIA:',r.stdout.strip())
print('This check does not establish GPU/backend/model compatibility; run an actual generation test.')
