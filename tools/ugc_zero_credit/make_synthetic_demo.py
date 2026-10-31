#!/usr/bin/env python3
"""Generate entirely synthetic, rights-clear media for smoke tests. No network/APIs."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent
MEDIA=ROOT/'examples'/'demo_media'

def run(*args):
    subprocess.run(['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-y',*map(str,args)],check=True,timeout=120)

def create(force:bool=False):
    MEDIA.mkdir(parents=True,exist_ok=True)
    outputs=[MEDIA/x for x in ('presentation_demo.mp4','produit.png','petales.png','music_original.wav')]
    if not force and all(f.is_file() and f.stat().st_size for f in outputs):return outputs
    # Color cards are deliberately fictitious and never imply endorsement by a real brand.
    for name,color in [('produit.png','0x8F526F'),('petales.png','0xAE7896')]:
        target=MEDIA/name
        run('-f','lavfi','-i',f'color=c={color}:s=1080x1920:r=1:d=1',
            '-vf',"drawbox=x=350:y=370:w=380:h=850:color=0xDDB3C1:t=fill,drawbox=x=390:y=420:w=300:h=740:color=0x7D365A:t=fill,drawbox=x=410:y=780:w=260:h=65:color=0xF9E5EA:t=fill",
            '-frames:v','1','-update','1',target)
    run('-f','lavfi','-i','sine=frequency=220:sample_rate=48000:duration=5',
        '-filter:a','volume=0.07',MEDIA/'music_original.wav')
    run('-f','lavfi','-i','color=c=0x5B3561:s=540x960:r=30:d=4',
        '-f','lavfi','-i','anoisesrc=color=pink:amplitude=0.2:seed=1234:sample_rate=48000:duration=4',
        '-vf',"drawbox=x=170:y=190:w=210:h=560:color=0xD79BC1:t=fill,drawbox=x=203:y=270:w=145:h=400:color=0x873A68:t=fill",
        '-af','volume=0.65','-c:v','libx264','-pix_fmt','yuv420p','-preset','veryfast',
        '-crf','24','-c:a','aac','-b:a','128k','-ar','48000','-t','4',MEDIA/'presentation_demo.mp4')
    return outputs

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--force',action='store_true');args=a.parse_args()
    for p in create(args.force):print(f'{p}: {p.stat().st_size} bytes')
