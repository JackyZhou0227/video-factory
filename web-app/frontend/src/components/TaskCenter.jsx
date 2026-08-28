import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./Icon";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import { apiFetch, useBackendBaseUrl } from "../lib/backend";

const TASK_LABELS = {
  digital_human: "数字人",
  voice_generation: "语音生成",
  template_production: "模板量产",
  smart_editing: "智能剪辑",
  poster_video: "大字报",
};

const GENERATION_LABELS = {
  voice: "语音",
  audio: "音频",
  image: "图片",
  video: "视频",
  archive: "压缩包",
};

const STATUS_LABELS = {
  pending: "等待中",
  running: "运行中",
  submitted: "已提交",
  completed: "已完成",
  partial_failed: "部分失败",
  failed: "失败",
  cancelled: "已取消",
};

const FINAL_STATUSES = new Set(["submitted", "completed", "partial_failed", "failed", "cancelled"]);

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatSize(value) {
  const size = Number(value || 0);
  if (!size) return "—";
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

async function readApiError(response) {
  const payload = await response.json().catch(() => ({}));
  return payload.detail || `HTTP ${response.status}`;
}

function taskSummary(task) {
  return `${TASK_LABELS[task.task_type] || task.task_type} · ${GENERATION_LABELS[task.generation_type] || task.generation_type}`;
}

function statusIcon(status) {
  if (["failed", "partial_failed"].includes(status)) return "alert";
  if (["completed", "submitted"].includes(status)) return "check";
  if (status === "cancelled") return "x";
  return "loading";
}

function ArtifactCard({ artifact, backendBaseUrl }) {
  const isPreviewable = ["audio", "image", "video"].includes(artifact.kind);
  const isComplete = artifact.status === "completed";
  return (
    <article className={`task-artifact-card ${artifact.status || ""}`}>
      <div className="task-artifact-preview">
        {isPreviewable && isComplete ? (
          <ProtectedMedia
            path={artifact.preview_url}
            kind={artifact.kind}
            backendBaseUrl={backendBaseUrl}
            alt={artifact.name}
          />
        ) : (
          <div className="task-artifact-placeholder">
            <Icon name={artifact.kind === "archive" ? "download" : artifact.status === "failed" ? "alert" : "file"} size={22} />
            <span>{artifact.status === "missing" ? "文件已清理" : STATUS_LABELS[artifact.status] || artifact.status}</span>
          </div>
        )}
      </div>
      <div className="task-artifact-copy">
        <div className="task-artifact-title-row">
          <strong title={artifact.name}>{artifact.name}</strong>
          <span>{formatSize(artifact.size)}</span>
        </div>
        <small>{artifact.kind === "archive" ? "任务压缩包" : GENERATION_LABELS[artifact.kind] || artifact.kind}</small>
        {isComplete ? (
          <ProtectedDownloadButton
            path={artifact.download_url}
            filename={artifact.name}
            backendBaseUrl={backendBaseUrl}
            className="secondary-action compact-action"
          >
            <Icon name="download" size={14} />下载
          </ProtectedDownloadButton>
        ) : null}
      </div>
    </article>
  );
}

function TaskDetail({ task, backendBaseUrl, loading, onClose }) {
  if (loading) {
    return <section className="modal-panel task-detail-modal task-detail-loading"><Icon name="loading" size={18} />正在读取详情</section>;
  }
  if (!task) return null;

  const extra = task.extra_info || {};
  const taskDownload = task.download_url;
  const taskDownloadArtifact =
    task.artifacts?.find((artifact) => artifact.kind === "archive" && artifact.status === "completed") ||
    (task.artifacts?.length === 1 && task.artifacts[0].status === "completed" ? task.artifacts[0] : null);
  return (
    <section className="modal-panel task-detail-modal" role="dialog" aria-modal="true" aria-labelledby="task-detail-title">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Task Detail</span>
          <h2 id="task-detail-title">{taskSummary(task)}</h2>
          <p>{task.message || "暂无任务说明"}</p>
        </div>
        <span className={`status-pill ${task.status}`}>
          <Icon name={statusIcon(task.status)} size={14} />
          {STATUS_LABELS[task.status] || task.status}
        </span>
        <button className="icon-button" type="button" onClick={onClose} aria-label="关闭任务详情" title="关闭">
          <Icon name="x" size={17} />
        </button>
      </div>

      <div className="task-progress-block">
        <div className="task-progress-meta"><span>处理进度</span><strong>{task.progress || 0}%</strong></div>
        <div className="task-progress-track"><span style={{ width: `${Math.max(0, Math.min(100, task.progress || 0))}%` }} /></div>
      </div>

      <div className="task-meta-grid">
        <div><span>生成数量</span><strong>{task.requested_count}</strong></div>
        <div><span>成功</span><strong>{task.success_count}</strong></div>
        <div><span>失败</span><strong>{task.failed_count}</strong></div>
        <div><span>创建人</span><strong>{task.creator_display_name || task.creator_username}</strong></div>
        <div><span>创建时间</span><strong>{formatTime(task.created_at)}</strong></div>
        <div><span>完成时间</span><strong>{formatTime(task.finished_at)}</strong></div>
      </div>

      {task.error ? <div className="form-alert failed">{task.error}</div> : null}

      {extra.runninghub_task_id ? (
        <div className="task-runninghub-card">
          <div><span>RunningHub 任务 ID</span><strong>{extra.runninghub_task_id}</strong></div>
          <div className="task-runninghub-actions">
            <a className="secondary-link-action" href={extra.runninghub_task_url} target="_blank" rel="noreferrer">
              <Icon name="external" size={14} />任务进度
            </a>
            <a className="secondary-link-action" href={extra.runninghub_works_url} target="_blank" rel="noreferrer">
              <Icon name="external" size={14} />我的作品
            </a>
          </div>
        </div>
      ) : null}

      <div className="task-artifacts-heading">
        <div><span className="section-kicker">Artifacts</span><h3>产物</h3></div>
        {taskDownload ? (
          <ProtectedDownloadButton
            path={taskDownload}
            filename={taskDownloadArtifact?.name || `${task.id}.zip`}
            backendBaseUrl={backendBaseUrl}
            className="secondary-action compact-action"
          >
            <Icon name="download" size={14} />下载任务文件
          </ProtectedDownloadButton>
        ) : null}
      </div>
      {task.artifacts?.length ? (
        <div className="task-artifact-grid">
          {task.artifacts.map((artifact) => <ArtifactCard key={artifact.id} artifact={artifact} backendBaseUrl={backendBaseUrl} />)}
        </div>
      ) : (
        <div className="task-no-artifacts">当前任务没有本地文件产物。</div>
      )}
    </section>
  );
}

export default function TaskCenter({ active = true }) {
  const backendBaseUrl = useBackendBaseUrl();
  const [filters, setFilters] = useState({ task_type: "", generation_type: "", status: "", created_from: "", created_to: "" });
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [selectedTask, setSelectedTask] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const loadTasks = useCallback(async (targetPage = 1, silent = false) => {
    if (!silent) setLoading(true);
    setError("");
    const params = new URLSearchParams({ page: String(targetPage), page_size: "12" });
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
    try {
      const response = await apiFetch(`/api/tasks?${params.toString()}`, undefined, backendBaseUrl);
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = await response.json();
      setItems(Array.isArray(payload.items) ? payload.items : []);
      setPage(payload.page || targetPage);
      setPages(Math.max(1, payload.pages || 1));
      setTotal(payload.total || 0);
    } catch (loadError) {
      if (!silent) setError(loadError.message || "读取任务列表失败");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [backendBaseUrl, filters]);

  const loadDetail = useCallback(async (taskId, silent = false) => {
    if (!taskId) return;
    setSelectedId(taskId);
    if (!silent) setDetailLoading(true);
    setError("");
    try {
      const response = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}`, undefined, backendBaseUrl);
      if (!response.ok) throw new Error(await readApiError(response));
      setSelectedTask(await response.json());
    } catch (detailError) {
      setError(detailError.message || "读取任务详情失败");
    } finally {
      if (!silent) setDetailLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    if (active) loadTasks(1);
  }, [active, loadTasks]);

  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => {
      loadTasks(page, true);
      if (selectedId) loadDetail(selectedId, true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [active, loadDetail, loadTasks, page, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    const current = items.find((item) => item.id === selectedId);
    if (current && !selectedTask) loadDetail(selectedId);
  }, [items, loadDetail, selectedId, selectedTask]);

  const updateFilter = (event) => {
    const { name, value } = event.target;
    setFilters((current) => ({ ...current, [name]: value }));
  };

  const resetFilters = () => {
    setFilters({ task_type: "", generation_type: "", status: "", created_from: "", created_to: "" });
    setSelectedId("");
    setSelectedTask(null);
  };

  const closeDetail = useCallback(() => {
    setSelectedId("");
    setSelectedTask(null);
    setDetailLoading(false);
  }, []);

  const activeCount = useMemo(() => items.filter((item) => !FINAL_STATUSES.has(item.status)).length, [items]);

  return (
    <div className="task-center-layout">
      <section className="workspace-panel task-center-list-panel" aria-label="任务中心工作区">
        <div className="task-filter-grid">
          <label className="field"><span className="field-label">任务类型</span><select className="control" name="task_type" value={filters.task_type} onChange={updateFilter}><option value="">全部</option><option value="digital_human">数字人</option><option value="voice_generation">语音生成</option><option value="poster_video">大字报</option><option value="template_production">模板量产</option><option value="smart_editing">智能剪辑</option></select></label>
          <label className="field"><span className="field-label">生成类型</span><select className="control" name="generation_type" value={filters.generation_type} onChange={updateFilter}><option value="">全部</option><option value="voice">语音</option><option value="image">图片</option><option value="video">视频</option></select></label>
          <label className="field"><span className="field-label">状态</span><select className="control" name="status" value={filters.status} onChange={updateFilter}><option value="">全部</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="field"><span className="field-label">开始日期</span><input className="control" type="date" name="created_from" value={filters.created_from} onChange={updateFilter} /></label>
          <label className="field"><span className="field-label">结束日期</span><input className="control" type="date" name="created_to" value={filters.created_to} onChange={updateFilter} /></label>
          <div className="task-filter-actions"><button className="secondary-action compact-action" type="button" onClick={resetFilters}>重置</button></div>
        </div>

        <div className="task-list-toolbar"><span>共 {total} 条任务</span>{activeCount ? <span className="task-live-note"><Icon name="loading" size={13} />{activeCount} 条处理中</span> : null}</div>
        {error ? <div className="form-alert failed">{error}</div> : null}
        {loading ? <div className="task-list-state"><Icon name="loading" size={18} />正在加载任务</div> : items.length ? (
          <div className="task-list">
            <div className="task-list-header" aria-hidden="true">
              <span>任务</span>
              <span>创建时间</span>
              <span>创建人</span>
              <span>进度</span>
              <span>状态</span>
              <span>操作</span>
            </div>
            {items.map((task) => (
              <div className={`task-list-row ${selectedId === task.id ? "is-selected" : ""}`} key={task.id}>
                <span className="task-row-task"><span className={`task-row-icon ${task.task_type}`}><Icon name={task.generation_type === "voice" ? "audio" : task.task_type === "digital_human" ? "digitalHuman" : task.generation_type === "image" ? "image" : "video"} size={18} /></span><strong>{taskSummary(task)}</strong></span>
                <span className="task-row-time">{formatTime(task.created_at)}</span>
                <span className="task-row-creator">{task.creator_display_name || task.creator_username || "—"}</span>
                <span className="task-row-count">{task.success_count}/{task.requested_count}</span>
                <span className={`status-pill ${task.status}`}>{STATUS_LABELS[task.status] || task.status}</span>
                <button className="secondary-action compact-action task-detail-action" type="button" onClick={() => loadDetail(task.id)}>
                  <Icon name="file" size={14} />查看详情
                </button>
              </div>
            ))}
          </div>
        ) : <div className="task-list-state"><Icon name="history" size={22} /><strong>还没有任务记录</strong><span>完成一次语音、图片或视频生成后，任务会出现在这里。</span></div>}
        <div className="task-pagination"><button className="secondary-action compact-action" type="button" disabled={page <= 1 || loading} onClick={() => loadTasks(page - 1)}>上一页</button><span>第 {page} / {pages} 页</span><button className="secondary-action compact-action" type="button" disabled={page >= pages || loading} onClick={() => loadTasks(page + 1)}>下一页</button></div>
      </section>
      {selectedId ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDetail(); }}>
          <TaskDetail task={selectedTask} loading={detailLoading} backendBaseUrl={backendBaseUrl} onClose={closeDetail} />
        </div>
      ) : null}
    </div>
  );
}
