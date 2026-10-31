#!/usr/bin/env python3
"""Check local rendering / offline lip-sync prerequisites without running paid models."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import sys


def _command(args,timeout=6):
    try:
        p=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
        return p.stdout.strip() if p.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):return None


def doctor(path:Path) -> dict:
    disk=shutil.disk_usage(path.resolve())
    proc_mem=None
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                proc_mem=round(int(line.split()[1])/1024**2,2)
                break
    except (OSError,ValueError,IndexError):pass
    nv=_command(['nvidia-smi','--query-gpu=name,memory.total,memory.free','--format=csv,noheader,nounits']) if shutil.which('nvidia-smi') else None
    gpu=[]
    if nv:
        for line in nv.splitlines():
            p=[s.strip() for s in line.split(',')]
            if len(p)==3:
                try:gpu.append({'name':p[0],'vram_total_mb':int(p[1]),'vram_free_mb':int(p[2])})
                except ValueError:continue
    try:
        import cv2
        cascade=Path(cv2.data.haarcascades,'haarcascade_frontalface_default.xml')
        vision={'available':True,'version':cv2.__version__,'cascade_bundled':cascade.is_file()}
    except ImportError:
        vision={'available':False,'hint':'pip install opencv-python-headless numpy (local, sans API)'}
    ffmpeg=_command(['ffmpeg','-version']) if shutil.which('ffmpeg') else None
    ffprobe=_command(['ffprobe','-version']) if shutil.which('ffprobe') else None
    summary={'render_local_ready':bool(ffmpeg and ffprobe and disk.free>200*1024*1024),
             'face_qa_ready':bool(vision['available'] and vision.get('cascade_bundled')),
             'gpu_seen':bool(gpu),'neural_lip_sync_ready':False,
             'reason':'Pas de modèle de lip-sync chargé ou validé: la présence d’un GPU ne suffit pas.'}
    return {'python':sys.version.split()[0], 'ffmpeg':ffmpeg.splitlines()[0] if ffmpeg else None,
            'ffprobe':ffprobe.splitlines()[0] if ffprobe else None,
            'opencv':vision,'gpu':gpu,'free_disk_gib':round(disk.free/1024**3,2),
            'available_ram_gib':proc_mem,'summary':summary,'credit_cost':0,'network_calls':0}


if __name__=='__main__':
    print(json.dumps(doctor(Path('.')),indent=2,ensure_ascii=False))
