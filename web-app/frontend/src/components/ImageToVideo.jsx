import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";
import { apiFetch, useBackendBaseUrl } from "../lib/backend";

const RUNNINGHUB_TASKS_URL = "https://www.runninghub.cn/bill-task";
const RUNNINGHUB_WORKS_URL = "https://www.runninghub.cn/user-center";

const VIDEO_STEP_LABELS = {
  idle: "等待素材",
  ready: "可生成视频",
  pending: "任务排队中",
  running: "正在提交任务",
  submitted: "任务已提交",
  completed: "视频已生成",
  failed: "生成失败",
};

function formatFileSize(size) {
  if (!size) return "";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function pollTask(taskId, signal, backendBaseUrl) {
  return apiFetch(`/api/task/${taskId}`, { signal }, backendBaseUrl).then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  });
}

export default function ImageToVideo() {
  const backendBaseUrl = useBackendBaseUrl();
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [taskStatus, setTaskStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const [runningHubResult, setRunningHubResult] = useState(null);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);

  const imageInputRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
      if (imagePreview) URL.revokeObjectURL(imagePreview);
    };
  }, [imagePreview]);

  const resetTaskState = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    setTaskStatus("idle");
    setProgress(0);
    setStatusMsg("");
    setRunningHubResult(null);
    setError("");
    setGenerating(false);
  }, []);

  const handleImageChange = useCallback(
    (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const nextPreview = URL.createObjectURL(file);
      setImageFile(file);
      setImagePreview((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return nextPreview;
      });
      resetTaskState();
    },
    [resetTaskState]
  );

  const removeImage = useCallback(() => {
    setImageFile(null);
    setImagePreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (imageInputRef.current) imageInputRef.current.value = "";
    resetTaskState();
  }, [resetTaskState]);

  const canGenerateVideo = Boolean(imageFile && prompt.trim() && !generating && taskStatus !== "submitted");

  const pipelineItems = [
    {
      label: "首帧图",
      detail: imageFile ? imageFile.name : "等待上传图片",
      state: imageFile ? "completed" : "idle",
      icon: "image",
    },
    {
      label: "提示词",
      detail: prompt.trim() ? "运动和镜头描述已填写" : "等待填写 prompt",
      state: prompt.trim() ? "completed" : "idle",
      icon: "sparkles",
    },
    {
      label: "云端生成",
      detail:
        taskStatus === "submitted"
          ? "已提交 RunningHub"
          : taskStatus === "failed"
            ? "需要检查任务"
            : "RunningHub 队列",
      state: ["pending", "running"].includes(taskStatus) ? "running" : taskStatus,
      icon: "cloud",
    },
  ];

  const videoPanelStatus = useMemo(() => {
    if (taskStatus === "submitted") return "submitted";
    if (taskStatus === "pending" || taskStatus === "running") return taskStatus;
    if (taskStatus === "failed") return "failed";
    if (imageFile && prompt.trim()) return "ready";
    return "idle";
  }, [imageFile, prompt, taskStatus]);

  const videoPanelMessage = useMemo(() => {
    if (taskStatus === "failed") return error || "任务执行失败，请检查输入后重试。";
    if (taskStatus === "submitted") return statusMsg || "RunningHub 任务已提交成功，请到 RunningHub 查看进度和作品。";
    if (taskStatus === "running" || taskStatus === "pending") return statusMsg || "正在创建 RunningHub 图生视频任务。";
    if (imageFile && prompt.trim()) return "首帧图和提示词已就绪，可以提交图生视频任务。";
    if (imageFile) return "首帧图已就绪，请补充视频提示词。";
    if (prompt.trim()) return "提示词已就绪，请上传首帧参考图。";
    return "上传一张首帧图，并写清楚动作、镜头和画面变化。";
  }, [error, imageFile, prompt, statusMsg, taskStatus]);

  const handleGenerateVideo = useCallback(async () => {
    if (!canGenerateVideo) return;

    setGenerating(true);
    setError("");
    setRunningHubResult(null);
    setProgress(0);
    setTaskStatus("pending");
    setStatusMsg("正在提交图生视频任务...");

    try {
      const formData = new FormData();
      formData.append("image", imageFile);
      formData.append("prompt", prompt.trim());

      const response = await apiFetch(
        "/api/image-to-video/generate",
        {
          method: "POST",
          body: formData,
        },
        backendBaseUrl
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const { task_id: taskId } = await response.json();
      setTaskStatus("running");
      setStatusMsg("正在上传首帧图并创建 RunningHub 任务...");

      const controller = new AbortController();
      const poll = async () => {
        try {
          const data = await pollTask(taskId, controller.signal, backendBaseUrl);
          setProgress(data.progress ?? 0);
          setStatusMsg(data.message ?? "");

          if (data.status === "submitted") {
            setTaskStatus("submitted");
            setRunningHubResult({
              taskId: data.runninghub_task_id ?? null,
              taskUrl: data.runninghub_task_url || RUNNINGHUB_TASKS_URL,
              worksUrl: data.runninghub_works_url || RUNNINGHUB_WORKS_URL,
            });
            setStatusMsg(data.message || "RunningHub 图生视频任务已提交成功。");
            setProgress(100);
            setGenerating(false);
            return;
          }

          if (data.status === "failed") {
            setTaskStatus("failed");
            setError(data.error ?? data.message ?? "未知错误");
            setStatusMsg("生成失败");
            setGenerating(false);
            return;
          }

          pollRef.current = setTimeout(poll, 3000);
        } catch (err) {
          if (err.name === "AbortError") return;
          setTaskStatus("failed");
          setError(err.message);
          setGenerating(false);
        }
      };

      pollRef.current = setTimeout(poll, 1200);
    } catch (err) {
      setTaskStatus("failed");
      setError(err.message);
      setGenerating(false);
    }
  }, [backendBaseUrl, canGenerateVideo, imageFile, prompt]);

  return (
    <>
      <section className="workspace-panel production-panel" aria-labelledby="i2v-production-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">制作</span>
            <h2 id="i2v-production-title">图生视频</h2>
          </div>
          <span className="required-note">固定 LTX-2 RunningHub 工作流</span>
        </div>

        <div className="pipeline-strip" aria-label="图生视频流程状态">
          {pipelineItems.map((item, index) => (
            <div key={item.label} className={`pipeline-step ${item.state}`}>
              <span className="pipeline-index">
                <Icon name={item.state === "completed" ? "check" : item.icon} size={14} />
                <span>{String(index + 1).padStart(2, "0")}</span>
              </span>
              <span className="pipeline-copy">
                <strong>{item.label}</strong>
                <span>{item.detail}</span>
              </span>
            </div>
          ))}
        </div>

        <div className="i2v-grid">
          <div className="workflow-card media-workflow">
            <div className="control-section-heading">
              <span>01</span>
              <strong>首帧参考图</strong>
            </div>

            <label className={`upload-dropzone ${imageFile ? "is-filled" : ""}`}>
              {imagePreview ? (
                <span className="image-preview-frame">
                  <img className="preview-img" src={imagePreview} alt="首帧预览" />
                </span>
              ) : (
                <span className="upload-placeholder">
                  <Icon name="imageAdd" size={26} />
                  <strong>上传首帧图片</strong>
                  <small>JPG、PNG 或 WebP</small>
                </span>
              )}
              <input ref={imageInputRef} type="file" accept="image/*" onChange={handleImageChange} />
            </label>

            {imageFile && (
              <div className="file-row">
                <span>
                  {imageFile.name} · {formatFileSize(imageFile.size)}
                </span>
                <button type="button" className="text-button" onClick={removeImage}>
                  移除
                </button>
              </div>
            )}
          </div>

          <div className="workflow-card">
            <div className="control-section-heading">
              <span>02</span>
              <strong>视频提示词</strong>
            </div>

            <label className="field" htmlFor="i2v-prompt">
              <span className="field-label">画面运动、镜头和风格 *</span>
              <textarea
                id="i2v-prompt"
                className="control textarea script-textarea"
                rows={10}
                placeholder="例如：镜头缓慢推进，人物自然转头看向镜头，背景保持稳定，光线柔和，动作连贯，不要变形。"
                value={prompt}
                onChange={(event) => {
                  setPrompt(event.target.value);
                  setTaskStatus((current) => (current === "submitted" ? "idle" : current));
                  setRunningHubResult(null);
                  setError("");
                }}
              />
            </label>
          </div>
        </div>
      </section>

      <section className="workspace-panel output-panel" aria-labelledby="i2v-output-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">输出</span>
            <h2 id="i2v-output-title">提交图生视频任务</h2>
          </div>
          <span className={`status-pill ${videoPanelStatus}`}>
            <Icon
              name={
                videoPanelStatus === "failed"
                  ? "alert"
                  : videoPanelStatus === "submitted"
                    ? "check"
                    : ["running", "pending"].includes(videoPanelStatus)
                      ? "loading"
                      : "gauge"
              }
              size={14}
            />
            {VIDEO_STEP_LABELS[videoPanelStatus]}
          </span>
        </div>

        <div className="video-workflow">
          <div className="video-status-card">
            <span className="section-kicker with-icon">
              <Icon name="cloud" size={13} />
              RunningHub
            </span>
            <h3>创建云端生成任务</h3>
            <p>{videoPanelMessage}</p>

            <button className="primary-action" type="button" disabled={!canGenerateVideo} onClick={handleGenerateVideo}>
              <Icon name={generating ? "loading" : "wand"} size={16} />
              {taskStatus === "submitted" ? "任务已提交" : generating ? "正在提交任务" : "生成图生视频"}
            </button>

            {(taskStatus === "running" || taskStatus === "pending") && (
              <div className="progress-area" aria-label="生成进度">
                <div className="progress-meta">
                  <span>{videoPanelMessage}</span>
                  <strong>{progress}%</strong>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}
          </div>

          <div className="result-surface">
            {taskStatus === "submitted" ? (
              <div className="submitted-state">
                <div className="state-orb submitted" aria-hidden="true">
                  <Icon name="check" size={28} />
                </div>
                <h3>RunningHub 任务已提交</h3>
                <p>{videoPanelMessage}</p>
                {runningHubResult?.taskId && (
                  <div className="runninghub-task-id">
                    <span>任务 ID</span>
                    <strong>{runningHubResult.taskId}</strong>
                  </div>
                )}
                <div className="runninghub-link-row">
                  <a
                    className="download-action"
                    href={runningHubResult?.taskUrl || RUNNINGHUB_TASKS_URL}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Icon name="external" size={16} />
                    查看任务进度
                  </a>
                  <a
                    className="secondary-link-action"
                    href={runningHubResult?.worksUrl || RUNNINGHUB_WORKS_URL}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Icon name="external" size={16} />
                    查看我的作品
                  </a>
                </div>
              </div>
            ) : (
              <div className="empty-state">
                <div className={`state-orb ${videoPanelStatus}`} aria-hidden="true">
                  {videoPanelStatus === "failed" ? (
                    <Icon name="alert" size={26} />
                  ) : videoPanelStatus === "running" || videoPanelStatus === "pending" ? (
                    `${progress}%`
                  ) : (
                    <Icon name="video" size={28} />
                  )}
                </div>
                <h3>{VIDEO_STEP_LABELS[videoPanelStatus]}</h3>
                <p>{videoPanelMessage}</p>
              </div>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
