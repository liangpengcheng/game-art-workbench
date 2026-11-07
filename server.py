import base64, io, json, math, mimetypes, os, re, secrets, shutil, subprocess, threading, time, urllib.error, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / 'config.json'
CONFIG = json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig')) if CONFIG_PATH.exists() else {}
BASE = Path(os.environ.get('GAME_ART_COMFY', CONFIG.get('comfy_path', ''))).expanduser()
COMFY = BASE / 'ComfyUI' if (BASE / 'ComfyUI').is_dir() else BASE
OUT = ROOT / 'projects'; OUT.mkdir(exist_ok=True)
FFMPEG = os.environ.get('GAME_ART_FFMPEG', CONFIG.get('ffmpeg_path', 'ffmpeg'))
FFPROBE = str(Path(FFMPEG).with_name('ffprobe' + Path(FFMPEG).suffix)) if Path(FFMPEG).parent != Path('.') else 'ffprobe'
URL = os.environ.get('GAME_ART_COMFY_URL', CONFIG.get('comfy_url', 'http://127.0.0.1:8188'))
QWEN_URL = os.environ.get('GAME_ART_QWEN_URL', CONFIG.get('qwen_url', URL))
TOKEN = secrets.token_urlsafe(24); LOCK = threading.Lock(); JOB = {'state':'idle','message':'准备就绪','error':''}
FPS = 24

def request(path, data=None, endpoint=None):
    req = urllib.request.Request((endpoint or URL)+path, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=12) as f:
            raw=f.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e: raise RuntimeError(e.read().decode('utf-8','replace')[:3000])

def project(pid):
    if not isinstance(pid,str) or not re.fullmatch(r'[a-f0-9]{32}',pid): raise ValueError('无效项目编号')
    p=OUT/pid; p.mkdir(exist_ok=True); return p

def progress(message):
    with LOCK: JOB.update(message=message)

def queue(graph, endpoint=None):
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

def bounded(value,name,lo,hi):
    try: n=float(value)
    except (TypeError,ValueError): raise ValueError(f'{name}需要填写数字')
    if not math.isfinite(n) or n<lo or n>hi: raise ValueError(f'{name}必须在 {lo} 到 {hi} 之间')
    return n

def frame_kind(kind):
    if kind in ('first','last') or (isinstance(kind,str) and re.fullmatch(r'guide_[a-f0-9]{16}',kind)): return kind
    raise ValueError('无效关键帧编号')

def action_mode(d,prompt):
    mode=d.get('action_mode','auto')
    if mode not in ('auto','idle','move','attack','other'): raise ValueError('无效动作类型')
    if mode=='auto': return 'idle' if any(k in prompt.lower() for k in ('待机','idle','idle loop')) else 'other'
    return mode

def motion_prompt(prompt,mode):
    if not prompt.strip(): raise ValueError('请先输入创作描述')
    common=('Create one uninterrupted 2D game character sprite animation. One character only, same costume, proportions and identity throughout. '
            'Full body remains entirely in frame, fixed orthographic camera, fixed scale and position, no cuts, no camera motion, '
            'no scene changes, no new objects, no extra characters, flat uniform light gray background. ')
    idle=('The ONLY movement is a subtle slow breathing or gentle body sway in place. Feet stay planted; hands and props remain in the same pose. '
          'No walking, running, jumping, attacking, gesturing, turning, adding items, scene transitions or other actions. '
          'Start and end in nearly identical poses for a seamless idle loop. ') if mode=='idle' else ''
    return common+idle+'Requested character and action: '+prompt.strip()

def qwen(prompt,first=None):
    g={'1':node('UNETLoader',unet_name='qwen_image_2.1_int8_convrot.safetensors',weight_dtype='default'),
       '2':node('CLIPLoader',clip_name='qwen3vl_8b_int8_convrot.safetensors',type='qwen_image',device='default'),
       '3':node('VAELoader',vae_name='qwen_image_2.1_vae_bf16.safetensors'),
       '4':node('TextEncodeQwenImage21',clip=['2',0],prompt=prompt,negative_prompt='',resolution=768),
       '5':node('EmptyLatentImage',width=768,height=768,batch_size=1),
       '6':node('KSampler',model=['1',0],positive=['4',0],negative=['4',1],latent_image=['5',0],seed=secrets.randbits(32),steps=25,cfg=1,sampler_name='euler',scheduler='simple',denoise=1),
       '7':node('VAEDecode',samples=['6',0],vae=['3',0]),'8':node('SaveImage',images=['7',0],filename_prefix='workbench/frame')}
    if first:
        name=prepare_input(first); g['9']=node('LoadImage',image=name)
        g['4']['inputs'].update({'vae':['3',0],'images.image_1':['9',0]}); g['6']['inputs']['latent_image']=['4',2]
    return queue(g,QWEN_URL)

def prepare_input(path):
    """Preserve uploaded RGBA files; composite only the model input onto a known light background."""
    name='workbench_'+uuid.uuid4().hex+'.png'; image=Image.open(path).convert('RGBA')
    bg=Image.new('RGBA',image.size,(238,238,238,255)); bg.alpha_composite(image); bg.convert('RGB').save(COMFY/'input'/name)
    return name

def video(prompt,first,last,duration,guides):
    f=prepare_input(first); length=max(5,round(duration*FPS)); length+=(5-length%17)%17
    g={'1':node('UNETLoader',unet_name='minimax_h3_fl2va_pruned_int8_convrot.safetensors',weight_dtype='default'),
       '2':node('CLIPLoader',clip_name='qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',type='minimax',device='default'),
       '3':node('VAELoader',vae_name='minimax_h3_video_vae_fp16.safetensors'), '4':node('VAELoader',vae_name='minimax_h3_audio_vae_fp32.safetensors'),
       '5':node('LoadImage',image=f), '6':node('MiniMaxH3ImageToVideo',clip=['2',0],vae=['3',0],first_frame=['5',0],prompt=prompt,width=448,height=448,length=length),
       '7':node('LoraLoaderModelOnly',model=['1',0],lora_name='minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors',strength_model=1),
       '8':node('BasicGuider',model=['7',0],conditioning=['6',0]), '9':node('RandomNoise',noise_seed=secrets.randbits(32)),
       '10':node('KSamplerSelect',sampler_name='res_multistep'), '11':node('BasicScheduler',model=['7',0],scheduler='simple',steps=8,denoise=1),
       '12':node('SamplerCustomAdvanced',noise=['9',0],guider=['8',0],sampler=['10',0],sigmas=['11',0],latent_image=['6',1]),
       '13':node('VAEDecode',samples=['12',0],vae=['3',0]), '14':node('VAEDecodeAudio',samples=['12',0],vae=['4',0]),
       '15':node('CreateVideo',images=['13',0],audio=['14',0],fps=FPS), '16':node('SaveVideo',video=['15',0],filename_prefix='workbench/video',format='auto',codec='auto')}
    if last:
        g['17']=node('LoadImage',image=prepare_input(last)); g['6']['inputs']['last_frame']=['17',0]
    conditioning=['6',0]
    if last and round(duration*FPS)<length:
        g['last_output_anchor']=node('MiniMaxH3AddGuide',positive=conditioning,latent=['6',1],vae=['3',0],image=['17',0],frame_idx=max(1,round(duration*FPS)-1))
        conditioning=['last_output_anchor',0]
    for index,(frame,frame_idx) in enumerate(guides):
        image_id='guide_image_'+str(index); guide_id='guide_anchor_'+str(index)
        g[image_id]=node('LoadImage',image=prepare_input(frame))
        g[guide_id]=node('MiniMaxH3AddGuide',positive=conditioning,latent=['6',1],vae=['3',0],image=[image_id,0],frame_idx=frame_idx)
        conditioning=[guide_id,0]
    g['8']['inputs']['conditioning']=conditioning
    return queue(g)

def runff(args):
    r=subprocess.run([FFMPEG,'-hide_banner','-loglevel','error','-y']+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',timeout=600)
    if r.returncode: raise RuntimeError('视频处理失败：'+r.stderr[-1500:])

def probe(path):
    r=subprocess.run([FFPROBE,'-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    if r.returncode: raise RuntimeError('读取视频信息失败：'+r.stderr[-1000:])
    data=json.loads(r.stdout); stream=next((s for s in data.get('streams',[]) if s.get('codec_type')=='video'),None)
    if not stream: raise ValueError('文件没有视频轨道')
    return float(data['format']['duration']),stream['width'],stream['height']

def keyed(image,color,tolerance,softness=12):
    image=image.convert('RGBA'); rgb=image.convert('RGB'); bg=Image.new('RGB',image.size,color)
    diff=ImageChops.difference(rgb,bg); r,g,b=diff.split(); delta=ImageChops.lighter(ImageChops.lighter(r,g),b)
    lut=[0 if n<=tolerance else min(255,round((n-tolerance)*255/softness)) for n in range(256)]
    alpha=ImageChops.multiply(image.getchannel('A'),delta.point(lut)); image.putalpha(alpha); return image

def release(endpoint):
    try: queued=request('/queue',endpoint=endpoint)
    except (OSError,urllib.error.URLError): return
    if queued.get('queue_running') or queued.get('queue_pending'):
        raise RuntimeError('另一 ComfyUI 服务正在运行任务，请等待完成后再切换模型')
    request('/free',{'unload_models':True,'free_memory':True},endpoint)

def worker(op,d):
    try:
        p=project(d['project']); prompt=str(d.get('prompt','')).strip(); mode=action_mode(d,prompt)
        if op=='frames':
            if not prompt: raise ValueError('请先输入创作描述')
            if QWEN_URL!=URL: release(URL)
            first_prompt=('2D game character sprite, one character, full body centered with generous margin, fixed camera, flat uniform light gray background, '
                          'no text or extra objects. Starting pose: '+prompt)
            if mode=='idle': first_prompt+=' Neutral idle stance, feet planted, relaxed pose, no action or prop changes.'
            progress('正在生成首帧…'); first=qwen(first_prompt); shutil.copy2(first,p/'first.png')
            if mode=='idle':
                progress('待机循环使用同一张图作为首尾帧…'); shutil.copy2(p/'first.png',p/'last.png')
            else:
                progress('正在基于首帧生成尾帧…')
                last=qwen('Edit <image1> into the final pose of this game action: '+prompt+'. Keep exactly the same character, costume, proportions, style, fixed camera and plain light gray background. Full body visible.',p/'first.png'); shutil.copy2(last,p/'last.png')
            result={'first':'first.png','last':'last.png','mode':mode}
        elif op=='guide':
            kind=frame_kind(d.get('kind')); desc=str(d.get('pose','')).strip()
            if not kind.startswith('guide_') or not desc: raise ValueError('请填写关键帧姿态描述')
            if not (p/'first.png').is_file(): raise ValueError('请先生成或上传首帧')
            if QWEN_URL!=URL: release(URL)
            progress('正在基于首帧生成关键帧…')
            frame=qwen('Edit <image1> to this single pose: '+desc+'. Keep exactly the same character, costume, body proportions, art style, fixed camera and plain light gray background. Full body visible.',p/'first.png')
            shutil.copy2(frame,p/(kind+'.png')); result={'kind':kind,'file':kind+'.png'}
        elif op=='video':
            if not (p/'first.png').is_file(): raise ValueError('请先生成或上传首帧')
            duration=bounded(d.get('duration',5),'动画时长',0.5,15)
            raw=d.get('guides',[])
            if not isinstance(raw,list) or len(raw)>8: raise ValueError('最多添加 8 个中间关键帧')
            guides=[]; seen=set()
            for item in raw:
                kind=frame_kind(item.get('kind')); t=bounded(item.get('time'),'关键帧时间',0,duration); idx=round(t*FPS)
                if not kind.startswith('guide_') or not (p/(kind+'.png')).is_file(): raise ValueError('请先上传或生成所有关键帧')
                if t<=0 or t>=duration or idx<=0 or idx>=round(duration*FPS)-1: raise ValueError('中间关键帧时间必须位于首帧和尾帧之间，至少相隔一帧')
                if idx in seen: raise ValueError('关键帧时间过近，请至少间隔一帧')
                seen.add(idx); guides.append((p/(kind+'.png'),idx))
            guides.sort(key=lambda x:x[1])
            if QWEN_URL!=URL: release(QWEN_URL)
            effective=motion_prompt(prompt,mode)
            progress('正在生成视频，首次可能需要数分钟…')
            path=video(effective,p/'first.png',(p/'last.png') if d.get('use_last',True) and (p/'last.png').is_file() else None,duration,guides)
            runff(['-i',str(path),'-t',str(duration),'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac',str(p/'video.mp4')])
            actual,_,_=probe(p/'video.mp4'); result={'video':'video.mp4','duration':actual,'mode':mode,'guide_count':len(guides)}
        elif op=='candidates':
            source=p/'video.mp4'
            if not source.is_file(): raise ValueError('请先生成视频')
            actual,width,height=probe(source); start=bounded(d.get('start',0),'起始时间',0,actual)
            end=bounded(d.get('end',actual),'结束时间',0,actual)
            if end<=start: raise ValueError('结束时间必须大于起始时间')
            fps_value=bounded(d.get('fps',12),'帧率',1,24)
            if not fps_value.is_integer(): raise ValueError('帧率必须为整数')
            fps=int(fps_value); offsets=d.get('offsets',[0,1,-1])
            if not isinstance(offsets,list) or len(offsets)!=3: raise ValueError('需要三个候选偏移值')
            offset_values=[bounded(v,'起点偏移帧数',-360,360) for v in offsets]
            if any(not v.is_integer() for v in offset_values): raise ValueError('起点偏移必须为整数帧')
            offsets=[int(v) for v in offset_values]
            batch='candidate_set_'+uuid.uuid4().hex[:12]; folder=p/batch; raw=folder/'frames'; raw.mkdir(parents=True)
            progress('正在提取完整动作帧…')
            runff(['-ss',str(start),'-i',str(source),'-t',str(end-start),'-an','-vf',f'fps={fps}','-start_number','0',str(raw/'frame_%04d.png')])
            count=len(list(raw.glob('frame_*.png')))
            if count<2: raise ValueError('所选范围太短，未能提取至少两帧')
            files=[]
            for i,offset in enumerate(offsets,1):
                progress(f'正在生成完整动画候选 {i} / 3…'); shift=offset%count; out=folder/f'candidate{i}.mp4'
                args=['-framerate',str(fps),'-start_number','0','-i',str(raw/'frame_%04d.png')]
                if shift:
                    filt=f'[0:v]split[a][b];[a]trim=start_frame={shift},setpts=PTS-STARTPTS[x];[b]trim=end_frame={shift},setpts=PTS-STARTPTS[y];[x][y]concat=n=2:v=1:a=0[out]'
                    args+=['-filter_complex',filt,'-map','[out]']
                args+=['-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(out)]; runff(args); files.append(batch+'/'+out.name)
            meta={'fps':fps,'frame_count':count,'width':width,'height':height,'start':start,'end':end,'offsets':offsets,'files':files}
            (folder/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
            result={'candidates':files,'set':batch,'fps':fps,'frame_count':count,'offsets':offsets,'start':start,'end':end}
        elif op=='export':
            batch=d.get('set',''); pick=int(d.get('candidate',0))
            if not isinstance(batch,str) or not re.fullmatch(r'candidate_set_[a-f0-9]{12}',batch) or pick not in (1,2,3): raise ValueError('请先选择新的完整动画候选')
            folder=p/batch; meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8')); count=meta['frame_count']; fps=meta['fps']; shift=meta['offsets'][pick-1]%count
            raw=folder/'frames'; dest=p/('export_'+uuid.uuid4().hex[:8]); (dest/'frames').mkdir(parents=True)
            alpha=bool(d.get('alpha',True)); color=str(d.get('color','#eeeeee'))
            if not re.fullmatch(r'#[a-fA-F0-9]{6}',color): raise ValueError('背景颜色无效')
            tolerance=int(bounded(d.get('tolerance',28),'抠图容差',0,100)); rgb=tuple(int(color[i:i+2],16) for i in (1,3,5))
            cols=6; rows=math.ceil(count/cols); width,height=meta['width'],meta['height']
            sheet=Image.new('RGBA',(cols*width,rows*height),(0,0,0,0))
            progress('正在导出所选完整动画帧…')
            for i in range(count):
                frame=Image.open(raw/f'frame_{(i+shift)%count:04d}.png').convert('RGBA')
                if alpha: frame=keyed(frame,rgb,tolerance)
                frame.save(dest/'frames'/f'frame_{i:04d}.png'); sheet.paste(frame,((i%cols)*width,(i//cols)*height))
            sheet.save(dest/'spritesheet.png')
            metadata={'fps':fps,'frame_count':count,'frame_width':width,'frame_height':height,'columns':cols,'alpha':alpha,'loop_offset_frames':meta['offsets'][pick-1],'source_start':meta['start'],'source_end':meta['end'],'note':'Color-key transparency is approximate; inspect edges.' if alpha else 'Original background retained.'}
            (dest/'animation.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
            shutil.make_archive(str(dest),'zip',dest); result={'archive':dest.name+'.zip','frame_count':count,'fps':fps,'alpha':alpha}
        else: raise ValueError('未知操作')
        with LOCK: JOB.update(state='done',message='完成',result=result,error='')
    except Exception as e:
        with LOCK: JOB.update(state='error',message='操作未完成',error=str(e),result={})

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def respond(self,status,obj):
        data=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        if path=='/api/status':
            with LOCK: state=JOB.copy()
            try: state['comfy']=request('/system_stats').get('system',{}).get('pytorch_version','connected')
            except Exception: state['comfy']='offline'
            return self.respond(200,state)
        if path=='/api/config': return self.respond(200,{'token':TOKEN})
        if path.startswith('/projects/'):
            target=(ROOT/path.lstrip('/')).resolve()
            if not target.is_relative_to(OUT.resolve()) or not target.is_file(): return self.send_error(404)
        else:
            target=(ROOT/'web'/('index.html' if path=='/' else path.lstrip('/'))).resolve()
            if not target.is_relative_to((ROOT/'web').resolve()) or not target.is_file(): return self.send_error(404)
        size=target.stat().st_size; start=0; end=size-1; header=self.headers.get('Range')
        if header:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',header.strip())
            if not match or not any(match.groups()): self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.end_headers(); return
            if match.group(1): start=int(match.group(1)); end=min(int(match.group(2)) if match.group(2) else end,end)
            else: start=max(0,size-int(match.group(2)))
            if start>=size or end<start: self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.end_headers(); return
        self.send_response(206 if header else 200); self.send_header('Content-Type',mimetypes.guess_type(str(target))[0] or 'application/octet-stream'); self.send_header('Content-Length',str(end-start+1)); self.send_header('Accept-Ranges','bytes'); self.send_header('Cache-Control','no-store')
        if header: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with target.open('rb') as f:
                f.seek(start); remaining=end-start+1
                while remaining:
                    chunk=f.read(min(1024*1024,remaining))
                    if not chunk: break
                    self.wfile.write(chunk); remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError): pass
    def do_POST(self):
        if self.headers.get('X-Workbench-Token')!=TOKEN: return self.respond(403,{'error':'无效请求'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>20_000_000: raise ValueError('文件过大')
            d=json.loads(self.rfile.read(size)); op=urlparse(self.path).path.removeprefix('/api/')
            if op=='upload':
                with LOCK:
                    if JOB['state']=='running': return self.respond(409,{'error':'任务正在运行，请等待完成后再更换图片'})
                p=project(d['project']); kind=frame_kind(d.get('kind')); raw=base64.b64decode(d['data'].split(',')[-1],validate=True)
                image=Image.open(io.BytesIO(raw)); image.verify(); image=Image.open(io.BytesIO(raw)); image.convert('RGBA' if 'A' in image.getbands() else 'RGB').save(p/(kind+'.png'))
                return self.respond(200,{'ok':True,'file':kind+'.png'})
            if op not in ('frames','guide','video','candidates','export'): raise ValueError('未知操作')
            with LOCK:
                if JOB['state']=='running': return self.respond(409,{'error':'已有任务正在运行'})
                JOB.update(state='running',message='正在准备…',result={},error='',operation=op,project=d.get('project'),job_id=uuid.uuid4().hex)
            threading.Thread(target=worker,args=(op,d),daemon=True).start(); return self.respond(202,{'ok':True})
        except Exception as e: return self.respond(400,{'error':str(e)})

if __name__=='__main__':
    port=int(os.environ.get('GAME_ART_PORT','8765')); server=ThreadingHTTPServer(('127.0.0.1',port),Handler); print(f'Game Art Workbench: http://127.0.0.1:{port}',flush=True); server.serve_forever()
