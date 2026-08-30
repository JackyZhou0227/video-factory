import { useCallback, useEffect, useMemo, useState } from "react";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import EChart, { barOption, dailySeriesOption, pieOption } from "./EChart";
import StatsTimeRange from "./StatsTimeRange";
import { listOrganizations } from "../lib/auth";
import { getOverviewStats } from "../lib/stats";

function defaultRange() {
  const to = new Date();
  const from = new Date(Date.now() - 29 * 86400000);
  const fmt = (date) => {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  };
  return { from: fmt(from), to: fmt(to) };
}

const CARD_STYLES = {
  display: "grid",
  gap: 12,
  padding: "14px 18px",
  borderRadius: "12px",
  backgroundColor: "var(--surface-muted, #f4f1ea)",
};

function MetricCard({ label, value }) {
  return (
    <Paper elevation={0} sx={CARD_STYLES}>
      <span style={{ fontSize: 12, color: "var(--text-muted, #6e6d68)" }}>{label}</span>
      <strong style={{ fontSize: 24, lineHeight: 1.2 }}>{value}</strong>
    </Paper>
  );
}

function formatRate(rate) {
  if (rate === null || rate === undefined) return "-";
  return `${Math.round(rate * 1000) / 10}%`;
}

export default function DataDashboard({ currentUser }) {
  const isAdmin = Boolean(currentUser?.is_admin);
  const [range, setRange] = useState(defaultRange);
  const ORG_ALL = "all";
  const [orgId, setOrgId] = useState(ORG_ALL);
  const [orgs, setOrgs] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isAdmin) return;
    listOrganizations()
      .then((res) => setOrgs(Array.isArray(res.organizations) ? res.organizations : []))
      .catch(() => setOrgs([]));
  }, [isAdmin]);

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getOverviewStats(range.from, range.to, orgId === ORG_ALL ? null : orgId);
      setData(res);
    } catch {
      // 错误已由全局提示展示
    } finally {
      setLoading(false);
    }
  }, [orgId, range.from, range.to]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  const totals = data?.totals;
  const dailyOption = useMemo(() => (data ? dailySeriesOption(data.daily, [
    { name: "任务数", key: "tasks", type: "bar" },
    { name: "产物数", key: "outputs", type: "line" },
  ]) : null), [data]);
  const typeOption = useMemo(() => (data ? pieOption(data.by_type) : null), [data]);
  const orgOption = useMemo(() => (data ? barOption(data.by_org, {
    nameKey: "org",
    series: [{ name: "任务数", key: "tasks" }, { name: "产物数", key: "outputs" }],
  }) : null), [data]);
  const memberOption = useMemo(() => (data ? barOption(data.top_members, {
    nameKey: "display_name",
    series: [{ name: "任务数", key: "tasks" }, { name: "产物数", key: "outputs" }],
  }) : null), [data]);

  return (
    <section className="workspace-panel admin-panel" aria-label="数据看板工作区">
      <div className="admin-content">
        <div className="task-filter-grid admin-filter-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
          <StatsTimeRange from={range.from} to={range.to} onChange={setRange} />
          {isAdmin && (
            <div className="field">
              <span className="field-label">组织</span>
              <TextField fullWidth size="small" select value={orgId} onChange={(event) => setOrgId(event.target.value)}>
                <MenuItem value={ORG_ALL}>全部组织</MenuItem>
                {orgs.map((org) => (
                  <MenuItem key={org.id} value={org.id}>{org.name}</MenuItem>
                ))}
              </TextField>
            </div>
          )}
        </div>

        {loading && <div className="form-alert completed">正在读取统计数据...</div>}

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
          <MetricCard label="任务数" value={totals?.task_count ?? "-"} />
          <MetricCard label="产物数" value={totals?.output_count ?? "-"} />
          <MetricCard label="失败产物数" value={totals?.failed_count ?? "-"} />
          <MetricCard label="成功率" value={formatRate(totals?.success_rate)} />
        </div>

        <Paper elevation={0} sx={{ mt: 2, p: 2, borderRadius: "12px" }}>
          <h3 style={{ margin: "4px 4px 8px", fontSize: 15 }}>任务量趋势</h3>
          {dailyOption && <EChart option={dailyOption} height={280} />}
          {!dailyOption && !loading && <div className="audio-empty">暂无数据</div>}
        </Paper>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12, marginTop: 12 }}>
          <Paper elevation={0} sx={{ p: 2, borderRadius: "12px" }}>
            <h3 style={{ margin: "4px 4px 8px", fontSize: 15 }}>模块占比（按任务数）</h3>
            {typeOption && data.by_type.length > 0 && <EChart option={typeOption} height={280} />}
            {(!typeOption || data.by_type.length === 0) && <div className="audio-empty">暂无数据</div>}
          </Paper>
          <Paper elevation={0} sx={{ p: 2, borderRadius: "12px" }}>
            <h3 style={{ margin: "4px 4px 8px", fontSize: 15 }}>组织对比</h3>
            {orgOption && data.by_org.length > 0 && <EChart option={orgOption} height={280} />}
            {(!orgOption || data.by_org.length === 0) && <div className="audio-empty">暂无数据</div>}
          </Paper>
        </div>

        <Paper elevation={0} sx={{ mt: 2, p: 2, borderRadius: "12px" }}>
          <h3 style={{ margin: "4px 4px 8px", fontSize: 15 }}>成员 Top 10（按任务数）</h3>
          {memberOption && data.top_members.length > 0 && <EChart option={memberOption} height={320} />}
          {(!memberOption || data.top_members.length === 0) && <div className="audio-empty">暂无数据</div>}
        </Paper>
      </div>
    </section>
  );
}
