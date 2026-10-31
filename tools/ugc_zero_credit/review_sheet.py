#!/usr/bin/env python3
"""Offline storyboard from the ACTUAL exported MP4. No AI or network.

Pillow is optional: the JPG contact sheet uses Pillow if available.
Audio/video export does not require Pillow.
"""
from __future__ import annotations
import argparse
import io
import json
import math
from pathlib import Path
import subprocess
from ugc import probe,sha256


def make_contact_sheet(video:Path,destination:Path,*,count=9,tile_width=270):
    if not 3 <= count <= 24:raise ValueError('3 à 24 images autorisées')
    if not 140 <= tile_width <= 540:raise ValueError('Largeur des vignettes hors limites')
    if not video.is_file():raise ValueError('MP4 introuvable')
    try:
        from PIL import Image,ImageDraw,ImageFont
    except ImportError as e:
        raise RuntimeError('Installer Pillow (facultatif): python -m pip install Pillow') from e
    meta=probe(video)
    duration=float(meta['format']['duration'])
    tiles=[];samples=[]
    for i in range(count):
        t=round(min(max(duration-.05,0),duration*(i+.5)/count),3)
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-ss',str(t),'-i',str(video),
             '-frames:v','1','-vf',f'scale={tile_width}:-2:flags=lanczos','-f','image2pipe','-vcodec','mjpeg','-']
        result=subprocess.run(cmd,capture_output=True,timeout=45)
        if result.returncode or not result.stdout:
            raise RuntimeError(f'Impossible de prélever une image à {t}s : '+result.stderr.decode(errors='replace')[-250:])
        with Image.open(io.BytesIO(result.stdout)) as frame:
            image=frame.convert('RGB').copy()
        samples.append(t);tiles.append(image)
    columns=3;rows=math.ceil(count/columns);pad=12;label=37
    height=max(im.height for im in tiles)
    canvas=Image.new('RGB',(columns*(tile_width+pad)+pad, rows*(height+label+pad)+pad),(23,23,30))
    draw=ImageDraw.Draw(canvas)
    try:font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',19)
    except OSError:font=ImageFont.load_default()
    for i,(t,frame) in enumerate(zip(samples,tiles)):
        x=pad+(i%columns)*(tile_width+pad);y=pad+(i//columns)*(height+label+pad)
        canvas.paste(frame,(x,y))
        draw.text((x+5,y+height+7),f'{t:05.1f} s',fill=(250,240,240),font=font)
    destination.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(destination,quality=89,optimize=True)
    return {'video':str(video),'contact_sheet':str(destination),'frames':count,
            'timestamps':samples,'resolution':canvas.size,'source_sha256':sha256(video),
            'cost_credits':0,'network_requests':0}


def main():
    p=argparse.ArgumentParser(description='Planche de vérification issue du véritable MP4, hors ligne')
    p.add_argument('video');p.add_argument('--output',required=True);p.add_argument('--frames',type=int,default=9)
    a=p.parse_args()
    print(json.dumps(make_contact_sheet(Path(a.video),Path(a.output),count=a.frames),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
