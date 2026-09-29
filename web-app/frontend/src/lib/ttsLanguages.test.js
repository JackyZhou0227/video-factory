import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_TTS_LANGUAGES } from "./ttsLanguages.js";

test("provides the default language options for voice profiles", () => {
  assert.ok(DEFAULT_TTS_LANGUAGES.length > 0);
  assert.deepEqual(DEFAULT_TTS_LANGUAGES[0], { id: "Chinese", label: "中文" });
});
