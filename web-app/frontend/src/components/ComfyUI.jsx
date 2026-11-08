import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { statusChipColors } from "../theme";
import Icon from "./Icon";
import Spinner from "./Spinner";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import { apiJson, useBackendBaseUrl } from "../lib/backend";

const VIDEO_STEP_LABELS = {
  idle: "等待输入",
  ready: "可提交",
  pending: "任务排队中",
  running: "正在提交",
  submitted: "任务已提交",
  completed: "任务已完成",
  failed: "提交失败",
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

export default function ComfyUI({ onOpenTtsStudio }) {
  const backendBaseUrl = useBackendBaseUrl();
  const [workflows, setWorkflows] = useState([]);
  const [workflowKey, setWorkflowKey] = useState("");
  const [workflowInputs, setWorkflowInputs] = useState({});
  const [previews, setPreviews] = useState({});
  const [catalogError, setCatalogError] = useState("");
  const [taskStatus, setTaskStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [providerResult, setProviderResult] = useState(null);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);

  const fileInputRefs = useRef({});
  const pollTimeoutRef = useRef(null);
  const pollAbortRef = useRef(null);

  const selectedWorkflow = workflows.find((workflow) => workflow.key === workflowKey) || null;
  const fields = selectedWorkflow?.inputs || [];
  const requiredFieldsReady = fields
    .filter((field) => field.required)
    .every((field) => Boolean(workflowInputs[field.key]));
  const inputsReady = Boolean(selectedWorkflow && requiredFieldsReady);
  const canGenerate = Boolean(inputsReady && !generating && taskStatus !== "submitted");

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

  const resetTaskState = useCallback(() => {
    stopPolling();
    setTaskStatus("idle");
    setProgress(0);
    setStatusMsg("");
    setVideoUrl("");
    setProviderResult(null);
    setError("");
    setGenerating(false);
  }, [stopPolling]);

  useEffect(() => {
    const controller = new AbortController();
    apiJson("/api/workflows", { signal: controller.signal, silentError: true }, backendBaseUrl)
      .then((data) => {
        if (!Array.isArray(data)) throw new Error("工作流目录格式不正确");
        setWorkflows(data);
        setWorkflowKey((current) => current || data[0]?.key || "");
        setCatalogError("");
      })
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setCatalogError(requestError.message || "读取工作流目录失败");
        }
      });
    return () => controller.abort();
  }, [backendBaseUrl]);

  useEffect(() => {
    return () => {
      stopPolling();
      Object.values(previews).forEach((url) => URL.revokeObjectURL(url));
    };
  }, [previews, stopPolling]);

  const handleWorkflowChange = useCallback((nextWorkflowKey) => {
    setWorkflowKey(nextWorkflowKey);
    setWorkflowInputs({});
    setPreviews({});
    resetTaskState();
  }, [resetTaskState]);

  const handleInputChange = useCallback((field, value) => {
    setWorkflowInputs((current) => ({ ...current, [field.key]: value }));
    resetTaskState();
  }, [resetTaskState]);

  const handleFileChange = useCallback((field, event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (field.type === "image" || field.type === "audio") {
      const url = URL.createObjectURL(file);
      setPreviews((current) => {
        if (current[field.key]) URL.revokeObjectURL(current[field.key]);
        return { ...current, [field.key]: url };
      });
    }
    setWorkflowInputs((current) => ({ ...current, [field.key]: file }));
    resetTaskState();
  }, [resetTaskState]);

  const removeFile = useCallback((field) => {
    setWorkflowInputs((current) => ({ ...current, [field.key]: null }));
    setPreviews((current) => {
      if (current[field.key]) URL.revokeObjectURL(current[field.key]);
      const next = { ...current };
      delete next[field.key];
      return next;
    });
    if (fileInputRefs.current[field.key]) fileInputRefs.current[field.key].value = "";
    resetTaskState();
  }, [resetTaskState]);

  const detailMessage = useMemo(() => {
    if (catalogError) return catalogError;
    if (taskStatus === "failed") return error || "工作流提交失败，请检查输入后重试。";
    if (taskStatus === "submitted") {
      return statusMsg || "工作流任务已提交成功，请到 RunningHub 查看进度和作品。";
    }
    if (taskStatus === "completed") {
      return videoUrl ? "视频已生成，可预览或下载。" : statusMsg;
    }
    if (isReadableMessage(statusMsg)) return statusMsg;
    if (taskStatus === "pending" || taskStatus === "running") return "正在上传素材并提交工作流...";
    if (!selectedWorkflow) return "当前没有可用工作流。";
    if (inputsReady) return "工作流输入已就绪，可以提交任务。";
    return "请填写工作流要求的输入参数。";
  }, [catalogError, error, inputsReady, selectedWorkflow, statusMsg, taskStatus, videoUrl]);

  const videoPanelStatus = useMemo(() => {
    if (taskStatus === "completed") return "completed";
    if (["pending", "running", "submitted"].includes(taskStatus)) return taskStatus;
    if (taskStatus === "failed") return "failed";
    return inputsReady ? "ready" : "idle";
  }, [inputsReady, taskStatus]);

  const handleGenerate = useCallback(async () => {
    if (!canGenerate || !selectedWorkflow) return;

    stopPolling();
    setGenerating(true);
    setError("");
    setVideoUrl("");
    setProviderResult(null);
    setProgress(0);
    setTaskStatus("pending");
    setStatusMsg("正在提交工作流任务...");

    try {
      const formData = new FormData();
      for (const field of fields) {
        const value = workflowInputs[field.key];
        if (value !== undefined && value !== null && value !== "") {
          formData.append(field.key, value);
        }
      }
      const data = await apiJson(
        `/api/workflows/${encodeURIComponent(selectedWorkflow.key)}/generate`,
        { method: "POST", body: formData, silentError: true },
        backendBaseUrl
      );
      const { task_id: taskId } = data;
      if (!taskId) throw new Error("后端没有返回工作流任务 ID。");

      const controller = new AbortController();
      pollAbortRef.current = controller;
      setTaskStatus("running");
      setStatusMsg("正在提交 ComfyUI 工作流...");

      const poll = async () => {
        try {
          const result = await pollTask(taskId, controller.signal, backendBaseUrl);
          setProgress(result.progress ?? 0);
          setStatusMsg(result.message ?? "");

          if (result.status === "submitted" || result.status === "completed") {
            setTaskStatus(result.status);
            setVideoUrl(result.video_url ?? "");
            const providerTaskId = result.provider_task_id || result.runninghub_task_id;
            setProviderResult(providerTaskId ? {
              taskId: providerTaskId,
              taskUrl: result.provider_task_url || result.runninghub_task_url || RUNNINGHUB_TASKS_URL,
              dashboardUrl: result.provider_dashboard_url || result.runninghub_works_url || RUNNINGHUB_WORKS_URL,
            } : null);
            setProgress(100);
            setGenerating(false);
            pollAbortRef.current = null;
            return;
          }

          if (result.status === "failed") {
            setTaskStatus("failed");
            setError(result.error ?? result.message ?? "未知错误");
            setGenerating(false);
            pollAbortRef.current = null;
            return;
          }

          setTaskStatus(result.status === "pending" ? "pending" : "running");
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
      setError(requestError.message || "创建工作流任务失败");
      setGenerating(false);
    }
  }, [backendBaseUrl, canGenerate, fields, selectedWorkflow, stopPolling, workflowInputs]);

  return (
    <>
      <section className="workspace-panel production-panel" aria-label="工作流输入">
        <Tabs
          value={workflowKey || false}
          onChange={(_, value) => handleWorkflowChange(value)}
          aria-label="选择 ComfyUI 工作流"
          sx={{ mb: 2, minHeight: 40, "& .MuiTab-root": { minHeight: 40, fontSize: 14, fontWeight: 600 } }}
        >
          {workflows.map((workflow) => (
            <Tab key={workflow.key} value={workflow.key} label={workflow.name} disabled={generating} />
          ))}
        </Tabs>
        {catalogError && <div className="form-alert failed">{catalogError}</div>}

        <div className="production-grid">
          {fields.filter((field) => field.type === "image").length > 0 && (
            <div className="workflow-card media-workflow">
              <div className="control-section-heading">
                <span>01</span>
                <strong>图片素材</strong>
              </div>
              {fields.filter((field) => field.type === "image").map((field) => {
                const value = workflowInputs[field.key];
                const previewUrl = previews[field.key];
                return (
                  <div className="field" key={field.key}>
                    <label className="field-label" htmlFor={`workflow-input-${field.key}`}>
                      {field.label}{field.required ? " *" : ""}
                    </label>
                    <label className={`upload-dropzone ${value ? "is-filled" : ""}`}>
                      {previewUrl ? (
                        <span className="image-preview-frame">
                          <img src={previewUrl} alt={`${field.label}预览`} className="preview-img" />
                        </span>
                      ) : (
                        <span className="upload-placeholder">
                          <Icon name="imageAdd" size={22} />
                          <strong>{value?.name || `选择${field.label}`}</strong>
                          <small>{value ? formatFileSize(value.size) : field.accept}</small>
                        </span>
                      )}
                      <input
                        ref={(node) => { fileInputRefs.current[field.key] = node; }}
                        id={`workflow-input-${field.key}`}
                        type="file"
                        accept={field.accept}
                        onChange={(event) => handleFileChange(field, event)}
                      />
                    </label>
                    {value && (
                      <div className="file-row">
                        <span>{value.name}</span>
                        <Button type="button" variant="text" size="small" onClick={() => removeFile(field)}>
                          移除
                        </Button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="workflow-card digital-human-audio-workflow">
            <div className="control-section-heading digital-human-audio-heading">
              <span>{fields.filter((field) => field.type === "image").length > 0 ? "02" : "01"}</span>
              <strong>其他输入</strong>
              <Button
                className="digital-human-tts-link"
                type="button"
                variant="text"
                size="small"
                disableRipple
                onClick={onOpenTtsStudio}
              >
                前往语音合成
                <Icon name="arrowRight" size={14} />
              </Button>
            </div>
            <div className="workflow-input-list">
              {fields.filter((field) => field.type !== "image").map((field) => {
                const value = workflowInputs[field.key];
                if (field.type === "audio") {
                  const previewUrl = previews[field.key];
                  return (
                    <div className="field" key={field.key}>
                      <label className="field-label" htmlFor={`workflow-input-${field.key}`}>
                        {field.label}{field.required ? " *" : ""}
                      </label>
                      <label className={`upload-dropzone compact ${value ? "is-filled" : ""}`}>
                        <span className="upload-placeholder">
                          <Icon name="upload" size={22} />
                          <strong>{value?.name || `选择${field.label}`}</strong>
                          <small>{value ? formatFileSize(value.size) : field.accept}</small>
                        </span>
                        <input
                          ref={(node) => { fileInputRefs.current[field.key] = node; }}
                          id={`workflow-input-${field.key}`}
                          type="file"
                          accept={field.accept}
                          onChange={(event) => handleFileChange(field, event)}
                        />
                      </label>
                      {value && (
                        <div className="file-row">
                          <span>{value.name}</span>
                          <Button type="button" variant="text" size="small" onClick={() => removeFile(field)}>
                            移除
                          </Button>
                        </div>
                      )}
                      {previewUrl && (
                        <audio className="audio-player" src={previewUrl} controls />
                      )}
                    </div>
                  );
                }
                if (field.type === "select") {
                  return (
                    <TextField
                      key={field.key}
                      select
                      fullWidth
                      size="small"
                      label={field.label}
                      required={field.required}
                      value={value ?? field.default ?? ""}
                      onChange={(event) => handleInputChange(field, event.target.value)}
                    >
                      {(field.options || []).map((option) => (
                        <MenuItem key={option} value={option}>{option}</MenuItem>
                      ))}
                    </TextField>
                  );
                }
                return (
                  <TextField
                    key={field.key}
                    fullWidth
                    size="small"
                    type={field.type === "number" ? "number" : "text"}
                    label={field.label}
                    required={field.required}
                    multiline={Boolean(field.multiline)}
                    minRows={field.multiline ? 3 : undefined}
                    value={value ?? field.default ?? ""}
                    inputProps={{
                      min: field.min,
                      max: field.max,
                      maxLength: field.max_length,
                    }}
                    onChange={(event) => handleInputChange(field, event.target.value)}
                  />
                );
              })}
              {fields.filter((field) => field.type !== "image").length === 0 && (
                <Typography color="text.secondary">此工作流无其他输入参数。</Typography>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="workspace-panel output-panel" aria-labelledby="output-title">
        <div className="panel-heading">
          <div><h2 id="output-title">提交工作流任务</h2></div>
          <Chip
            size="small"
            icon={
              videoPanelStatus === "failed"
                ? <Icon name="alert" size={14} />
                : videoPanelStatus === "completed" || videoPanelStatus === "submitted"
                  ? <Icon name="check" size={14} />
                  : ["running", "pending"].includes(videoPanelStatus)
                    ? <Spinner size={14} />
                    : <Icon name="gauge" size={14} />
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
              ComfyUI
            </Typography>
            <h3>{selectedWorkflow?.name || "工作流任务"}</h3>
            <p>{detailMessage}</p>
            <Button
              type="button"
              variant="contained"
              disabled={!canGenerate}
              onClick={handleGenerate}
              startIcon={generating ? <Spinner size={16} /> : <Icon name="wand" size={16} />}
            >
              {taskStatus === "submitted" ? "任务已提交" : generating ? "正在提交" : "提交工作流"}
            </Button>
            {(["pending", "running"].includes(taskStatus) || progress > 0) && taskStatus !== "submitted" && (
              <div className="progress-area" aria-label="提交进度">
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
            {taskStatus === "submitted" || (taskStatus === "completed" && !videoUrl && providerResult) ? (
              <div className="submitted-state">
                <div className="state-orb submitted" aria-hidden="true"><Icon name="check" size={28} /></div>
                <h3>工作流任务已提交</h3>
                <p>{detailMessage}</p>
                {providerResult?.taskId && (
                  <div className="runninghub-task-id">
                    <span>远端任务 ID</span>
                    <strong>{providerResult.taskId}</strong>
                  </div>
                )}
                <div className="runninghub-link-row">
                  <Button href={providerResult?.taskUrl || RUNNINGHUB_TASKS_URL} target="_blank" rel="noreferrer" variant="outlined" size="small" startIcon={<Icon name="external" size={16} />}>
                    查看任务进度
                  </Button>
                  <Button href={providerResult?.dashboardUrl || RUNNINGHUB_WORKS_URL} target="_blank" rel="noreferrer" variant="text" size="small" startIcon={<Icon name="external" size={16} />}>
                    查看我的作品
                  </Button>
                </div>
              </div>
            ) : taskStatus === "completed" && videoUrl ? (
              <>
                <ProtectedMedia className="result-video" path={videoUrl} kind="video" backendBaseUrl={backendBaseUrl} />
                <ProtectedDownloadButton path={videoUrl} filename="comfyui-workflow.mp4" backendBaseUrl={backendBaseUrl}>
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
