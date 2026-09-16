import assert from "node:assert/strict";
import test from "node:test";
import {
  classifySource,
  estimatePosterAsset,
  isTerminalPosterStatus,
  narrationFileError,
  posterDownloadFilename,
  selectSourceFiles,
  sourceFileError,
} from "./posterVideo.js";

test("source classification validates supported extensions and matching MIME types", () => {
  for (const [file, expected] of [
    [{ name: "photo.PNG", type: "" }, "image"],
    [{ name: "clip.MKV", type: "application/octet-stream" }, "video"],
    [{ name: "photo", type: "image/jpeg" }, "image"],
    [{ name: "clip", type: "video/mp4" }, "video"],
    [{ name: "misnamed.mp4", type: "image/png" }, null],
    [{ name: "misnamed.jpg", type: "video/mp4" }, null],
    [{ name: "animated.gif", type: "image/gif" }, null],
    [{ name: "animated", type: "image/gif" }, null],
    [{ name: "photo.gif", type: "image/png" }, null],
    [{ name: "clip.avi", type: " VIDEO/X-MSVIDEO; codecs=unknown " }, "video"],
    [{ name: "voice.mp3", type: "audio/mpeg" }, null],
    [{ name: "photo.png.exe", type: "" }, null],
  ]) {
    assert.equal(classifySource(file), expected);
  }
});

test("source validation enforces per-type size limits and rejects invalid files before selection", () => {
  for (const [file, mode, expected] of [
    [{ name: "photo.png", type: "image/png", size: 20 * 1024 * 1024 }, "video", ""],
    [{ name: "photo.png", type: "image/png", size: 20 * 1024 * 1024 + 1 }, "video", "size"],
    [{ name: "clip.mov", type: "video/quicktime", size: 500 * 1024 * 1024 }, "video", ""],
    [{ name: "clip.mov", type: "video/quicktime", size: 500 * 1024 * 1024 + 1 }, "video", "size"],
    [{ name: "clip.mp4", type: "image/png", size: 10 }, "video", "mime"],
    [{ name: "photo.png", type: "image/gif", size: 10 }, "video", "mime"],
    [{ name: "photo.gif", type: "image/gif", size: 10 }, "video", "type"],
    [{ name: "clip.mp4", type: "video/mp4", size: 10 }, "image", "mode"],
    [{ name: "empty.png", type: "image/png", size: 0 }, "image", "empty"],
    [{ name: "still", type: "image/png", size: 10 }, "video", ""],
    [{ name: "clip", type: "video/mp4", size: 10 }, "video", ""],
  ]) {
    assert.equal(sourceFileError(file, mode), expected, file.name);
  }
  const valid = { name: "valid.mkv", type: "video/x-matroska", size: 10 };
  assert.deepEqual(selectSourceFiles([], [
    { name: "too-large.jpg", size: 20 * 1024 * 1024 + 1 },
    { name: "misnamed.mp4", type: "image/png", size: 10 },
    valid,
  ], "video"), [valid]);
});

test("supported media accepts only backend generic or matching MIME allowlists", () => {
  for (const type of ["", "application/octet-stream", "binary/octet-stream"]) {
    assert.equal(sourceFileError({ name: "still.jpg", type, size: 1 }, "video"), "");
    assert.equal(sourceFileError({ name: "clip.mkv", type, size: 1 }, "video"), "");
    assert.equal(narrationFileError({ name: "voice.mp3", type, size: 1 }), "");
  }
  for (const type of [
    "audio/aac", "audio/flac", "audio/m4a", "audio/mp4", "audio/mpeg", "audio/ogg",
    "audio/wav", "audio/wave", "audio/x-flac", "audio/x-m4a", "audio/x-wav",
  ]) {
    assert.equal(narrationFileError({ name: "voice.wav", type, size: 1 }), "");
  }
  for (const type of ["video/mp4", "image/png", "audio/opus", "application/pdf"]) {
    assert.equal(narrationFileError({ name: "voice.mp3", type, size: 1 }), "mime");
  }
});

test("downloads use the output format and a safe source stem", () => {
  assert.equal(posterDownloadFilename("photo.png", "video"), "photo_poster.mp4");
  assert.equal(posterDownloadFilename("clip.MOV", "video"), "clip_poster.mp4");
  assert.equal(posterDownloadFilename("photo.png", "image"), "photo_poster.jpg");
  assert.equal(posterDownloadFilename("folder/../my clip.mov", "video"), "my_clip_poster.mp4");
  assert.equal(posterDownloadFilename("C:\\folder\\my:clip?.png", "image"), "my_clip_poster.jpg");
  assert.equal(posterDownloadFilename("", "video"), "asset_poster.mp4");
});

test("cancelled and other terminal task statuses stop polling while active statuses do not", () => {
  for (const status of ["cancelled", "completed", "partial_failed", "failed"]) {
    assert.equal(isTerminalPosterStatus(status), true, status);
  }
  for (const status of ["pending", "running", "idle", undefined]) {
    assert.equal(isTerminalPosterStatus(status), false, status);
  }
});

test("video output accepts mixed sources, deduplicates, and caps the whole batch at 50", () => {
  const current = Array.from({ length: 48 }, (_, i) => ({
    name: `${i}.mp4`, size: 10, lastModified: 1,
  }));
  const image = { name: "new.png", size: 20, lastModified: 2 };
  const video = { name: "new.mov", size: 30, lastModified: 3 };
  assert.deepEqual(
    selectSourceFiles(current, [current[0], image, image, video, { name: "extra.jpg" }], "video"),
    [image, video]
  );
  assert.deepEqual(selectSourceFiles([], [video, image], "image"), [image]);
  assert.deepEqual(selectSourceFiles([...current, image, video], [{ name: "extra.jpg" }], "video"), []);
});

test("narration accepts only the supported audio extensions up to 50 MB", () => {
  for (const extension of ["mp3", "wav", "aac", "m4a", "ogg", "flac"]) {
    assert.equal(narrationFileError({ name: `voice.${extension.toUpperCase()}`, size: 50 * 1024 * 1024 }), "");
  }
  assert.equal(narrationFileError({ name: "voice.mp3", size: 50 * 1024 * 1024 + 1 }), "size");
  assert.equal(narrationFileError({ name: "voice.mp3", size: 0 }), "empty");
  assert.equal(narrationFileError({ name: "voice.opus", type: "audio/opus", size: 1 }), "type");
  assert.equal(narrationFileError({ name: "voice.mp3.exe", type: "audio/mpeg", size: 1 }), "type");
});

test("images prefer narration duration, otherwise BGM, and require audio", () => {
  const source = { sourceType: "image" };
  assert.deepEqual(estimatePosterAsset(source, { narration: { duration: 12 }, bgm: { duration: 30 } }), {
    targetDuration: 12, videoSpeed: null, narrationSpeed: 1, requiresAudio: false,
  });
  assert.deepEqual(estimatePosterAsset(source, { bgm: { duration: 30 } }), {
    targetDuration: 30, videoSpeed: null, narrationSpeed: null, requiresAudio: false,
  });
  assert.equal(estimatePosterAsset(source).requiresAudio, true);
});

test("video with narration accelerates only the longer side without a 1.5x cap", () => {
  assert.deepEqual(estimatePosterAsset({ sourceType: "video", duration: 30 }, { narration: { duration: 10 } }), {
    targetDuration: 10, videoSpeed: 3, narrationSpeed: 1, requiresAudio: false,
  });
  assert.deepEqual(estimatePosterAsset({ sourceType: "video", duration: 8 }, { narration: { duration: 20 } }), {
    targetDuration: 8, videoSpeed: 1, narrationSpeed: 2.5, requiresAudio: false,
  });
  assert.deepEqual(estimatePosterAsset({ sourceType: "video", duration: 10 }, { narration: { duration: 10 } }), {
    targetDuration: 10, videoSpeed: 1, narrationSpeed: 1, requiresAudio: false,
  });
});

test("video without narration retains source duration regardless of BGM", () => {
  for (const bgm of [null, { duration: 2 }, { duration: 100 }]) {
    assert.deepEqual(estimatePosterAsset({ sourceType: "video", duration: 24 }, { bgm }), {
      targetDuration: 24, videoSpeed: 1, narrationSpeed: null, requiresAudio: false,
    });
  }
});

test("missing or unusable browser metadata stays pending without invalidating supported files", () => {
  for (const duration of [undefined, null, 0, -1, NaN, Infinity]) {
    const image = estimatePosterAsset(
      { sourceType: "image" },
      { narration: { duration }, bgm: { duration: 30 } }
    );
    assert.equal(image.targetDuration, null);
    assert.equal(image.requiresAudio, false);
    const video = estimatePosterAsset({ sourceType: "video", duration }, { narration: { duration: 10 } });
    assert.equal(video.targetDuration, null);
    assert.equal(video.videoSpeed, null);
    assert.equal(video.narrationSpeed, null);
    assert.equal(video.requiresAudio, false);
  }
});
