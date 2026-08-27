import { apiFetch } from "./backend";

async function readApiError(response, fallback) {
  const data = await response.json().catch(() => ({}));
  const message = data.detail || fallback || `HTTP ${response.status}`;
  const retryAfter = Number.parseInt(response.headers.get("Retry-After") || "", 10);
  if (response.status === 429 && Number.isFinite(retryAfter) && retryAfter > 0) {
    return `${message}（约 ${retryAfter} 秒后可重试）`;
  }
  return message;
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

export async function changePassword(currentPassword, newPassword) {
  const response = await apiFetch("/api/auth/password", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!response.ok) throw new Error(await readApiError(response, "修改密码失败"));
  return response.json();
}

export async function listUsers() {
  const response = await apiFetch("/api/admin/users");
  if (!response.ok) throw new Error(await readApiError(response, "读取用户列表失败"));
  return response.json();
}

export async function resetUserPassword(userId, password) {
  const response = await apiFetch(`/api/admin/users/${userId}/password`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) throw new Error(await readApiError(response, "重置密码失败"));
  return response.json();
}

export async function updateUserRole(userId, role) {
  const response = await apiFetch(`/api/admin/users/${userId}/role`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!response.ok) throw new Error(await readApiError(response, "更新用户角色失败"));
  return response.json();
}
