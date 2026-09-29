const PROFILE_PATHS = {
  profile: "profile",
  "profile/bgm": "profile-bgm",
  "profile/voices": "profile-voices",
};

export function profilePageFromPathname(pathname) {
  const path = pathname.replace(/^\/+|\/+$/g, "");
  return PROFILE_PATHS[path] || null;
}

export function isProfilePage(pageId) {
  return pageId === "profile" || pageId === "profile-bgm" || pageId === "profile-voices";
}
