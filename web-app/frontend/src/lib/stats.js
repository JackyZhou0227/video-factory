import { apiJson } from "./backend";

export async function getMyStats(from, to) {
  const params = new URLSearchParams();
  if (from) params.set("created_from", from);
  if (to) params.set("created_to", to);
  const query = params.toString();
  return apiJson(`/api/stats/me${query ? `?${query}` : ""}`);
}

export async function getOverviewStats(from, to, orgId) {
  const params = new URLSearchParams();
  if (from) params.set("created_from", from);
  if (to) params.set("created_to", to);
  if (orgId) params.set("org_id", orgId);
  const query = params.toString();
  return apiJson(`/api/stats/overview${query ? `?${query}` : ""}`);
}
