import { useEffect, useState } from "react";

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
  return getDefaultBackendBaseUrl();
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
    return await fetch(requestUrl, {
      credentials: "include",
      ...(options || {}),
    });
  } catch (err) {
    if (err?.name === "AbortError" || !requestUrl) throw err;

    throw new Error(
      `无法连接后端服务：${requestUrl}。请确认后端服务已启动，并从后端服务打开页面。`
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

    window.addEventListener("focus", sync);

    return () => {
      window.removeEventListener("focus", sync);
    };
  }, []);

  return baseUrl;
}
