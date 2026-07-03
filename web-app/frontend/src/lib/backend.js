import { useEffect, useState } from "react";

export const BACKEND_BASE_URL_STORAGE_KEY = "videoFactory.backendBaseUrl";
export const BACKEND_BASE_URL_EVENT = "video-factory-backend-base-url-change";

function isBrowser() {
  return typeof window !== "undefined";
}

function isAbsoluteUrl(value) {
  return /^[a-z][a-z\d+\-.]*:\/\//i.test(value) || value.startsWith("//");
}

export function normalizeBackendBaseUrl(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";

  const withProtocol = isAbsoluteUrl(trimmed) ? trimmed : `http://${trimmed}`;

  try {
    const parsed = new URL(withProtocol, isBrowser() ? window.location.href : undefined);
    let path = parsed.pathname.replace(/\/+$/, "");
    if (path === "/api") path = "";
    if (path.endsWith("/api")) path = path.slice(0, -4);
    return `${parsed.origin}${path}`;
  } catch {
    return trimmed.replace(/\/+$/, "");
  }
}

export function getBackendBaseUrl() {
  if (!isBrowser()) return "";
  return normalizeBackendBaseUrl(window.localStorage.getItem(BACKEND_BASE_URL_STORAGE_KEY));
}

export function saveBackendBaseUrl(value) {
  const normalized = normalizeBackendBaseUrl(value);
  if (!isBrowser()) return normalized;

  if (normalized) {
    window.localStorage.setItem(BACKEND_BASE_URL_STORAGE_KEY, normalized);
  } else {
    window.localStorage.removeItem(BACKEND_BASE_URL_STORAGE_KEY);
  }

  window.dispatchEvent(
    new CustomEvent(BACKEND_BASE_URL_EVENT, {
      detail: { baseUrl: normalized },
    })
  );

  return normalized;
}

export function buildBackendUrl(path, baseUrl = getBackendBaseUrl()) {
  if (!path) return baseUrl || "";
  if (isAbsoluteUrl(path) || path.startsWith("blob:") || path.startsWith("data:")) return path;

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return baseUrl ? `${baseUrl}${normalizedPath}` : normalizedPath;
}

export function resolveBackendAssetUrl(path, baseUrl = getBackendBaseUrl()) {
  if (!path) return "";
  return buildBackendUrl(path, baseUrl);
}

export function apiFetch(path, options) {
  return fetch(buildBackendUrl(path), options);
}

export function getBackendDisplayUrl(baseUrl = getBackendBaseUrl()) {
  if (baseUrl) return baseUrl;
  return "当前前端同源地址";
}

export function useBackendBaseUrl() {
  const [baseUrl, setBaseUrl] = useState(() => getBackendBaseUrl());

  useEffect(() => {
    const sync = () => setBaseUrl(getBackendBaseUrl());

    window.addEventListener(BACKEND_BASE_URL_EVENT, sync);
    window.addEventListener("storage", sync);

    return () => {
      window.removeEventListener(BACKEND_BASE_URL_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return baseUrl;
}
