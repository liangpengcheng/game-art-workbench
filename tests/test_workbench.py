import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('studio',ROOT/'server.py')
studio=importlib.util.module_from_spec(spec); spec.loader.exec_module(studio)

class WorkbenchTests(unittest.TestCase):
    def test_empty_comfy_response_is_success(self):
        class EmptyResponse:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b''
        with patch.object(studio.urllib.request,'urlopen',return_value=EmptyResponse()):
            self.assertEqual(studio.request('/free',{'unload_models':True}),{})
    def test_idle_prompt_keeps_request_and_constrains_action(self):
        prompt='一个僵尸原地待机'
        self.assertEqual(studio.action_mode({'action_mode':'auto'},prompt),'idle')
        result=studio.motion_prompt(prompt,'idle')
        self.assertIn(prompt,result)
        self.assertIn('No walking',result)
        self.assertIn('no new objects',result)

    def test_multiframe_graph_uses_time_anchors(self):
        graphs=[]
        def capture(graph,endpoint=None): graphs.append(graph); return 'fake.mp4'
        with patch.object(studio,'prepare_input',side_effect=lambda p:str(p)),patch.object(studio,'queue',side_effect=capture):
            studio.video('idle',Path('first.png'),Path('last.png'),1.5,[(Path('middle-a.png'),12),(Path('middle-b.png'),24)])
        g=graphs[0]
        self.assertEqual(g['6']['inputs']['length'],39)
        self.assertEqual(g['last_output_anchor']['inputs']['frame_idx'],35)
        self.assertEqual(g['guide_anchor_0']['inputs']['frame_idx'],12)
        self.assertEqual(g['guide_anchor_1']['inputs']['frame_idx'],24)
        self.assertEqual(g['8']['inputs']['conditioning'],['guide_anchor_1',0])

    def test_duplicate_guide_times_are_rejected_before_generation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(studio,'OUT',Path(directory)):
            pid='b'*32;p=studio.project(pid)
            for name in ('first.png','guide_aaaaaaaaaaaaaaaa.png','guide_bbbbbbbbbbbbbbbb.png'):
                Image.new('RGB',(2,2),'white').save(p/name)
            studio.worker('video',{'project':pid,'prompt':'僵尸待机','duration':2,'guides':[{'kind':'guide_aaaaaaaaaaaaaaaa','time':0.5},{'kind':'guide_bbbbbbbbbbbbbbbb','time':0.51}]})
            self.assertEqual(studio.JOB['state'],'error')
            self.assertIn('关键帧时间过近',studio.JOB['error'])
    def test_color_key_preserves_existing_alpha(self):
        img=Image.new('RGBA',(2,1),(238,238,238,255));img.putpixel((1,0),(10,10,10,127))
        result=studio.keyed(img,(238,238,238),28)
        self.assertEqual(result.getpixel((0,0))[3],0)
        self.assertEqual(result.getpixel((1,0))[3],127)

    def test_complete_candidates_rotation_and_export(self):
        ffmpeg=shutil.which('ffmpeg'); ffprobe=shutil.which('ffprobe')
        if not ffmpeg or not ffprobe:self.skipTest('FFmpeg and ffprobe required')
        with tempfile.TemporaryDirectory() as directory, patch.object(studio,'OUT',Path(directory)),patch.object(studio,'FFMPEG',ffmpeg),patch.object(studio,'FFPROBE',ffprobe):
            pid='a'*32;p=studio.project(pid)
            studio.runff(['-f','lavfi','-i','testsrc=size=64x64:rate=24:duration=2','-c:v','libx264','-pix_fmt','yuv420p',str(p/'video.mp4')])
            studio.worker('candidates',{'project':pid,'start':0,'end':2,'fps':12,'offsets':[0,1,-1]})
            self.assertEqual(studio.JOB['state'],'done',studio.JOB.get('error'))
            result=studio.JOB['result'];self.assertEqual(result['frame_count'],24)
            for file in result['candidates']: self.assertAlmostEqual(studio.probe(p/file)[0],2.0,delta=0.1)
            studio.worker('export',{'project':pid,'set':result['set'],'candidate':2,'alpha':False,'color':'#eeeeee','tolerance':28})
            self.assertEqual(studio.JOB['state'],'done',studio.JOB.get('error'))
            with zipfile.ZipFile(p/studio.JOB['result']['archive']) as z:
                meta=json.loads(z.read('animation.json'));self.assertEqual(meta['frame_count'],24);self.assertEqual(meta['loop_offset_frames'],1)
                actual=Image.open(io.BytesIO(z.read('frames/frame_0000.png'))).convert('RGB')
                expected=Image.open(p/result['set']/'frames'/'frame_0001.png').convert('RGB')
                self.assertIsNone(ImageChops.difference(actual,expected).getbbox())
            studio.worker('candidates',{'project':pid,'start':0.5,'end':1.5,'fps':12,'offsets':[0,2,-2]})
            self.assertEqual(studio.JOB['state'],'done',studio.JOB.get('error'))
            trimmed=studio.JOB['result'];self.assertEqual(trimmed['frame_count'],12)
            self.assertAlmostEqual(studio.probe(p/trimmed['candidates'][2])[0],1.0,delta=0.1)

if __name__=='__main__':unittest.main()
