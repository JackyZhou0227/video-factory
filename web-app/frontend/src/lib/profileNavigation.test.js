import assert from "node:assert/strict";
import test from "node:test";
import { isProfilePage, profilePageFromPathname } from "./profileNavigation.js";

test("maps personal center paths to their subpages", () => {
  assert.equal(profilePageFromPathname("/profile"), "profile");
  assert.equal(profilePageFromPathname("/profile/bgm/"), "profile-bgm");
  assert.equal(profilePageFromPathname("/profile/voices"), "profile-voices");
  assert.equal(profilePageFromPathname("/unknown"), null);
  assert.equal(isProfilePage("profile-bgm"), true);
  assert.equal(isProfilePage("settings"), false);
});
