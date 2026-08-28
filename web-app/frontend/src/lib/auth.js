import { apiJson } from "./backend";

// 认证类错误由调用方就地展示（登录表单、页面横幅等），不走全局 Snackbar
export async function getCurrentUser() {
  return apiJson("/api/auth/me", { silentError: true });
}

export async function login(username, password) {
  return apiJson(
    "/api/auth/login",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      silentError: true,
    }
  );
}

export async function register(username, password, displayName) {
  const payload = { username, password };
  if (displayName.trim()) payload.display_name = displayName.trim();

  return apiJson(
    "/api/auth/register",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      silentError: true,
    }
  );
}

export async function logout() {
  return apiJson("/api/auth/logout", { method: "POST" });
}

export async function changePassword(currentPassword, newPassword) {
  return apiJson(
    "/api/auth/password",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }
  );
}

export async function updateProfile(displayName) {
  return apiJson(
    "/api/auth/profile",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName }),
    }
  );
}

export async function listUsers({ name = "", username = "", page = 1, pageSize = 20 } = {}) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (name.trim()) params.set("name", name.trim());
  if (username.trim()) params.set("username", username.trim());
  return apiJson(`/api/admin/users?${params.toString()}`);
}

export async function resetUserPassword(userId, password) {
  return apiJson(
    `/api/admin/users/${userId}/password`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    }
  );
}

export async function updateUserRole(userId, role) {
  return apiJson(
    `/api/admin/users/${userId}/role`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    }
  );
}
