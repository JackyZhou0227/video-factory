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

export async function register(username, password, displayName, orgId) {
  const payload = { username, password };
  if (displayName.trim()) payload.display_name = displayName.trim();
  if (orgId) payload.org_id = orgId;

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

export async function listPublicOrganizations() {
  return apiJson("/api/auth/organizations", { silentError: true });
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

export async function listUsers({ name = "", username = "", page = 1, pageSize = 20, status = "" } = {}) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (name.trim()) params.set("name", name.trim());
  if (username.trim()) params.set("username", username.trim());
  if (status) params.set("status_filter", status);
  return apiJson(`/api/admin/users?${params.toString()}`);
}

export async function createMember({ username, password, displayName }) {
  const payload = { username, password };
  if (displayName?.trim()) payload.display_name = displayName.trim();
  return apiJson(
    "/api/admin/users",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function updateUserStatus(userId, status) {
  return apiJson(
    `/api/admin/users/${userId}/status`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }
  );
}

export async function rejectPendingUser(userId) {
  return apiJson(`/api/admin/users/${userId}/pending`, { method: "DELETE" });
}

export async function updateUserOrg(userId, orgId) {
  return apiJson(
    `/api/admin/users/${userId}/org`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org_id: orgId }),
    }
  );
}

// --- 组织管理（仅超管） ---

export async function listOrganizations() {
  return apiJson("/api/admin/organizations");
}

export async function createOrganization(name) {
  return apiJson(
    "/api/admin/organizations",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }
  );
}

export async function renameOrganization(orgId, name) {
  return apiJson(
    `/api/admin/organizations/${orgId}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }
  );
}

export async function deleteOrganization(orgId) {
  return apiJson(`/api/admin/organizations/${orgId}`, { method: "DELETE" });
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
