import { apiFetch } from "./backend";

async function readApiError(response, fallback) {
  const data = await response.json().catch(() => ({}));
  return data.detail || fallback || `HTTP ${response.status}`;
}

export async function getCurrentUser() {
  const response = await apiFetch("/api/auth/me");
  if (!response.ok) throw new Error(await readApiError(response, "读取登录状态失败"));
  return response.json();
}

export async function login(username, password) {
  const response = await apiFetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new Error(await readApiError(response, "登录失败"));
  return response.json();
}

export async function register(username, password, displayName) {
  const payload = { username, password };
  if (displayName.trim()) payload.display_name = displayName.trim();

  const response = await apiFetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await readApiError(response, "注册失败"));
  return response.json();
}

export async function logout() {
  const response = await apiFetch("/api/auth/logout", { method: "POST" });
  if (!response.ok) throw new Error(await readApiError(response, "退出登录失败"));
  return response.json();
}

