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

export function getDefaultBackendBaseUrl() {
  if (!isBrowser()) return "";

  const { hostname, port, protocol } = window.location;
  const isLocalFrontend =
    port === "5173" &&
    (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1" || hostname === "[::1]");

  return isLocalFrontend ? `${protocol}//127.0.0.1:8001` : "";
}

export function getBackendBaseUrl() {
  if (!isBrowser()) return "";
  return (
    normalizeBackendBaseUrl(window.localStorage.getItem(BACKEND_BASE_URL_STORAGE_KEY)) ||
    getDefaultBackendBaseUrl()
  );
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

export function buildApiUrl(path, baseUrl = getBackendBaseUrl()) {
  const normalizedBaseUrl = normalizeBackendBaseUrl(baseUrl);
  return buildBackendUrl(path, normalizedBaseUrl);
}

export async function apiFetch(path, options, baseUrl = getBackendBaseUrl()) {
  let requestUrl = "";

  try {
    requestUrl = buildApiUrl(path, baseUrl);
    return await fetch(requestUrl, options);
  } catch (err) {
    if (err?.name === "AbortError" || !requestUrl) throw err;

    throw new Error(
      `无法连接后端服务：${requestUrl}。请确认设置里的后端地址能从当前浏览器访问，且后端服务已启动。`
    );
  }
}

export function getBackendDisplayUrl(baseUrl = getBackendBaseUrl()) {
  if (baseUrl) return baseUrl;
  return "当前页面同源地址";
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
