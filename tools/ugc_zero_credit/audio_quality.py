#!/usr/bin/env python3
"""Offline EBU R128 integrated LUFS + true peak. Never connects to a service."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess


def analyze_audio(path: Path) -> dict:
    """Informational acoustic metrics; no claim of subjective voice quality."""
    path=Path(path)
    if not path.is_file():
        raise ValueError(f"Audio/MP4 introuvable: {path}")
    proc=subprocess.run([
        'ffmpeg','-hide_banner','-nostdin','-i',str(path),'-vn',
        '-af','ebur128=peak=true','-f','null','-'],capture_output=True,text=True,timeout=180)
    log=proc.stderr
    result={'measurement_available':False,'integrated_lufs':None,'true_peak_dbtp':None,
            'warnings':[],'method':'FFmpeg ebur128=peak=true (ITU-R BS.1770)'}
    if proc.returncode:
        result['warnings'].append('FFmpeg ebur128 a échoué: '+log[-200:])
        return result
    # The last summary is authoritative, not rolling momentary readings.
    match=re.search(r'Summary:\s*Integrated loudness:\s*I:\s*([-+\d.]+)\s*LUFS.*?True peak:\s*Peak:\s*([-+\d.]+)\s*dBFS',log,re.S)
    if not match:
        result['warnings'].append('Résumé LUFS/true peak absent dans la sortie FFmpeg')
        return result
    lufs=float(match.group(1));peak=float(match.group(2))
    result.update(measurement_available=True,integrated_lufs=lufs,true_peak_dbtp=peak)
    if lufs< -19:result['warnings'].append('Mixage potentiellement trop faible (LUFS < -19)')
    if lufs> -12:result['warnings'].append('Mixage potentiellement trop fort (LUFS > -12)')
    if peak > -1.0:result['warnings'].append('True peak > -1 dBTP : risque de saturation après réencodage')
    return result


def main():
    parser=argparse.ArgumentParser(description='Contrôle audio R128 entièrement local')
    parser.add_argument('file')
    args=parser.parse_args()
    print(json.dumps(analyze_audio(Path(args.file)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
