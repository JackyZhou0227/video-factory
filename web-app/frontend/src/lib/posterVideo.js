export const MAX_BATCH_SIZE = 50;
export const VIDEO_EXTENSIONS = [".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"];
export const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".bmp"];
export const NARRATION_EXTENSIONS = [".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"];
const GENERIC_MIME_TYPES = ["", "application/octet-stream", "binary/octet-stream"];
const IMAGE_MIME_TYPES = ["image/bmp", "image/jpeg", "image/png", "image/webp"];
const VIDEO_MIME_TYPES = [
  "video/avi", "video/mp4", "video/quicktime", "video/x-m4v",
  "video/x-matroska", "video/x-msvideo", "video/webm",
];
const AUDIO_MIME_TYPES = [
  "audio/aac", "audio/flac", "audio/m4a", "audio/mp4", "audio/mpeg", "audio/ogg",
  "audio/wav", "audio/wave", "audio/x-flac", "audio/x-m4a", "audio/x-wav",
];

function mimeType(file) {
  return (file.type || "").split(";", 1)[0].trim().toLowerCase();
}

function sourceType(file, outputMode) {
  const name = (file.name || "").toLowerCase();
  if (IMAGE_EXTENSIONS.some((extension) => name.endsWith(extension))) return "image";
  if (VIDEO_EXTENSIONS.some((extension) => name.endsWith(extension))) return "video";
  if (!name.includes(".")) {
    if (IMAGE_MIME_TYPES.includes(mimeType(file))) return "image";
    if (VIDEO_MIME_TYPES.includes(mimeType(file))) return "video";
    if (GENERIC_MIME_TYPES.includes(mimeType(file))) return outputMode;
  }
  return null;
}

export function classifySource(file, outputMode = "video") {
  const type = sourceType(file, outputMode);
  if (!type) return null;
  const allowed = type === "image" ? IMAGE_MIME_TYPES : VIDEO_MIME_TYPES;
  return [...GENERIC_MIME_TYPES, ...allowed].includes(mimeType(file)) ? type : null;
}

export function sourceFileError(file, outputMode) {
  const type = sourceType(file, outputMode);
  if (!type) return "type";
  if (!classifySource(file, outputMode)) return "mime";
  if (outputMode === "image" && type !== "image") return "mode";
  if (file.size > (type === "image" ? 20 : 500) * 1024 * 1024) return "size";
  if (file.size === 0) return "empty";
  return "";
}

export function selectSourceFiles(current, incoming, outputMode) {
  const key = (file) => `${file.name}:${file.size}:${file.lastModified}`;
  const keys = new Set(current.map(key));
  const additions = [];
  for (const file of incoming) {
    if (current.length + additions.length >= MAX_BATCH_SIZE) break;
    if (sourceFileError(file, outputMode) || keys.has(key(file))) continue;
    keys.add(key(file));
    additions.push(file);
  }
  return additions;
}

export function narrationFileError(file) {
  if (!NARRATION_EXTENSIONS.some((extension) => file.name.toLowerCase().endsWith(extension))) return "type";
  if (![...GENERIC_MIME_TYPES, ...AUDIO_MIME_TYPES].includes(mimeType(file))) return "mime";
  if (file.size > 50 * 1024 * 1024) return "size";
  if (!file.size) return "empty";
  return "";
}

export function posterDownloadFilename(filename, outputMode) {
  const name = String(filename || "").split(/[\\/]/).pop();
  const stem = name.replace(/\.[^.]*$/, "")
    .replace(/[^\p{L}\p{N}_.-]+/gu, "_")
    .replace(/^[._]+|[._]+$/g, "") || "asset";
  return `${stem}_poster.${outputMode === "image" ? "jpg" : "mp4"}`;
}

export function isTerminalPosterStatus(status) {
  return ["completed", "partial_failed", "failed", "cancelled"].includes(status);
}

function knownDuration(value) {
  const duration = Number(value);
  return Number.isFinite(duration) && duration > 0 ? duration : null;
}

export function estimatePosterAsset(source, { narration = null, bgm = null } = {}) {
  const narrationDuration = knownDuration(narration?.duration);
  if (source.sourceType === "image") {
    return {
      targetDuration: narration ? narrationDuration : knownDuration(bgm?.duration),
      videoSpeed: null,
      narrationSpeed: narration ? 1 : null,
      requiresAudio: !narration && !bgm,
    };
  }
  const videoDuration = knownDuration(source.duration);
  const targetDuration = narration
    ? (videoDuration && narrationDuration ? Math.min(videoDuration, narrationDuration) : null)
    : videoDuration;
  return {
    targetDuration,
    videoSpeed: narration ? (targetDuration ? videoDuration / targetDuration : null) : 1,
    narrationSpeed: narration && targetDuration ? narrationDuration / targetDuration : null,
    requiresAudio: false,
  };
}
