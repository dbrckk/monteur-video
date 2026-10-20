"""Original royalty-free instrumental beats generated locally without external music APIs.

The arrangements are algorithmic and deterministic: no copyrighted recordings,
third-party stems, samples or model weights are used.
"""
from __future__ import annotations

import math
import os
import random
import struct
import wave
from array import array
from pathlib import Path
from typing import Callable

from editor import execute, probe_media

SAMPLE_RATE = 22050
TRACKS = {
    "fitness": {"bpm": 144, "root": 41.203, "name": "Power Session", "style": "trap / gym"},
    "sport": {"bpm": 152, "root": 43.654, "name": "Sprint Mode", "style": "athletic / electronic"},
    "motivation": {"bpm": 128, "root": 36.708, "name": "Rise Again", "style": "cinematic / drive"},
    "lifestyle": {"bpm": 116, "root": 65.406, "name": "Daylight Motion", "style": "chill / groove"},
    "auto": {"bpm": 136, "root": 41.203, "name": "Momentum", "style": "modern / uplifting"},
}
SOUND_LEVELS = {"mute": 0.0, "low": 0.20, "auto": 0.0}


def select_music_profile(theme: str, samples: list, *,
                         scene_count: int = 0, source_seconds: float = 0) -> dict:
    """Match music to measured visual energy, not just the chosen category.

    Only deterministic, non-biometric FFmpeg signals are used. Scores do not
    claim knowledge of depicted people, emotion, or exercise type.
    """
    preset = TRACKS.get(theme, TRACKS["auto"])
    visible = [x for x in samples
               if 25 <= x.luminance <= 230 and x.detail >= 2]
    if not visible:
        return {"bpm": preset["bpm"], "title": preset["name"],
                "style": preset["style"], "root": preset["root"],
                "energy": "medium", "motion_score": None,
                "scene_rate": None, "selection_method": "theme_fallback"}
    motion = sorted(max(0.0, min(24.0, x.motion)) for x in visible)
    active_motion = motion[int(0.75 * (len(motion) - 1))]
    scene_rate = (60.0 * scene_count / source_seconds
                  if source_seconds > 0 else 0.0)
    visual_energy = min(1.0, active_motion / 12)
    cutting_energy = min(1.0, scene_rate / 22)
    combined = 0.77 * visual_energy + 0.23 * cutting_energy
    if combined >= 0.65:
        energy = "high"
        bpm = 154 if theme in {"sport", "fitness"} else 144
        name, style = "Peak Momentum", "high-energy workout / bass"
    elif combined >= 0.32:
        energy = "medium"
        bpm = 136 if theme in {"sport", "fitness"} else 124
        name, style = "Forward Motion", "pulsing training / electronic"
    else:
        energy = "low"
        bpm = 108 if theme in {"lifestyle", "motivation"} else 120
        name, style = "Steady Focus", "minimal groove / warm-up"
    return {"bpm": bpm, "title": name, "style": style,
            "root": preset["root"], "energy": energy,
            "motion_score": round(active_motion, 2),
            "scene_rate": round(scene_rate, 2),
            "selection_method": "visual_motion_scene_density"}


def beat_duration(theme: str) -> float:
    return 60.0 / TRACKS.get(theme, TRACKS["auto"])["bpm"]


def create_original_beat(theme: str, destination: Path, bars: int = 8,
                         music_profile: dict | None = None) -> dict:
    """Generate an original 8-bar drum+bass+lead loop in memory-limited PCM.

    A loop lasts 13–17 seconds and is repeated seamlessly while exporting the
    finished master. Computation cost does not grow with input or output length.
    """
    if bars < 2 or bars > 16:
        raise ValueError("Nombre de mesures invalide")
    preset = {**TRACKS.get(theme, TRACKS["auto"]), **(music_profile or {})}
    beat = 60.0 / preset["bpm"]
    length = bars * 4 * beat
    count = math.ceil(length * SAMPLE_RATE)
    pcm = array("f", [0.0]) * count
    rng = random.Random(0x4D4F4E54 + preset["bpm"])
    intensity = {"low": 0.63, "medium": 0.83, "high": 1.0}.get(
        preset.get("energy", "medium"), 0.83)

    def add_kick(start: float, intensity: float = 1.0) -> None:
        offset = round(start * SAMPLE_RATE)
        for j in range(min(int(0.33 * SAMPLE_RATE), count - offset)):
            t = j / SAMPLE_RATE
            phase = 2 * math.pi * (47 * t + 88 * 0.026 * (1 - math.exp(-t / 0.026)))
            click = 0.13 * math.sin(2 * math.pi * 1900 * t) * math.exp(-t * 150)
            pcm[offset+j] += intensity * (0.64 * math.sin(phase) * math.exp(-t * 14.5) + click)

    def add_snare(start: float, intensity: float = 1.0) -> None:
        offset = round(start * SAMPLE_RATE)
        for j in range(min(int(0.19 * SAMPLE_RATE), count - offset)):
            t = j / SAMPLE_RATE
            noise = rng.uniform(-1, 1)
            tone = math.sin(2 * math.pi * 182 * t) * math.exp(-t * 25)
            pcm[offset+j] += intensity * (0.23 * noise * math.exp(-t * 17) +
                                           0.13 * tone)

    def add_hat(start: float, intensity: float = 1.0) -> None:
        offset = round(start * SAMPLE_RATE)
        for j in range(min(int(0.065 * SAMPLE_RATE), count - offset)):
            t = j / SAMPLE_RATE
            noise = rng.uniform(-1, 1)
            pcm[offset+j] += intensity * 0.095 * noise * math.exp(-t * 69)

    def add_bass(start: float, length_seconds: float, frequency: float,
                 intensity: float = 1.0) -> None:
        offset = round(start * SAMPLE_RATE)
        for j in range(min(int(length_seconds * SAMPLE_RATE), count - offset)):
            t = j / SAMPLE_RATE
            envelope = min(1.0, t * 45) * math.exp(-t * 2.9)
            wobble = 1.0 + 0.05 * math.sin(2 * math.pi * 3.2 * t)
            fundamental = math.sin(2 * math.pi * frequency * t)
            overtone = 0.24 * math.sin(2 * math.pi * frequency * 2 * t)
            pcm[offset+j] += intensity * 0.25 * envelope * wobble * (fundamental + overtone)

    def add_lead(start: float, frequency: float, duration: float) -> None:
        offset = round(start * SAMPLE_RATE)
        for j in range(min(int(duration * SAMPLE_RATE), count - offset)):
            t = j / SAMPLE_RATE
            attack = min(1.0, t * 90)
            release = math.exp(-t * 4.5)
            pcm[offset+j] += 0.07 * attack * release * (
                math.sin(2 * math.pi * frequency * t) +
                0.28 * math.sin(2 * math.pi * frequency * 2.002 * t)
            )

    # Four-bar harmonic motion (minor i-bVI-bIII-bVII) and rhythmic variations.
    progression = [0, 8, 3, 10, 0, 8, 3, 10]
    bass_semitones = [0, 0, 7, 0]
    for bar in range(bars):
        start = bar * 4 * beat
        root = preset["root"] * 2 ** (progression[bar % len(progression)] / 12)
        for pulse in range(4):
            at = start + pulse * beat
            if pulse in (0, 2) or (bar >= 4 and pulse == 3):
                add_kick(at, intensity * (1.0 if pulse == 0 else 0.84))
            if pulse in (1, 3):
                add_snare(at, intensity * 0.91)
            add_hat(at, intensity * (0.68 if pulse % 2 == 0 else 0.48))
            add_hat(at + beat / 2, intensity * (0.44 + (0.14 if bar >= 4 else 0)))
            add_bass(at, beat * 0.78, root * 2 ** (bass_semitones[pulse] / 12), intensity)
        if bar % 2 == 1:
            add_kick(start + 3.5 * beat, 0.62 * intensity)
        for position, interval in ((0, 12), (1.5, 15), (2.5, 19)):
            add_lead(start + position * beat, root * 2 ** (interval / 12),
                     beat * 0.83)
    destination.parent.mkdir(parents=True, exist_ok=True)
    peak = max(0.1, max(abs(x) for x in pcm))
    scale = min(1.0, 0.90 / peak)
    with wave.open(str(destination), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        for offset in range(0, count, 32768):
            block = pcm[offset:offset+32768]
            stream.writeframesraw(struct.pack("<" + "h" * len(block),
                                             *(int(max(-1.0, min(1.0, x * scale)) * 32767)
                                               for x in block)))
        stream.writeframes(b"")
    return {"title": preset.get("title", preset["name"]), "style": preset["style"], "bpm": preset["bpm"],
            "energy": preset.get("energy", "medium"),
            "selection_method": preset.get("selection_method", "theme_fallback"),
            "origin": "original_generated", "copyright": "original_instrumental",
            "loop_seconds": round(length, 3)}


def _original_music_mix(duration: float, original_volume: float) -> tuple[str, float]:
    """FFmpeg graph with measured-source sidechain ducking and bounded output.

    The sidechain responds only to actual microphone energy; it does not claim
    speech recognition. Pad the key and source to video duration so an early
    microphone EOF cannot truncate the music or picture.
    """
    fade_start = max(0.0, duration - 0.65)
    music_volume = 0.72 if original_volume > 0 else 0.88
    beat = (f"[1:a]aresample=48000,volume={music_volume:.2f},"
            f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d=0.18,"
            f"afade=t=out:st={fade_start:.3f}:d=0.65")
    if original_volume <= 0:
        return beat + ",alimiter=limit=0.93[out]", music_volume
    graph = (f"[0:a]aresample=48000,apad=whole_dur={duration:.3f},"
             f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
             "asplit=2[key][ambient_source];"
             f"[ambient_source]volume={original_volume:.2f}[ambient];"
             + beat + "[beat];"
             "[beat][key]sidechaincompress="
             "threshold=0.035:ratio=6:attack=22:release=260:detection=rms[ducked];"
             "[ambient][ducked]amix=inputs=2:duration=longest:normalize=0,"
             "alimiter=limit=0.93[out]")
    return graph, music_volume


def add_soundtrack(video: Path, theme: str, *, sound_mode: str = "auto",
                   voice_present: bool = False,
                   music_profile: dict | None = None,
                   progress: Callable[[float, str], None] | None = None) -> dict:
    """Mix generated royalty-free music continuously over the assembled video.

    Sound mode auto keeps original audio at 20% only if actual speech evidence
    exists; otherwise it is muted. A user may explicitly force low or mute.
    """
    if sound_mode not in SOUND_LEVELS:
        raise ValueError("Mode audio inconnu")
    if not video.exists():
        raise FileNotFoundError("Montage vidéo absent")
    master_info = probe_media(video)
    requested_volume = (0.2 if voice_present else 0.0) if sound_mode == "auto" else SOUND_LEVELS[sound_mode]
    original_volume = requested_volume if master_info["has_audio"] else 0.0
    loop_file = video.with_suffix(".original-beat.wav")
    mixed = video.with_name(video.stem + ".music.partial.mp4")
    mixed.unlink(missing_ok=True)
    try:
        info = create_original_beat(theme, loop_file, music_profile=music_profile)
        duration = master_info["duration"]
        if progress:
            progress(0.95, "music")
        mix, music_volume = _original_music_mix(duration, original_volume)
        execute(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                 "-i", str(video), "-stream_loop", "-1", "-i", str(loop_file),
                 "-filter_complex", mix,
                 "-map", "0:v:0", "-map", "[out]",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                 "-ar", "48000", "-ac", "2",
                 "-movflags", "+faststart", "-shortest", str(mixed)], timeout=300)
        probe_media(mixed)
        os.replace(mixed, video)
        if progress:
            progress(0.99, "music")
        info.update({"original_audio_volume": original_volume,
                     "source_audio_mode": sound_mode,
                     "music_volume": music_volume,
                     "dynamic_source_ducking": original_volume > 0,
                     "music_generated": True})
        return info
    finally:
        mixed.unlink(missing_ok=True)
        loop_file.unlink(missing_ok=True)


def prepare_instagram_reel(video: Path, *, sound_mode: str = "auto",
                           voice_present: bool = False,
                           progress: Callable[[float, str], None] | None = None) -> dict:
    """Export a silent/quiet source ready for native Instagram music addition.

    Critically: no unauthorized third-party recording is downloaded or copied.
    Instagram supplies the chosen commercial recording in its own composer.
    """
    if sound_mode not in SOUND_LEVELS:
        raise ValueError("Mode audio inconnu")
    if not video.is_file():
        raise FileNotFoundError("MP4 original introuvable")
    volume = (0.2 if voice_present else 0.0) if sound_mode == "auto" else SOUND_LEVELS[sound_mode]
    partial = video.with_name(video.stem + ".ig-audio.partial.mp4")
    partial.unlink(missing_ok=True)
    if progress:
        progress(0.95, "music")
    try:
        command = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                   "-i", str(video), "-map", "0:v:0", "-c:v", "copy"]
        if volume > 0:
            command += ["-map", "0:a:0?", "-af", f"volume={volume:.2f}",
                        "-c:a", "aac", "-b:a", "128k", "-ar", "48000"]
        else:
            command += ["-an"]
        command += ["-movflags", "+faststart", str(partial)]
        execute(command, timeout=180)
        probe_media(partial)
        os.replace(partial, video)
        if progress:
            progress(0.99, "music")
        return {"mode": "instagram_native", "music_embedded": False,
                "source_audio_mode": sound_mode, "original_audio_volume": volume,
                "next_action": "Dans Instagram, ajouter la musique recommandée à ce Reel",
                "licensing": "La musique sous licence est ajoutée dans l'application Instagram"}
    finally:
        partial.unlink(missing_ok=True)
