import { useEffect, useState } from "react";
import Paper from "@mui/material/Paper";
import Icon from "./Icon";
import { apiJson, useBackendBaseUrl } from "../lib/backend";

export default function TaskCapacityHeaderCard() {
  const backendBaseUrl = useBackendBaseUrl();
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const payload = await apiJson("/api/tasks/summary", { silentError: true }, backendBaseUrl);
        if (!cancelled) setSummary(payload);
      } catch {
        // Keep the last successful snapshot during a transient refresh failure.
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [backendBaseUrl]);

  const limit = (value) => value == null ? "不限" : value;
  return (
    <Paper className="task-capacity-card" elevation={0} aria-label="任务容量">
      <span className="task-capacity-icon" aria-hidden="true"><Icon name="gauge" size={18} /></span>
      <div className="task-capacity-content">
        <div className="task-capacity-title"><strong>任务容量</strong><span>5 秒更新</span></div>
        <div className="task-capacity-line">
          <span>我的 {summary?.user ? `${summary.user.active}/${limit(summary.user.limit)}` : "—"}</span>
          <span>全局 {summary?.global ? `${summary.global.active}/${limit(summary.global.limit)}` : "—"}</span>
          <span>等待 {summary?.global?.pending ?? "—"}</span>
          <span>处理中 {summary?.global?.running ?? "—"}</span>
          <span>本地配音 {summary?.runtime ? `${summary.runtime.qwen.active}/${summary.runtime.qwen.limit}` : "—"}</span>
        </div>
      </div>
    </Paper>
  );
}
