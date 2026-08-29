import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import { statusChipColors } from "../theme";
import Icon from "./Icon";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import { apiJson, useBackendBaseUrl } from "../lib/backend";

const VIDEO_STEP_LABELS = {
  idle: "等待素材",
  ready: "可生成视频",
  pending: "任务排队中",
  running: "正在生成视频",
  submitted: "任务已提交",
  completed: "任务已完成",
  failed: "生成失败",
};

const RUNNINGHUB_TASKS_URL = "https://www.runninghub.cn/bill-task";
const RUNNINGHUB_WORKS_URL = "https://www.runninghub.cn/user-center";

function pollTask(taskId, signal, backendBaseUrl) {
  return apiJson(`/api/task/${taskId}`, { signal, silentError: true }, backendBaseUrl);
}

function formatFileSize(size) {
  if (!size) return "";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function isReadableMessage(message) {
  return typeof message === "string" && message.trim() && !/[锟]/.test(message);
}

export default function DigitalHuman({ onOpenTtsStudio }) {
  const backendBaseUrl = useBackendBaseUrl();
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState("");
  const [audioFile, setAudioFile] = useState(null);
  const [audioLocalUrl, setAudioLocalUrl] = useState("");
  const [taskStatus, setTaskStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [runningHubResult, setRunningHubResult] = useState(null);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);

  const imageInputRef = useRef(null);
  const audioInputRef = useRef(null);
  const pollTimeoutRef = useRef(null);
  const pollAbortRef = useRef(null);

  const stopPolling = useCallback(() => {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
    if (pollAbortRef.current) {
      pollAbortRef.current.abort();
      pollAbortRef.current = null;
    }
  }, []);

  const resetVideoState = useCallback(() => {
    stopPolling();
    setTaskStatus("idle");
    setProgress(0);
    setStatusMsg("");
    setVideoUrl("");
    setRunningHubResult(null);
    setError("");
    setGenerating(false);
  }, [stopPolling]);

  useEffect(() => {
    return () => {
      stopPolling();
      if (imagePreview) URL.revokeObjectURL(imagePreview);
      if (audioLocalUrl) URL.revokeObjectURL(audioLocalUrl);
    };
  }, [audioLocalUrl, imagePreview, stopPolling]);

  const handleImageChange = useCallback(
    (event) => {
      const file = event.target.files?.[0];
      if (!file) return;

      const nextPreview = URL.createObjectURL(file);
      setImageFile(file);
      setImagePreview((current) => {
        if (current) URL.revokeObjectURL(current);
        return nextPreview;
      });
      resetVideoState();
    },
    [resetVideoState]
  );

  const handleAudioChange = useCallback(
    (event) => {
      const file = event.target.files?.[0];
      if (!file) return;

      const nextAudioUrl = URL.createObjectURL(file);
      setAudioFile(file);
      setAudioLocalUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return nextAudioUrl;
      });
      resetVideoState();
    },
    [resetVideoState]
  );

  const removeImage = useCallback(() => {
    setImageFile(null);
    setImagePreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
    if (imageInputRef.current) imageInputRef.current.value = "";
    resetVideoState();
  }, [resetVideoState]);

  const removeAudio = useCallback(() => {
    setAudioFile(null);
    setAudioLocalUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
    if (audioInputRef.current) audioInputRef.current.value = "";
    resetVideoState();
  }, [resetVideoState]);

  const inputsReady = Boolean(imageFile && audioFile);
  const canGenerateVideo = Boolean(inputsReady && !generating && taskStatus !== "submitted");

  const pipelineItems = useMemo(
    () => [
      {
        label: "人物图片",
        detail: imageFile ? imageFile.name : "等待上传图片",
        state: imageFile ? "completed" : "idle",
        icon: "image",
      },
      {
        label: "口播音频",
        detail: audioFile ? audioFile.name : "等待上传音频",
        state: audioFile ? "completed" : "idle",
        icon: "audio",
      },
      {
        label: "云端生成",
        detail:
          taskStatus === "submitted"
            ? "已提交 RunningHub"
            : taskStatus === "completed"
              ? runningHubResult && !videoUrl
                ? "RunningHub 已接收"
                : "视频已生成"
              : taskStatus === "failed"
                ? "需要检查任务"
                : "RunningHub 队列",
        state: ["pending", "running"].includes(taskStatus) ? "running" : taskStatus,
        icon: "cloud",
      },
    ],
    [audioFile, imageFile, runningHubResult, taskStatus, videoUrl]
  );

  const detailMessage = useMemo(() => {
    if (taskStatus === "failed") return error || "任务执行失败，请检查素材后重试。";
    if (taskStatus === "submitted") return statusMsg || "RunningHub 任务已提交成功，请到 RunningHub 查看进度和作品。";
    if (taskStatus === "completed") {
      return videoUrl
        ? "视频已生成，可预览或下载。"
        : statusMsg || "RunningHub 已接收任务，请到 RunningHub 查看生成进度和作品。";
    }
    if (isReadableMessage(statusMsg)) return statusMsg;
    if (taskStatus === "pending" || taskStatus === "running") return "正在上传素材并创建 RunningHub 任务。";
    if (inputsReady) return "人物图片和口播音频已就绪，可以提交生成视频。";
    if (imageFile) return "人物图片已就绪，请上传在语音合成页面生成并下载的音频。";
    if (audioFile) return "口播音频已就绪，请补充人物图片后再生成视频。";
    return "请先上传人物图片与口播音频。";
  }, [audioFile, error, imageFile, inputsReady, statusMsg, taskStatus, videoUrl]);

  const videoPanelStatus = useMemo(() => {
    if (taskStatus === "completed") return "completed";
    if (["pending", "running", "submitted"].includes(taskStatus)) return taskStatus;
    if (taskStatus === "failed") return "failed";
    return inputsReady ? "ready" : "idle";
  }, [inputsReady, taskStatus]);

  const handleGenerateVideo = useCallback(async () => {
    if (!canGenerateVideo) return;

    stopPolling();
    setGenerating(true);
    setError("");
    setVideoUrl("");
    setRunningHubResult(null);
    setProgress(0);
    setTaskStatus("pending");
    setStatusMsg("正在提交视频生成任务...");

    try {
      const formData = new FormData();
      formData.append("image", imageFile);
      formData.append("audio", audioFile);

      const data = await apiJson(
        "/api/generate-video",
        { method: "POST", body: formData, silentError: true },
        backendBaseUrl
      );

      const { task_id: taskId } = data;
      if (!taskId) throw new Error("后端没有返回视频任务 ID。");

      const controller = new AbortController();
      pollAbortRef.current = controller;
      setTaskStatus("running");
      setStatusMsg("正在上传素材并创建 RunningHub 任务...");

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
            setProgress(100);
            setGenerating(false);
            pollAbortRef.current = null;
            return;
          }

          if (data.status === "completed") {
            setTaskStatus("completed");
            setVideoUrl(data.video_url ?? "");
            setRunningHubResult(
              data.runninghub_task_id
                ? {
                    taskId: data.runninghub_task_id,
                    taskUrl: data.runninghub_task_url || RUNNINGHUB_TASKS_URL,
                    worksUrl: data.runninghub_works_url || RUNNINGHUB_WORKS_URL,
                  }
                : null
            );
            setProgress(100);
            setGenerating(false);
            pollAbortRef.current = null;
            return;
          }

          if (data.status === "failed") {
            setTaskStatus("failed");
            setError(data.error ?? data.message ?? "未知错误");
            setGenerating(false);
            pollAbortRef.current = null;
            return;
          }

          setTaskStatus(data.status === "pending" ? "pending" : "running");
          pollTimeoutRef.current = setTimeout(poll, 3000);
        } catch (pollError) {
          if (pollError.name === "AbortError") return;
          setTaskStatus("failed");
          setError(pollError.message || "查询任务状态失败");
          setGenerating(false);
          pollAbortRef.current = null;
        }
      };

      pollTimeoutRef.current = setTimeout(poll, 1200);
    } catch (requestError) {
      setTaskStatus("failed");
      setError(requestError.message || "创建视频任务失败");
      setGenerating(false);
    }
  }, [audioFile, backendBaseUrl, canGenerateVideo, imageFile, stopPolling]);

  return (
    <>
      <section className="workspace-panel production-panel" aria-label="素材上传工作区">
        <div className="pipeline-strip" aria-label="生产管线状态">
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

        <div className="production-grid">
          <div className="workflow-card media-workflow">
            <div className="control-section-heading">
              <span>01</span>
              <strong>人物素材</strong>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="character-image">
                人物形象图片 *
              </label>
              <label className={`upload-dropzone ${imagePreview ? "is-filled" : ""}`}>
                {imagePreview ? (
                  <span className="image-preview-frame">
                    <img src={imagePreview} alt="人物形象预览" className="preview-img" />
                  </span>
                ) : (
                  <span className="upload-placeholder">
                    <Icon name="imageAdd" size={22} />
                    <strong>选择图片</strong>
                    <small>JPG、PNG 或 WebP</small>
                  </span>
                )}
                <input
                  ref={imageInputRef}
                  id="character-image"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={handleImageChange}
                />
              </label>
              {imageFile && (
                <div className="file-row">
                  <span>{imageFile.name}</span>
                  <Button type="button" variant="text" size="small" onClick={removeImage}>
                    移除
                  </Button>
                </div>
              )}
            </div>
          </div>

          <div className="workflow-card digital-human-audio-workflow">
            <div className="control-section-heading digital-human-audio-heading">
              <span>02</span>
              <strong>口播音频</strong>
              <Button className="digital-human-tts-link" type="button" variant="text" size="small" onClick={onOpenTtsStudio}>
                前往语音合成
                <Icon name="arrowRight" size={14} />
              </Button>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="digital-human-audio-file">
                音频文件 *
              </label>
              <label className={`upload-dropzone compact ${audioFile ? "is-filled" : ""}`}>
                <span className="upload-placeholder">
                  <Icon name={audioFile ? "audio" : "upload"} size={22} />
                  <strong>{audioFile ? audioFile.name : "选择音频"}</strong>
                  <small>{audioFile ? formatFileSize(audioFile.size) : "MP3、WAV 或其他常见格式"}</small>
                </span>
                <input
                  ref={audioInputRef}
                  id="digital-human-audio-file"
                  type="file"
                  accept="audio/*"
                  onChange={handleAudioChange}
                />
              </label>
              {audioFile && (
                <>
                  <div className="file-row">
                    <span>{audioFile.name}</span>
                    <Button type="button" variant="text" size="small" onClick={removeAudio}>
                      移除
                    </Button>
                  </div>
                  <audio className="audio-player" src={audioLocalUrl} controls />
                </>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="workspace-panel output-panel" aria-labelledby="output-title">
        <div className="panel-heading">
          <div>
            <h2 id="output-title">生成数字人视频</h2>
          </div>
          <Chip
            size="small"
            icon={
              <Icon
                name={
                  videoPanelStatus === "failed"
                    ? "alert"
                    : videoPanelStatus === "completed" || videoPanelStatus === "submitted"
                      ? "check"
                      : ["running", "pending"].includes(videoPanelStatus)
                        ? "loading"
                        : "gauge"
                }
                size={14}
              />
            }
            label={VIDEO_STEP_LABELS[videoPanelStatus]}
            sx={{
              backgroundColor: statusChipColors[videoPanelStatus]?.bg || "#f3f1e9",
              color: statusChipColors[videoPanelStatus]?.fg || "#68645b",
              fontWeight: 600,
              "& .vf-icon": { color: statusChipColors[videoPanelStatus]?.fg || "#68645b" },
            }}
          />
        </div>

        <div className="video-workflow">
          <div className="video-status-card">
            <Typography variant="kicker" component="span" className="section-kicker with-icon">
              <Icon name="cloud" size={13} />
              Video
            </Typography>
            <h3>提交生成任务</h3>
            <p>{detailMessage}</p>
            <Button type="button" variant="contained" disabled={!canGenerateVideo} onClick={handleGenerateVideo}
              startIcon={<Icon name={generating ? "loading" : "wand"} size={16} />}>
              {taskStatus === "submitted" ? "任务已提交" : generating ? "正在生成视频" : "生成数字人视频"}
            </Button>
            {(["pending", "running"].includes(taskStatus) || progress > 0) && taskStatus !== "submitted" && (
              <div className="progress-area" aria-label="生成进度">
                <div className="progress-meta">
                  <span>{detailMessage}</span>
                  <strong>{progress}%</strong>
                </div>
                <LinearProgress variant="determinate" value={progress} sx={{ mt: 0.5 }} />
              </div>
            )}
            {error && taskStatus === "failed" && <div className="form-alert failed">{error}</div>}
          </div>

          <div className={`result-surface ${videoUrl ? "has-video" : ""}`}>
            {taskStatus === "submitted" || (taskStatus === "completed" && !videoUrl && runningHubResult) ? (
              <div className="submitted-state">
                <div className="state-orb submitted" aria-hidden="true">
                  <Icon name="check" size={28} />
                </div>
                <h3>RunningHub 任务已提交</h3>
                <p>{detailMessage}</p>
                {runningHubResult?.taskId && (
                  <div className="runninghub-task-id">
                    <span>任务 ID</span>
                    <strong>{runningHubResult.taskId}</strong>
                  </div>
                )}
                <div className="runninghub-link-row">
                  <Button
                    href={runningHubResult?.taskUrl || RUNNINGHUB_TASKS_URL}
                    target="_blank"
                    rel="noreferrer"
                    variant="outlined"
                    size="small"
                    startIcon={<Icon name="external" size={16} />}
                  >
                    查看任务进度
                  </Button>
                  <Button
                    href={runningHubResult?.worksUrl || RUNNINGHUB_WORKS_URL}
                    target="_blank"
                    rel="noreferrer"
                    variant="text"
                    size="small"
                    startIcon={<Icon name="external" size={16} />}
                  >
                    查看我的作品
                  </Button>
                </div>
              </div>
            ) : taskStatus === "completed" && videoUrl ? (
              <>
                <ProtectedMedia
                  className="result-video"
                  path={videoUrl}
                  kind="video"
                  backendBaseUrl={backendBaseUrl}
                />
                <ProtectedDownloadButton
                  path={videoUrl}
                  filename="digital_human.mp4"
                  backendBaseUrl={backendBaseUrl}
                >
                  <Icon name="download" size={16} />
                  下载视频
                </ProtectedDownloadButton>
              </>
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
                <p>{detailMessage}</p>
              </div>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
