import base64, json, os, secrets, shutil, subprocess, threading, time, urllib.request, urllib.error, uuid, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT=Path(__file__).resolve().parent
CONFIG_PATH=ROOT/'config.json'
CONFIG=json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig')) if CONFIG_PATH.exists() else {}
BASE=Path(os.environ.get('GAME_ART_COMFY',CONFIG.get('comfy_path',''))).expanduser()
COMFY=BASE/'ComfyUI' if (BASE/'ComfyUI').is_dir() else BASE
OUT=ROOT/'projects'; OUT.mkdir(exist_ok=True)
FFMPEG=os.environ.get('GAME_ART_FFMPEG',CONFIG.get('ffmpeg_path','ffmpeg'))
URL=os.environ.get('GAME_ART_COMFY_URL',CONFIG.get('comfy_url','http://127.0.0.1:8188'))
QWEN_URL=os.environ.get('GAME_ART_QWEN_URL',CONFIG.get('qwen_url',URL))
TOKEN=secrets.token_urlsafe(24); LOCK=threading.Lock(); JOB={'state':'idle','message':'准备就绪','error':''}

def request(path,data=None,endpoint=None):
    req=urllib.request.Request((endpoint or URL)+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=12) as f: return json.load(f)
    except urllib.error.HTTPError as e: raise RuntimeError(e.read().decode('utf-8','replace')[:3000])
def project(pid):
    if not isinstance(pid,str) or len(pid)!=32 or any(c not in '0123456789abcdef' for c in pid): raise ValueError('无效项目编号')
    p=OUT/pid; p.mkdir(exist_ok=True); return p
def progress(message):
    with LOCK: JOB.update(message=message)
def queue(graph,endpoint=None):
    progress('已提交 ComfyUI，正在生成…')
    res=request('/prompt',{'prompt':graph,'client_id':'codex-game-art-workbench'},endpoint)
    if res.get('node_errors'): raise RuntimeError(str(res['node_errors']))
    task=res['prompt_id']; end=time.time()+3600
    while time.time()<end:
        time.sleep(3); h=request('/history/'+task,endpoint=endpoint)
        if task in h:
            record=h[task]; status=record.get('status',{})
            if status.get('status_str')!='success': raise RuntimeError(json.dumps(status,ensure_ascii=False)[:3000])
            for v in record.get('outputs',{}).values():
                for f in v.get('images',[]): return COMFY/'output'/f.get('subfolder','')/f['filename']
            raise RuntimeError('生成完成，但没有找到输出文件')
    raise RuntimeError('生成超时，请查看 ComfyUI 状态')
def node(t,**inputs): return {'class_type':t,'inputs':inputs}
def qwen(prompt,first=None):
    g={'1':node('UNETLoader',unet_name='qwen_image_2.1_int8_convrot.safetensors',weight_dtype='default'),
       '2':node('CLIPLoader',clip_name='qwen3vl_8b_int8_convrot.safetensors',type='qwen_image',device='default'),
       '3':node('VAELoader',vae_name='qwen_image_2.1_vae_bf16.safetensors'),
       '4':node('TextEncodeQwenImage21',clip=['2',0],prompt=prompt,negative_prompt='',resolution=768),
       '5':node('EmptyLatentImage',width=768,height=768,batch_size=1),
       '6':node('KSampler',model=['1',0],positive=['4',0],negative=['4',1],latent_image=['5',0],seed=secrets.randbits(32),steps=25,cfg=1,sampler_name='euler',scheduler='simple',denoise=1),
       '7':node('VAEDecode',samples=['6',0],vae=['3',0]),'8':node('SaveImage',images=['7',0],filename_prefix='workbench/frame')}
    if first:
        name='workbench_'+uuid.uuid4().hex+'.png'; shutil.copy2(first,COMFY/'input'/name)
        g['9']=node('LoadImage',image=name); g['4']['inputs'].update({'vae':['3',0],'images.image_1':['9',0]}); g['6']['inputs']['latent_image']=['4',2]
    return queue(g,QWEN_URL)
def video(prompt,first,last,duration):
    f='workbench_'+uuid.uuid4().hex+'.png'; shutil.copy2(first,COMFY/'input'/f)
    length=max(5,round(duration*24)); length+= (5-length%17)%17
    g={'1':node('UNETLoader',unet_name='minimax_h3_fl2va_pruned_int8_convrot.safetensors',weight_dtype='default'),
       '2':node('CLIPLoader',clip_name='qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',type='minimax',device='default'),
       '3':node('VAELoader',vae_name='minimax_h3_video_vae_fp16.safetensors'), '4':node('VAELoader',vae_name='minimax_h3_audio_vae_fp32.safetensors'),
       '5':node('LoadImage',image=f), '6':node('MiniMaxH3ImageToVideo',clip=['2',0],vae=['3',0],first_frame=['5',0],prompt=prompt,width=448,height=448,length=length),
       '7':node('LoraLoaderModelOnly',model=['1',0],lora_name='minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors',strength_model=1),
       '8':node('BasicGuider',model=['7',0],conditioning=['6',0]), '9':node('RandomNoise',noise_seed=secrets.randbits(32)),
       '10':node('KSamplerSelect',sampler_name='res_multistep'), '11':node('BasicScheduler',model=['7',0],scheduler='simple',steps=8,denoise=1),
       '12':node('SamplerCustomAdvanced',noise=['9',0],guider=['8',0],sampler=['10',0],sigmas=['11',0],latent_image=['6',1]),
       '13':node('VAEDecode',samples=['12',0],vae=['3',0]), '14':node('VAEDecodeAudio',samples=['12',0],vae=['4',0]),
       '15':node('CreateVideo',images=['13',0],audio=['14',0],fps=24), '16':node('SaveVideo',video=['15',0],filename_prefix='workbench/video',format='auto',codec='auto')}
    if last:
        l='workbench_'+uuid.uuid4().hex+'.png'; shutil.copy2(last,COMFY/'input'/l); g['17']=node('LoadImage',image=l); g['6']['inputs']['last_frame']=['17',0]
    return queue(g)
def runff(args):
    r=subprocess.run([FFMPEG,'-hide_banner','-loglevel','error','-y']+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=600)
    if r.returncode: raise RuntimeError('视频处理失败：'+r.stderr[-1500:])
def worker(op,d):
    try:
        p=project(d['project']); prompt=str(d.get('prompt','')).strip()
        if op=='optimize':
            cmd=shutil.which('codex.cmd') or shutil.which('codex')
            if not cmd: raise RuntimeError('未找到 Codex 命令。请在 Codex 对话中优化后粘贴回输入框。')
            progress('正在调用 Codex 优化描述…')
            instruction='请把以下二维游戏动画需求优化为可直接用于图像和图生视频的简洁提示词。保留原意，明确角色、动作、固定镜头、完整角色、纯色背景；只输出提示词，不要解释：\n'+prompt
            import tempfile
            with tempfile.TemporaryDirectory(prefix='frame-prompt-') as temp:
                last=Path(temp)/'last.txt'
                args=['exec','--skip-git-repo-check','--sandbox','read-only','--output-last-message',str(last)]
                if CONFIG.get('codex_model'): args+=['--model',CONFIG['codex_model']]
                command=(['cmd.exe','/d','/c',cmd] if os.name=='nt' and cmd.lower().endswith(('.cmd','.bat')) else [cmd])+args+['-']
                r=subprocess.run(command,input=instruction,text=True,encoding="utf-8",errors="replace",capture_output=True,timeout=180,cwd=str(ROOT))
                message=last.read_text(encoding='utf-8-sig').strip() if last.exists() else ''
                if r.returncode or not message: raise RuntimeError('Codex 优化未完成，请检查 Codex 登录与模型设置。'+(r.stderr or r.stdout)[-800:])
                result={'optimized':message}
        elif op=='frames':
            if not prompt: raise ValueError('请先输入创作描述')
            if QWEN_URL!=URL:
                try: request('/free',{'unload_models':True,'free_memory':True},URL)
                except Exception: pass
            progress('正在生成首帧…'); first=qwen('2D game sprite character reference, full body, fixed orthographic camera, single character, centered with margin, flat light gray background. '+prompt); shutil.copy2(first,p/'first.png')
            progress('正在基于首帧生成尾帧…'); last=qwen('Edit <image1> into the final pose of this action: '+prompt+'. Keep the same character identity, costume, proportions, art style, camera, scale and flat light gray background. Full body in frame.',p/'first.png'); shutil.copy2(last,p/'last.png'); result={'first':'first.png','last':'last.png'}
        elif op=='video':
            if not (p/'first.png').is_file(): raise ValueError('请先生成首帧')
            duration=float(d.get('duration',5)); duration=max(1,min(5,duration))
            if QWEN_URL!=URL:
                try: request('/free',{'unload_models':True,'free_memory':True},QWEN_URL)
                except Exception: pass
            progress('正在生成视频，首次可能需要数分钟…'); path=video(prompt,p/'first.png',(p/'last.png') if d.get('use_last',True) and (p/'last.png').is_file() else None,duration)
            runff(['-i',str(path),'-t',str(duration),'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac',str(p/'video.mp4')]); result={'video':'video.mp4'}
        elif op=='candidates':
            source=p/'video.mp4'
            if not source.is_file(): raise ValueError('请先生成视频')
            duration=float(d.get('duration',5)); clip=min(2.0,duration); starts=[0,max(0,(duration-clip)/2),max(0,duration-clip)]
            for i,start in enumerate(starts,1):
                progress('正在制作候选片段 %d / 3…'%i); runff(['-ss',str(start),'-i',str(source),'-t',str(clip),'-an','-c:v','libx264','-crf','20','-pix_fmt','yuv420p',str(p/('candidate%d.mp4'%i))])
            result={'candidates':['candidate1.mp4','candidate2.mp4','candidate3.mp4']}
        elif op=='export':
            pick=int(d.get('candidate',1)); fps=int(d.get('fps',12)); fps=max(1,min(24,fps))
            if pick not in (1,2,3): raise ValueError('无效候选编号')
            source=p/('candidate%d.mp4'%pick)
            if not source.is_file(): raise ValueError('请先生成候选片段')
            dest=p/('export_'+uuid.uuid4().hex[:8]); (dest/'frames').mkdir(parents=True)
            alpha=bool(d.get('alpha',False)); vf='fps=%d'%fps
            if alpha: vf+=',format=rgba,colorkey=0xeeeeee:0.20:0.08'
            progress('正在导出 PNG 序列帧…'); runff(['-i',str(source),'-vf',vf,'-frames:v','120',str(dest/'frames'/'frame_%03d.png')])
            count=len(list((dest/'frames').glob('frame_*.png')))
            if not count: raise RuntimeError('未能导出帧')
            progress('正在打包图集…'); runff(['-framerate',str(fps),'-i',str(dest/'frames'/'frame_%03d.png'),'-vf','tile=6x%d:padding=0:margin=0'%((count+5)//6),'-frames:v','1',str(dest/'spritesheet.png')])
            (dest/'animation.json').write_text(json.dumps({'fps':fps,'frame_count':count,'frame_width':448,'frame_height':448,'columns':6,'alpha':alpha,'note':'alpha is a simple light-background color key; review edges' if alpha else 'original background retained'},ensure_ascii=False,indent=2),encoding='utf-8')
            shutil.make_archive(str(dest),'zip',dest); result={'archive':dest.name+'.zip','frame_count':count,'fps':fps,'alpha':alpha}
        else: raise ValueError('未知操作')
        with LOCK: JOB.update(state='done',message='完成',result=result,error='')
    except Exception as e:
        with LOCK: JOB.update(state='error',message='操作未完成',error=str(e),result={})
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def respond(self,status,obj):
        data=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        if path=='/api/status':
            with LOCK: state=JOB.copy()
            try: state['comfy']=request('/system_stats').get('system',{}).get('pytorch_version','connected')
            except Exception: state['comfy']='offline'
            return self.respond(200,state)
        if path=='/api/config': return self.respond(200,{'token':TOKEN})
        if path.startswith('/projects/'):
            target=(ROOT/path.lstrip('/')).resolve(); allowed=OUT.resolve()
            if not target.is_relative_to(allowed) or not target.is_file(): return self.send_error(404)
        else:
            target=(ROOT/'web'/('index.html' if path=='/' else path.lstrip('/'))).resolve()
            if not target.is_relative_to((ROOT/'web').resolve()) or not target.is_file(): return self.send_error(404)
        data=target.read_bytes(); self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(str(target))[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if self.headers.get('X-Workbench-Token')!=TOKEN: return self.respond(403,{'error':'无效请求'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>20_000_000: raise ValueError('文件过大')
            d=json.loads(self.rfile.read(size)); op=urlparse(self.path).path.removeprefix('/api/')
            if op=='upload':
                p=project(d['project']); kind=d.get('kind');
                if kind not in ('first','last'): raise ValueError('无效图片类型')
                raw=base64.b64decode(d['data'].split(',')[-1],validate=True)
                from PIL import Image
                import io
                image=Image.open(io.BytesIO(raw)); image.verify(); image=Image.open(io.BytesIO(raw)).convert('RGB'); image.save(p/(kind+'.png')); return self.respond(200,{'ok':True})
            if op not in ('optimize','frames','video','candidates','export'): raise ValueError('未知操作')
            with LOCK:
                if JOB['state']=='running': return self.respond(409,{'error':'已有任务正在运行'})
                JOB.update(state='running',message='正在准备…',result={},error='')
            threading.Thread(target=worker,args=(op,d),daemon=True).start(); return self.respond(202,{'ok':True})
        except Exception as e: return self.respond(400,{'error':str(e)})
if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',8765),Handler); print('Game Art Workbench: http://127.0.0.1:8765',flush=True);server.serve_forever()
