import { useCallback, useEffect, useMemo, useState } from "react";
import Paper from "@mui/material/Paper";
import EChart, { dailySeriesOption, pieOption } from "./EChart";
import StatsTimeRange from "./StatsTimeRange";
import { getMyStats } from "../lib/stats";

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

export default function PersonalStats({ active }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState(defaultRange);

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getMyStats(range.from, range.to));
    } catch {
      // 错误已由全局提示展示
    } finally {
      setLoading(false);
    }
  }, [range.from, range.to]);

  useEffect(() => {
    if (active) loadStats();
  }, [active, loadStats]);

  const totals = data?.totals;
  const dailyOption = useMemo(() => (data ? dailySeriesOption(data.daily, [
    { name: "任务数", key: "tasks", type: "bar" },
    { name: "产物数", key: "outputs", type: "line" },
  ]) : null), [data]);
  const typeOption = useMemo(() => (data ? pieOption(data.by_type) : null), [data]);

  if (!active) return null;

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="task-list-toolbar" style={{ justifyContent: "flex-end" }}>
        <StatsTimeRange from={range.from} to={range.to} onChange={setRange} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
        <MetricCard label="任务数" value={totals?.task_count ?? "-"} />
        <MetricCard label="产物数" value={totals?.output_count ?? "-"} />
        <MetricCard label="失败产物数" value={totals?.failed_count ?? "-"} />
        <MetricCard label="成功率" value={formatRate(totals?.success_rate)} />
      </div>

      {loading && <div className="form-alert completed">正在读取个人统计...</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
        <Paper elevation={0} sx={{ p: 2, borderRadius: "12px" }}>
          <h3 style={{ margin: "4px 4px 8px", fontSize: 15 }}>我的任务趋势</h3>
          {dailyOption && data.daily.length > 0 && <EChart option={dailyOption} height={240} />}
          {(!dailyOption || data.daily.length === 0) && <div className="audio-empty">近30天暂无任务</div>}
        </Paper>
        <Paper elevation={0} sx={{ p: 2, borderRadius: "12px" }}>
          <h3 style={{ margin: "4px 4px 8px", fontSize: 15 }}>模块占比（按任务数）</h3>
          {typeOption && data.by_type.length > 0 && <EChart option={typeOption} height={240} />}
          {(!typeOption || data.by_type.length === 0) && <div className="audio-empty">暂无任务</div>}
        </Paper>
      </div>
    </div>
  );
}
