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
  const backendHostname = hostname === "::1" ? "[::1]" : hostname;

  return isLocalFrontend ? `${protocol}//${backendHostname}:18888` : "";
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

function getCookieValue(name) {
  if (!isBrowser()) return "";
  const prefix = `${encodeURIComponent(name)}=`;
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : "";
}

function withCsrfHeader(options) {
  const requestOptions = { ...(options || {}) };
  const method = String(requestOptions.method || "GET").toUpperCase();
  if (!["POST", "PUT", "PATCH", "DELETE"].includes(method)) return requestOptions;

  const csrfToken = getCookieValue("vf_csrf");
  if (!csrfToken) return requestOptions;

  return {
    ...requestOptions,
    headers: {
      ...(requestOptions.headers || {}),
      "X-CSRF-Token": csrfToken,
    },
  };
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function extractDetailMessage(data, response) {
  const detail = data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((item) => {
        const loc = Array.isArray(item?.loc)
          ? item.loc.filter((part) => part !== "body").join(".")
          : "";
        return loc ? `${loc}: ${item?.msg ?? ""}` : String(item?.msg ?? "");
      })
      .filter(Boolean)
      .join("；");
  }
  if (typeof data?.message === "string" && data.message.trim()) return data.message;
  return `请求失败（HTTP ${response.status}）`;
}

let globalErrorHandler = null;

export function setGlobalErrorHandler(handler) {
  globalErrorHandler = typeof handler === "function" ? handler : null;
}

function notifyGlobalError(error) {
  if (globalErrorHandler) globalErrorHandler(error);
}

// 非静默模式下，非 2xx 响应会自动触发全局错误提示；需要就地展示错误的调用方
// 传入 { silentError: true }，拿到 ApiError 后自行处理
export async function apiJson(path, options, baseUrl = getBackendBaseUrl()) {
  const { silentError, ...fetchOptions } = options || {};
  const response = await apiFetch(path, fetchOptions, baseUrl);

  let data = null;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const error = new ApiError(extractDetailMessage(data, response), response.status);
    if (!silentError) notifyGlobalError(error);
    throw error;
  }

  return data;
}

export async function apiFetch(path, options, baseUrl = getBackendBaseUrl()) {
  let requestUrl = "";

  try {
    requestUrl = buildApiUrl(path, baseUrl);
    const requestOptions = withCsrfHeader(options);
    const isAuthRequest = String(path || "").startsWith("/api/auth/");
    return await fetch(requestUrl, {
      ...requestOptions,
      credentials: "include",
      cache: isAuthRequest ? "no-store" : requestOptions.cache,
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
