/** Dependency-free deterministic selectors for offline browser editing. */
export const THEMES = Object.freeze({
  fitness: ["fitness", "musculation", "entrainement", "progression", "fitfrance"],
  motivation: ["motivation", "discipline", "mental", "perseverance", "mindset"],
  sport: ["sport", "training", "performance", "progression"],
  lifestyle: ["lifestyle", "habitudes", "equilibre", "quotidien"],
  auto: ["progression", "inspiration"],
});
export const FORMATS = Object.freeze({
  vertical: {label: "Reel · 9:16", width: 720, height: 1280},
  youtube: {label: "YouTube · 16:9", width: 1280, height: 720},
});
export const EXPORT_TYPES = [
  {type: "video/mp4;codecs=avc1.42E01E,mp4a.40.2", ext: "mp4"},
  {type: "video/mp4", ext: "mp4"},
  {type: "video/webm;codecs=vp9,opus", ext: "webm"},
  {type: "video/webm;codecs=vp8,opus", ext: "webm"},
  {type: "video/webm", ext: "webm"},
];
export const MAX_TARGET_SECONDS = 180;

export function formatTime(seconds) {
  const s = Math.floor(Math.max(0, Number(seconds) || 0));
  const m = Math.floor(s / 60);
  return (m >= 60 ? Math.floor(m / 60) + " h " : "") +
    (m % 60) + " min " + String(s % 60).padStart(2, "0") + " s";
}

export function safeDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0.5) {
    throw new Error("Impossible de lire la durée de cette vidéo.");
  }
  return seconds;
}

/** Uses downscaled luma changes, contrast and edge detail. Not person or exercise recognition. */
export function frameSignature(pixels, width, height) {
  if (!pixels || !width || !height || pixels.length < width * height * 4) {
    throw new Error("Image d'analyse invalide");
  }
  const grey = new Float32Array(width * height);
  let sum = 0, sumSquare = 0, edges = 0;
  for (let i = 0; i < grey.length; i++) {
    const j = i * 4;
    const luma = .2126 * pixels[j] + .7152 * pixels[j + 1] + .0722 * pixels[j + 2];
    grey[i] = luma;
    sum += luma;
    sumSquare += luma * luma;
    if (i % width && i >= width) {
      edges += Math.abs(luma - grey[i - 1]) + Math.abs(luma - grey[i - width]);
    }
  }
  const mean = sum / grey.length;
  const contrast = Math.sqrt(Math.max(0, sumSquare / grey.length - mean * mean));
  return {grey, mean, contrast, detail: edges / grey.length};
}

export function frameScore(current, previous) {
  if (!current) return 0;
  const light = Math.max(0, 1 - Math.abs(current.mean - 118) / 118);
  const contrast = Math.min(1, current.contrast / 70);
  const detail = Math.min(1, current.detail / 90);
  let motion = 0;
  if (previous && previous.grey.length === current.grey.length) {
    for (let i = 0; i < current.grey.length; i++) {
      motion += Math.abs(current.grey[i] - previous.grey[i]);
    }
    motion = Math.min(1, motion / current.grey.length / 64);
  }
  return Math.round((.15 + .22 * light + .23 * contrast + .15 * detail + .25 * motion) * 1000) / 1000;
}

/** Pick distributed candidates from across source, then fill duration with top-ranked nonoverlapping clips. */
export function selectClips(samples, duration, targetSeconds, cutLength = 5) {
  safeDuration(duration);
  if (!Number.isFinite(targetSeconds) || targetSeconds < 1 || targetSeconds > MAX_TARGET_SECONDS) {
    throw new Error("Durée de montage invalide.");
  }
  const target = Math.min(duration, targetSeconds);
  if (duration <= target + .25) return [{start: 0, end: duration, score: 1}];
  const count = Math.max(1, Math.ceil(target / cutLength));
  const bucketCount = Math.min(count, Math.max(1, Math.floor(duration / cutLength)));
  const candidates = samples.filter(s => Number.isFinite(s.time) && Number.isFinite(s.score))
    .map(s => ({
      start: Math.max(0, Math.min(duration - Math.min(cutLength, duration),
                                s.time - cutLength / 2)),
      end: 0, score: Math.max(0, s.score),
    }));
  if (!candidates.length) {
    for (let i = 0; i < bucketCount; i++) {
      candidates.push({start: Math.min(duration - cutLength,
        duration * (i + .5) / bucketCount - cutLength / 2), end: 0, score: .3});
    }
  }
  for (const c of candidates) c.end = Math.min(duration, c.start + cutLength);
  const buckets = Array.from({length: bucketCount}, () => []);
  for (const candidate of candidates) {
    buckets[Math.min(bucketCount - 1, Math.floor(candidate.start / duration * bucketCount))].push(candidate);
  }
  const representatives = buckets.map((bucket, i) => {
    const center = duration * (i + .5) / bucketCount;
    return bucket.sort((a, b) => (b.score - a.score) ||
      (Math.abs(a.start - center) - Math.abs(b.start - center)))[0];
  }).filter(Boolean);
  const ranked = [...representatives, ...candidates.sort((a,b) => (b.score - a.score) || a.start)];
  const selected = [];
  let remaining = target;
  for (const c of ranked) {
    if (remaining < .5) break;
    if (selected.some(s => c.start < s.end - .01 && c.end > s.start + .01)) continue;
    const length = Math.min(c.end - c.start, remaining);
    if (length < .5) continue;
    selected.push({start: +c.start.toFixed(3), end: +(c.start + length).toFixed(3),
      score: c.score});
    remaining -= length;
  }
  if (remaining >= .5) {
    // Fill uncovered gaps safely. Avoid silently exporting fewer seconds than asked for.
    let cursor = 0;
    for (const s of [...selected].sort((a,b) => a.start - b.start).concat([{start:duration,end:duration}])) {
      if (remaining < .5) break;
      if (s.start - cursor >= .5) {
        const length = Math.min(remaining, s.start - cursor);
        selected.push({start:+cursor.toFixed(3),end:+(cursor+length).toFixed(3),score:0});
        remaining -= length;
      }
      cursor = Math.max(cursor, s.end);
    }
  }
  return selected.sort((a,b) => a.start - b.start);
}

export function chooseRecorderType(MediaRecorderImpl) {
  if (!MediaRecorderImpl || typeof MediaRecorderImpl.isTypeSupported !== "function") return null;
  return EXPORT_TYPES.find(t => MediaRecorderImpl.isTypeSupported(t.type)) || null;
}

export function makePublication(theme, clips, duration, format, extension) {
  const selectedTheme = Object.hasOwn(THEMES, theme) ? theme : "auto";
  const tags = [...THEMES[selectedTheme]];
  const lines = {
    fitness: "Chaque séance compte. La progression se construit avec de la régularité.",
    motivation: "La discipline se cultive chaque jour. L'important, c'est de continuer.",
    sport: "Chaque entraînement est une occasion de progresser.",
    lifestyle: "Construire de bonnes habitudes, un jour à la fois.",
    auto: "Un moment à partager.",
  };
  return {
    description: lines[selectedTheme] + "\n\nEt toi, quel est ton prochain objectif ?\n\n" +
      tags.map(t=>"#"+t).join(" "),
    hashtags: tags,
    analysis: "Analyse visuelle des plans, contraste et mouvement (aucune reconnaissance d'exercice ni transcription).",
    clips: clips.map(c=>({start:c.start,end:c.end,score:c.score})),
    sourceDuration: duration, format, extension, theme: selectedTheme,
    renderedSeconds: clips.reduce((total,clip)=>total+clip.end-clip.start,0),
  };
}

export function fittedCrop(srcW, srcH, destW, destH) {
  if (![srcW,srcH,destW,destH].every(n=>Number.isFinite(n) && n>0)) {
    throw new Error("Dimensions vidéo invalides");
  }
  const sourceRatio = srcW / srcH, destRatio = destW / destH;
  if (sourceRatio > destRatio) {
    const width = srcH * destRatio;
    return {sx:(srcW-width)/2, sy:0, sw:width, sh:srcH};
  }
  const height = srcW / destRatio;
  return {sx:0, sy:(srcH-height)/2, sw:srcW, sh:height};
}
