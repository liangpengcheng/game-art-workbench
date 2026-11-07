const $ = s => document.querySelector(s);
let token='', busy=false, selected=0, currentOp='';
let project=localStorage.getItem('frame-project') || crypto.randomUUID().replaceAll('-','');
localStorage.setItem('frame-project',project);
const key='frame-state-'+project;
let state; try { state=JSON.parse(localStorage.getItem(key)||'{}'); } catch { state={}; }
if(!Array.isArray(state.guides)) state.guides=[];
function fileUrl(file){ return '/projects/'+project+'/'+file+'?v='+Date.now(); }
function save(){
  state.prompt=$('#prompt').value; state.duration=$('#duration').value; state.actionMode=$('#actionMode').value;
  state.useLast=$('#useLast').checked; state.start=$('#rangeStart').value; state.end=$('#rangeEnd').value;
  state.fps=$('#fps').value; state.offsets=[1,2,3].map(i=>$('#offset'+i).value);
  state.alpha=$('#alpha').checked; state.color=$('#keyColor').value; state.tolerance=$('#tolerance').value;
  state.selected=selected; localStorage.setItem(key,JSON.stringify(state));
}
function notify(message){const t=$('#toast');t.textContent=message;t.style.display='block';clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>t.style.display='none',7500);}
function keyPixels(data, colorOverride=null){
  const color=colorOverride||$('#keyColor').value, tolerance=Math.max(0,Math.min(100,Number($('#tolerance').value)||0));
  const r=parseInt(color.slice(1,3),16),g=parseInt(color.slice(3,5),16),b=parseInt(color.slice(5,7),16);
  for(let i=0;i<data.length;i+=4){const d=Math.max(Math.abs(data[i]-r),Math.abs(data[i+1]-g),Math.abs(data[i+2]-b));const a=d<=tolerance?0:Math.min(255,Math.round((d-tolerance)*255/12));data[i+3]=Math.round(data[i+3]*a/255);}
}
function showImage(kind){
  const img=$('#'+kind+'Image'), box=$('#'+kind+'Box'); if(!img||!box)return;
  const source=new Image();source.onload=()=>{if($('#alpha').checked){const canvas=document.createElement('canvas');canvas.width=source.naturalWidth;canvas.height=source.naturalHeight;const c=canvas.getContext('2d',{willReadFrequently:true});c.drawImage(source,0,0);const pixels=c.getImageData(0,0,canvas.width,canvas.height);let hasAlpha=false;for(let i=3;i<pixels.data.length;i+=4){if(pixels.data[i]<255){hasAlpha=true;break}}if(!hasAlpha){const coords=[[2,2],[canvas.width-3,2],[2,canvas.height-3],[canvas.width-3,canvas.height-3]];const colors=coords.map(([x,y])=>Array.from(c.getImageData(Math.max(0,x),Math.max(0,y),1,1).data));const rgb=[0,1,2].map(i=>colors.map(v=>v[i]).sort((a,b)=>a-b)[1]);keyPixels(pixels.data,'#'+rgb.map(n=>n.toString(16).padStart(2,'0')).join(''))}c.putImageData(pixels,0,0);img.src=canvas.toDataURL('image/png')}else img.src=source.src;img.hidden=false;const placeholder=box.querySelector('.placeholder');if(placeholder)placeholder.hidden=true;};
  source.onerror=()=>{img.hidden=true};source.src=fileUrl(kind+'.png');
}
function sampleBackground(silent=false){
  const v=$('#video');if(!state.video||v.readyState<2){if(!silent)notify('视频画面尚未加载，请稍后重试');return}
  const c=document.createElement('canvas');c.width=v.videoWidth;c.height=v.videoHeight;const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(v,0,0);
  const coords=[[2,2],[c.width-3,2],[2,c.height-3],[c.width-3,c.height-3]];const colors=coords.map(([x,y])=>Array.from(ctx.getImageData(x,y,1,1).data).slice(0,3));
  const rgb=[0,1,2].map(i=>colors.map(c=>c[i]).sort((a,b)=>a-b)[1]);$('#keyColor').value='#'+rgb.map(n=>n.toString(16).padStart(2,'0')).join('');state.backgroundSampled=true;save();
  if(state.first)showImage('first');if(state.last)showImage('last');for(const g of state.guides)if(g.hasImage)showImage(g.kind);if(state.candidates)renderCandidates();if(!silent)notify('已从视频角落取样背景色，请检查透明边缘');
}
function showVideo(){const v=$('#video');v.src=fileUrl('video.mp4');v.hidden=false;$('#videoBox .placeholder').hidden=true;v.onloadedmetadata=()=>{if(!state.end||Number(state.end)>v.duration){$('#rangeEnd').value=v.duration.toFixed(2);state.end=$('#rangeEnd').value;save()}};v.onloadeddata=()=>{if(!state.backgroundSampled)sampleBackground(true)};}
function setStep(n){for(let i=1;i<=5;i++){let e=$('#step'+i);e.classList.toggle('done',i<n);e.classList.toggle('active',i===n);}}
function invalidateVideo(){state.video=false;state.candidates=null;state.candidateSet=null;state.archive=null;selected=0;$('#video').hidden=true;$('#videoBox .placeholder').hidden=false;$('#selection').textContent='尚未选择候选';$('#candidateGrid').innerHTML='<div class="candidate-empty">设置范围并生成候选后，在这里循环预览。</div>';$('#download').innerHTML='';}
function invalidateCandidates(){state.candidates=null;state.candidateSet=null;state.archive=null;selected=0;$('#selection').textContent='设置已更改，请重新生成候选';$('#candidateGrid').innerHTML='<div class="candidate-empty">设置范围并生成候选后，在这里循环预览。</div>';$('#download').innerHTML='';}
function renderGuides(){
  const list=$('#guides');list.innerHTML='';
  state.guides.forEach((item,index)=>{
    const el=document.createElement('div');el.className='guide-item';
    el.innerHTML='<div class="guide-thumb checker" id="'+item.kind+'Box"><div class="placeholder">关键帧 '+(index+1)+'</div><img id="'+item.kind+'Image" hidden alt="中间关键帧 '+(index+1)+'"></div><div class="guide-fields"><div class="guide-title"><strong>关键帧 '+(index+1)+'</strong><button class="text-button remove-guide" type="button">移除</button></div><label>出现时间 <input class="small-number guide-time" type="number" min="0.05" max="15" step="0.05"> 秒</label><input class="pose" type="text" placeholder="描述这一时刻的姿态，例如身体向左轻微倾斜"><div class="guide-buttons"><label class="upload">↑ 上传图片<input class="guide-upload" type="file" accept="image/*" hidden></label><button class="subtle guide-generate" type="button">✦ 基于首帧生成</button></div></div>';
    list.appendChild(el);const time=el.querySelector('.guide-time');time.value=item.time;time.onchange=()=>{item.time=time.value;invalidateVideo();save()};
    const pose=el.querySelector('.pose');pose.value=item.pose||'';pose.oninput=()=>{item.pose=pose.value;save()};
    el.querySelector('.remove-guide').onclick=()=>{if(busy)return;state.guides=state.guides.filter(x=>x.kind!==item.kind);invalidateVideo();save();renderGuides()};
    el.querySelector('.guide-upload').onchange=e=>upload(e,item.kind);
    el.querySelector('.guide-generate').onclick=()=>{if(!item.pose.trim())return notify('请先填写这一关键帧的姿态描述');action('guide',{kind:item.kind,pose:item.pose})};
    if(item.hasImage)showImage(item.kind);
  });
}
function playPreview(video,canvas){
  const ctx=canvas.getContext('2d',{willReadFrequently:true});let last=0;
  function paint(now){if(!canvas.isConnected)return;if(!video.paused&&!video.ended&&now-last>70&&video.readyState>=2){last=now;canvas.width=video.videoWidth||448;canvas.height=video.videoHeight||448;ctx.drawImage(video,0,0,canvas.width,canvas.height);if($('#alpha').checked){const frame=ctx.getImageData(0,0,canvas.width,canvas.height);keyPixels(frame.data);ctx.putImageData(frame,0,0);}}requestAnimationFrame(paint)}requestAnimationFrame(paint);
}
function renderCandidates(){
  const grid=$('#candidateGrid');grid.innerHTML='';
  if(!state.candidates||!state.candidateSet){grid.innerHTML='<div class="candidate-empty">设置范围并生成候选后，在这里循环预览。</div>';return}
  state.candidates.forEach((file,i)=>{
    const card=document.createElement('div');card.className='candidate'+(selected===i+1?' selected':'');
    const shift=(state.candidateOffsets||[])[i]??0;
    card.innerHTML='<div class="candidate-canvas checker"><video muted loop playsinline preload="metadata"></video><canvas width="448" height="448" aria-label="候选动画预览"></canvas></div><div class="candidate-controls"><button type="button" class="play-candidate">▶ 播放</button><span>起点 '+(Number(shift)>0?'+':'')+shift+' 帧</span></div><button type="button" class="select-candidate">'+(selected===i+1?'✓ 已选择':'选择候选 0'+(i+1))+'</button>';
    grid.appendChild(card);const v=card.querySelector('video'),canvas=card.querySelector('canvas'),play=card.querySelector('.play-candidate');v.src=fileUrl(file);v.muted=true;v.loop=true;playPreview(v,canvas);
    play.onclick=async()=>{if(v.paused){try{await v.play();play.textContent='❚❚ 暂停'}catch(e){notify('无法播放候选：'+e.message)}}else{v.pause();play.textContent='▶ 播放'}};
    card.querySelector('.select-candidate').onclick=()=>{selected=i+1;save();renderCandidates();$('#selection').textContent='已选择候选 0'+selected;setStep(5)};
    v.onloadeddata=()=>{const ctx=canvas.getContext('2d',{willReadFrequently:true});canvas.width=v.videoWidth||448;canvas.height=v.videoHeight||448;ctx.drawImage(v,0,0,canvas.width,canvas.height);if($('#alpha').checked){const frame=ctx.getImageData(0,0,canvas.width,canvas.height);keyPixels(frame.data);ctx.putImageData(frame,0,0)}};
  });
}
function restore(){
  $('#prompt').value=state.prompt||'';$('#duration').value=state.duration||'5';$('#actionMode').value=state.actionMode||'auto';$('#useLast').checked=state.useLast!==false;
  $('#rangeStart').value=state.start??'0';$('#rangeEnd').value=state.end||'';$('#fps').value=state.fps||'12';(state.offsets||[0,1,-1]).forEach((x,i)=>$('#offset'+(i+1)).value=x);
  $('#alpha').checked=state.alpha!==false;$('#keyColor').value=state.color||'#eeeeee';$('#tolerance').value=state.tolerance??28;selected=state.selected||0;
  if(state.first)showImage('first');if(state.last)showImage('last');renderGuides();if(state.video)showVideo();
  if(state.candidates&&state.candidateSet){renderCandidates();setStep(selected?5:4)}else if(state.video)setStep(3);else if(state.first)setStep(2);
  if(selected&&state.candidateSet)$('#selection').textContent='已选择候选 0'+selected;if(state.archive)showDownload(state.archive);
}
function showDownload(name){const e=$('#download');e.innerHTML='';const a=document.createElement('a');a.href=fileUrl(name);a.download='animation.zip';a.textContent='↓ 下载序列帧、图集与信息文件';e.appendChild(a)}
async function post(op,extra={}){const r=await fetch('/api/'+op,{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':token},body:JSON.stringify({project,prompt:$('#prompt').value,duration:$('#duration').value,action_mode:$('#actionMode').value,...extra})});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;}
function buttons(on){busy=on;document.querySelectorAll('button').forEach(b=>{if(b.id!=='newProject')b.disabled=on});}
async function action(op,extra={}){
  if(busy)return;if((op==='frames'||op==='video')&&!$('#prompt').value.trim())return notify('请先输入创作描述');
  if((op==='video'||op==='guide')&&!state.first)return notify('请先生成或上传首帧');if(op==='candidates'&&!state.video)return notify('请先生成视频');if(op==='export'&&(!selected||!state.candidateSet))return notify('请先生成并选择完整动画候选');
  save();buttons(true);currentOp=op;try{await post(op,extra);poll()}catch(e){buttons(false);currentOp='';notify(e.message)}
}
async function poll(){
  try{const s=await(await fetch('/api/status')).json();$('#connection').textContent=s.comfy==='offline'?'ComfyUI 未连接':'ComfyUI 已连接';$('#dot').style.background=s.comfy==='offline'?'#dd9a79':'#a7d46f';$('#jobTitle').textContent=s.message||'准备就绪';$('#jobDetail').textContent=s.state==='running'?'正在运行，请保持工作台开启':(s.error||'本地任务');
    if(s.project===project&&s.job_id&&state.jobProcessed!==s.job_id&&!currentOp)currentOp=s.operation;
    if(s.state==='running'){buttons(true);setTimeout(poll,2500);return}buttons(false);
    if(s.state==='error'){if(s.project===project&&state.jobProcessed!==s.job_id){notify(s.error||'操作失败');state.jobProcessed=s.job_id;save()}currentOp='';return}
    if(s.state==='done'&&currentOp&&s.project===project){const r=s.result||{};
      if(currentOp==='frames'){state.first=state.last=true;invalidateVideo();showImage('first');showImage('last');setStep(2);$('#frames').scrollIntoView({behavior:'smooth'});if(r.mode==='idle')notify('待机模式已使用相同首尾帧，便于循环')}
      if(currentOp==='guide'){const item=state.guides.find(x=>x.kind===r.kind);if(item)item.hasImage=true;invalidateVideo();renderGuides();setStep(2)}
      if(currentOp==='video'){state.video=true;state.backgroundSampled=false;state.end=String(r.duration||$('#duration').value);$('#rangeStart').value='0';$('#rangeEnd').value=state.end;invalidateCandidates();showVideo();setStep(3);$('#motion').scrollIntoView({behavior:'smooth'})}
      if(currentOp==='candidates'){state.candidates=r.candidates;state.candidateSet=r.set;state.candidateOffsets=r.offsets;state.candidateFps=r.fps;state.candidateCount=r.frame_count;selected=0;renderCandidates();setStep(4);$('#candidates').scrollIntoView({behavior:'smooth'});notify('每个候选均包含 '+r.frame_count+' 帧完整动作')}
      if(currentOp==='export'){state.archive=r.archive;showDownload(r.archive);setStep(5);notify('导出完成，共 '+r.frame_count+' 帧')}
      state.jobProcessed=s.job_id;save();currentOp='';
    }
  }catch(e){buttons(false);currentOp='';notify('无法连接本地工作台：'+e.message)}
}
async function upload(e,kind){const f=e.target.files[0];if(!f)return;const reader=new FileReader();reader.onload=async()=>{try{await post('upload',{kind,data:reader.result});if(kind==='first'||kind==='last')state[kind]=true;else{const item=state.guides.find(x=>x.kind===kind);if(item)item.hasImage=true}invalidateVideo();showImage(kind);setStep(2);save();notify('图片已上传；请重新生成视频')}catch(err){notify(err.message)}};reader.readAsDataURL(f)}
$('#generateFrames').onclick=()=>action('frames');
$('#addGuide').onclick=()=>{if(state.guides.length>=8)return notify('最多添加 8 个中间关键帧');const kind='guide_'+crypto.randomUUID().replaceAll('-','').slice(0,16);const duration=Number($('#duration').value)||5;state.guides.push({kind,time:(duration/2).toFixed(2),pose:'',hasImage:false});invalidateVideo();save();renderGuides()};
function videoOptions(){return {use_last:$('#useLast').checked,guides:state.guides.map(x=>({kind:x.kind,time:Number(x.time)}))}}
$('#confirmFrames').onclick=()=>action('video',videoOptions());$('#regenerateVideo').onclick=()=>action('video',videoOptions());$('#goEditor').onclick=()=>{if(!state.video)return notify('请先生成视频');$('#candidates').scrollIntoView({behavior:'smooth'})};
$('#makeCandidates').onclick=()=>{const start=Number($('#rangeStart').value),end=Number($('#rangeEnd').value);if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return notify('请填写有效的开始与结束时间');action('candidates',{start,end,fps:Number($('#fps').value),offsets:[1,2,3].map(i=>Number($('#offset'+i).value))})};
$('#exportBtn').onclick=()=>action('export',{candidate:selected,set:state.candidateSet,alpha:$('#alpha').checked,color:$('#keyColor').value,tolerance:Number($('#tolerance').value)});
$('#sampleBg').onclick=()=>sampleBackground(false);
$('#markStart').onclick=()=>{if(!state.video)return notify('请先生成视频');$('#rangeStart').value=$('#video').currentTime.toFixed(2);invalidateCandidates();save()};
$('#markEnd').onclick=()=>{if(!state.video)return notify('请先生成视频');$('#rangeEnd').value=$('#video').currentTime.toFixed(2);invalidateCandidates();save()};
$('#fullRange').onclick=()=>{if(!state.video)return notify('请先生成视频');$('#rangeStart').value='0';$('#rangeEnd').value=$('#video').duration.toFixed(2);invalidateCandidates();save()};
for(const name of ['rangeStart','rangeEnd','fps','offset1','offset2','offset3'])$('#'+name).onchange=()=>{invalidateCandidates();save()};
for(const name of ['alpha','keyColor','tolerance'])$('#'+name).onchange=()=>{save();if(state.first)showImage('first');if(state.last)showImage('last');for(const g of state.guides)if(g.hasImage)showImage(g.kind);if(state.candidates)renderCandidates()};
$('#prompt').oninput=save;$('#actionMode').onchange=save;$('#useLast').onchange=save;$('#duration').onchange=()=>{invalidateVideo();save()};
for(const kind of ['first','last'])$('#'+kind+'Upload').onchange=e=>upload(e,kind);
$('#newProject').onclick=()=>{if(busy)return notify('请等待当前任务完成');project=crypto.randomUUID().replaceAll('-','');localStorage.setItem('frame-project',project);location.reload()};
(async()=>{try{token=(await(await fetch('/api/config')).json()).token;restore();poll()}catch(e){notify('本地工作台连接失败')}})();
