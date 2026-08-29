import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Chip from "@mui/material/Chip";
import Slider from "@mui/material/Slider";
import Switch from "@mui/material/Switch";
import LinearProgress from "@mui/material/LinearProgress";
import Dialog from "@mui/material/Dialog";
import { statusChipColors } from "../theme";
import BgmManager from "./BgmManager";
import Icon from "./Icon";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import SubtitleReplacementManager from "./SubtitleReplacementManager";
import { apiFetch, apiJson, useBackendBaseUrl } from "../lib/backend";
import { useGlobalMessage } from "./GlobalMessageProvider";

const FINAL_STATUSES = new Set(["completed", "partial_failed", "failed"]);
const SUBTITLE_PREVIEW_TEXT = "这是一段用于查看字幕样式的预览内容";
const DEFAULT_SUBTITLE_STYLE = {
  font_family: "Microsoft YaHei",
  font_size: 65,
  color: "#FFD21F",
  outline_color: "#000000",
  outline_width: 5,
  bottom_margin: 250,
  alignment: "center",
  notice_enabled: true,
  notice_text: "人文记录 无不良引导\n如有不适 请线上就医",
  notice_font_size: 33,
  notice_color: "#FFFFFF",
  notice_outline_color: "#000000",
  notice_outline_width: 1,
  notice_top_margin: 106,
};

function cloneDefaultSubtitleStyle() {
  return { ...DEFAULT_SUBTITLE_STYLE };
}

function withOpacity(color, opacity) {
  const normalized = String(color || "").trim();
  return /^#[0-9a-f]{6}$/i.test(normalized) ? `${normalized}${opacity}` : normalized;
}

function subtitlePreviewStyle(style, type) {
  const isNotice = type === "notice";
  const fontSize = Number(isNotice ? style.notice_font_size : style.font_size) || 1;
  const outlineWidth = Number(isNotice ? style.notice_outline_width : style.outline_width) || 0;
  const color = isNotice ? style.notice_color : style.color;
  const outlineColor = isNotice
    ? withOpacity(style.notice_outline_color, "B0")
    : style.outline_color;
  const fontFamily = style.font_family || DEFAULT_SUBTITLE_STYLE.font_family;

  return {
    color,
    fontFamily: `"${fontFamily}", "Microsoft YaHei", sans-serif`,
    // The preview canvas uses container-query units so the 1080x1920 design
    // remains proportional when the editor column changes width.
    fontSize: `${(fontSize / 1920) * 100}cqh`,
    WebkitTextStroke: outlineWidth > 0 ? `${(outlineWidth / 1920) * 100}cqh ${outlineColor}` : undefined,
    textShadow: outlineWidth > 0 ? `0 0 ${(outlineWidth / 1920) * 1.5}cqh ${outlineColor}` : "none",
  };
}

function SubtitleStylePreview({ style }) {
  const noticeText = String(style.notice_text || "").trim();

  return (
    <div className="subtitle-style-preview" aria-label="字幕样式预览">
      <div className="subtitle-preview-canvas">
        <div className="subtitle-preview-backdrop" aria-hidden="true" />
        {style.notice_enabled && noticeText ? (
          <div
            className="subtitle-preview-notice"
            style={{ ...subtitlePreviewStyle(style, "notice"), top: `${(Number(style.notice_top_margin) / 1920) * 100}%` }}
          >
            {noticeText}
          </div>
        ) : null}
        <div
          className={`subtitle-preview-main is-${style.alignment || "center"}`}
          style={{
            ...subtitlePreviewStyle(style, "subtitle"),
            bottom: `${(Number(style.bottom_margin) / 1920) * 100}%`,
          }}
        >
          {SUBTITLE_PREVIEW_TEXT}
        </div>
      </div>
    </div>
  );
}

function templateContentDefaults(template) {
  return Object.fromEntries(
    (template?.content_fields || [])
      .filter((field) => field.default !== null && field.default !== undefined)
      .map((field) => [field.key, String(field.default)])
  );
}

function templateDefaultBatchSize(template) {
  const maximum = Math.max(1, Number(template?.production?.max_batch_size) || 50);
  return Math.max(1, Math.min(maximum, Number(template?.production?.default_batch_size) || 5));
}

function templateCandidateCount(template) {
  return Math.max(1, Number(template?.script_generation?.default_candidate_count) || 3);
}

function exportFilename(response, templateId) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (utf8Name) {
    try {
      return decodeURIComponent(utf8Name);
    } catch {
      return `${templateId}.json`;
    }
  }
  return disposition.match(/filename="?([^";]+)"?/i)?.[1] || `${templateId}.json`;
}

function makeId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function statusLabel(status) {
  return {
    pending: "等待处理",
    running: "生成中",
    completed: "已完成",
    partial_failed: "部分失败",
    failed: "失败",
  }[status] || "准备中";
}

function formatFileSize(size) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function MaterialPreview({ file, mediaType, label }) {
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => {
    const nextUrl = URL.createObjectURL(file);
    setPreviewUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [file]);

  if (!previewUrl) {
    return <div className="material-preview-media is-loading" aria-label={`${label}加载中`} />;
  }

  return (
    <div className="material-preview-media">
      {mediaType === "image" ? (
        <img src={previewUrl} alt={`${label}预览`} />
      ) : (
        <video src={previewUrl} controls muted playsInline preload="metadata" aria-label={`${label}预览`} />
      )}
    </div>
  );
}

function ContentFieldControl({ field, value, onChange }) {
  const sharedProps = {
    className: "field",
    fullWidth: true,
    size: "small",
    label: `${field.label}${field.required ? " *" : ""}`,
    value,
    required: Boolean(field.required),
    onChange: (event) => onChange(event.target.value),
  };

  let control;
  if (field.input_type === "textarea") {
    control = (
      <TextField
        {...sharedProps}
        multiline
        rows={4}
        slotProps={{ htmlInput: { minLength: field.min_length ?? undefined, maxLength: field.max_length ?? undefined } }}
        placeholder={field.placeholder || "请输入内容"}
      />
    );
  } else if (field.input_type === "select") {
    control = (
      <TextField {...sharedProps} select>
        <MenuItem value="">{field.placeholder || `请选择${field.label}`}</MenuItem>
        {(field.options || []).map((option) => (
          <MenuItem key={option.value} value={option.value}>{option.label}</MenuItem>
        ))}
      </TextField>
    );
  } else {
    control = (
      <TextField
        {...sharedProps}
        type="text"
        slotProps={{ htmlInput: { minLength: field.min_length ?? undefined, maxLength: field.max_length ?? undefined } }}
        placeholder={field.placeholder || "请输入内容"}
      />
    );
  }

  return (
    <div className="field">
      {control}
      {field.help_text ? <small className="field-help">{field.help_text}</small> : null}
    </div>
  );
}

export default function TemplateProduction({ currentUser }) {
  const backendBaseUrl = useBackendBaseUrl();
  const { showSuccess } = useGlobalMessage();
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templateError, setTemplateError] = useState("");
  const [importingTemplate, setImportingTemplate] = useState(false);
  const [exportingTemplate, setExportingTemplate] = useState(false);
  const [templateId, setTemplateId] = useState("");
  const [variables, setVariables] = useState({});
  const [materials, setMaterials] = useState({});
  const [scriptCandidates, setScriptCandidates] = useState([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [finalScript, setFinalScript] = useState("");
  const [subtitleStyle, setSubtitleStyle] = useState(cloneDefaultSubtitleStyle);
  const [subtitleStyleDialogOpen, setSubtitleStyleDialogOpen] = useState(false);
  const [subtitleReplacementStatus, setSubtitleReplacementStatus] = useState({
    issues: [],
    hasUnsaved: false,
    loading: true,
    error: "",
  });
  const [rewritingCandidateId, setRewritingCandidateId] = useState("");
  const [generateCount, setGenerateCount] = useState(5);
  const [generatingScripts, setGeneratingScripts] = useState(false);
  const [task, setTask] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [selectedBgmId, setSelectedBgmId] = useState("");
  const pollRef = useRef(null);
  const templateFileInputRef = useRef(null);
  const previousTemplateIdRef = useRef("");

  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === templateId) || null,
    [templateId, templates]
  );
  const taskStorageKey = `vf.templateProductionTask.v1.${currentUser?.id || "local"}`;

  const maxBatchSize = Math.max(1, Number(selectedTemplate?.production?.max_batch_size) || 50);
  const defaultCandidateCount = templateCandidateCount(selectedTemplate);

  const loadTemplates = useCallback(async ({ signal, selectId } = {}) => {
    setTemplatesLoading(true);
    setTemplateError("");
    try {
      const data = await apiJson(
        "/api/template-production/templates",
        { ...(signal ? { signal } : {}), silentError: true },
        backendBaseUrl
      );
      const nextTemplates = Array.isArray(data.templates) ? data.templates : [];
      setTemplates(nextTemplates);
      setTemplateId((currentId) => {
        if (selectId && nextTemplates.some((item) => item.id === selectId)) return selectId;
        if (nextTemplates.some((item) => item.id === currentId)) return currentId;
        return nextTemplates[0]?.id || "";
      });
      return nextTemplates;
    } catch (err) {
      if (err?.name === "AbortError") return null;
      setTemplateError(err.message || "读取模板列表失败");
      return null;
    } finally {
      if (!signal?.aborted) setTemplatesLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    loadTemplates({ signal: controller.signal });
    return () => controller.abort();
  }, [currentUser?.id, loadTemplates]);

  const materialIssues = useMemo(() => {
    return (selectedTemplate?.material_requirements || []).flatMap((requirement) => {
      const count = materials[requirement.key]?.length || 0;
      if (count < requirement.min_count) return [`${requirement.label}至少需要 ${requirement.min_count} 个素材`];
      if (count > requirement.max_count) return [`${requirement.label}最多选择 ${requirement.max_count} 个素材`];
      return [];
    });
  }, [materials, selectedTemplate]);

  const contentIssues = useMemo(() => {
    return (selectedTemplate?.content_fields || []).flatMap((field) => {
      const value = String(variables[field.key] || "");
      const trimmed = value.trim();
      if (field.required && !trimmed) return [`请填写${field.label}`];
      if (!trimmed) return [];
      if (field.min_length && trimmed.length < field.min_length) {
        return [`${field.label}至少需要 ${field.min_length} 个字符`];
      }
      if (field.max_length && trimmed.length > field.max_length) {
        return [`${field.label}最多填写 ${field.max_length} 个字符`];
      }
      if (field.input_type === "select" && !(field.options || []).some((option) => option.value === value)) {
        return [`请选择有效的${field.label}`];
      }
      return [];
    });
  }, [selectedTemplate, variables]);
  const variablesReady = Boolean(selectedTemplate) && contentIssues.length === 0;
  const subtitleReplacementIssues = selectedTemplate?.runtime_capabilities?.subtitle_replacements
    ? subtitleReplacementStatus.issues
    : [];
  const hasUnsavedSubtitleReplacements = Boolean(
    selectedTemplate?.runtime_capabilities?.subtitle_replacements
    && subtitleReplacementStatus.hasUnsaved
  );
  const canSubmit = variablesReady
    && materialIssues.length === 0
    && subtitleReplacementIssues.length === 0
    && !hasUnsavedSubtitleReplacements
    && Boolean(finalScript.trim())
    && !submitting;

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = null;
  }, []);

  useEffect(() => {
    if (!selectedTemplate || previousTemplateIdRef.current === selectedTemplate.id) return;

    const previousTemplateId = previousTemplateIdRef.current;
    previousTemplateIdRef.current = selectedTemplate.id;
    setVariables(templateContentDefaults(selectedTemplate));
    setMaterials({});
    setScriptCandidates([]);
    setSelectedCandidateId("");
    setFinalScript("");
    setSubtitleStyle(cloneDefaultSubtitleStyle());
    setSubtitleStyleDialogOpen(false);
    setRewritingCandidateId("");
    setGenerateCount(templateDefaultBatchSize(selectedTemplate));
    setError("");

    if (previousTemplateId) {
      stopPolling();
      localStorage.removeItem(taskStorageKey);
      setTask(null);
      setSubmitting(false);
    }
  }, [selectedTemplate?.id, stopPolling, taskStorageKey]);

  useEffect(() => {
    if (!subtitleStyleDialogOpen || !selectedTemplate) return undefined;

    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setSubtitleStyleDialogOpen(false);
    };

    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [selectedTemplate, subtitleStyleDialogOpen]);

  useEffect(() => {
    if (!selectedTemplate && subtitleStyleDialogOpen) setSubtitleStyleDialogOpen(false);
  }, [selectedTemplate, subtitleStyleDialogOpen]);

  const pollTask = useCallback(
    async (taskId) => {
      try {
        const nextTask = await apiJson(
          `/api/template-production/tasks/${taskId}`,
          { silentError: true },
          backendBaseUrl
        );
        setTask(nextTask);
        setSubmitting(!FINAL_STATUSES.has(nextTask.status));
        if (!FINAL_STATUSES.has(nextTask.status)) {
          pollRef.current = setTimeout(() => pollTask(taskId), 1500);
        }
      } catch (err) {
        if (err?.status === 404) {
          localStorage.removeItem(taskStorageKey);
          setTask(null);
          setError("上一次任务已失效，可能是后端服务已经重启。");
        } else {
          setError(err.message || "读取模板任务失败");
        }
        setSubmitting(false);
      }
    },
    [backendBaseUrl, taskStorageKey]
  );

  useEffect(() => {
    const storedTaskId = localStorage.getItem(taskStorageKey);
    if (storedTaskId) pollTask(storedTaskId);
    return stopPolling;
  }, [pollTask, stopPolling, taskStorageKey]);

  const switchTemplate = useCallback(
    (nextTemplate) => {
      if (submitting) return;
      setTemplateId(nextTemplate.id);
    },
    [submitting]
  );

  const importTemplate = useCallback(async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 128 * 1024) {
      setTemplateError("模板 JSON 不能超过 128 KiB");
      return;
    }

    setImportingTemplate(true);
    setTemplateError("");
    const knownIds = new Set(templates.map((item) => item.id));
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const data = await apiJson(
        "/api/template-production/templates/import",
        { method: "POST", body: form, silentError: true },
        backendBaseUrl
      );
      const importedId = data.template?.id || data.id || data.template_id || "";
      const nextTemplates = await loadTemplates({ selectId: importedId });
      if (!nextTemplates) return;
      const inferredTemplate = importedId
        ? nextTemplates.find((item) => item.id === importedId)
        : nextTemplates.find((item) => !knownIds.has(item.id));
      if (inferredTemplate) setTemplateId(inferredTemplate.id);
      showSuccess(`模板“${inferredTemplate?.name || importedId || file.name}”已导入`);
    } catch (err) {
      setTemplateError(err.message || "导入模板失败");
    } finally {
      setImportingTemplate(false);
    }
  }, [backendBaseUrl, loadTemplates, showSuccess, templates]);

  const exportTemplate = useCallback(async () => {
    if (!selectedTemplate) return;
    setExportingTemplate(true);
    setTemplateError("");
    try {
      const response = await apiFetch(
        `/api/template-production/templates/${encodeURIComponent(selectedTemplate.id)}/export`,
        undefined,
        backendBaseUrl
      );
      if (!response.ok) {
        // 导出接口返回二进制文件，无法使用 apiJson，这里就地解析错误 detail
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || data.message || "导出模板失败");
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = exportFilename(response, selectedTemplate.id);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      showSuccess(`模板“${selectedTemplate.name}”已导出`);
    } catch (err) {
      setTemplateError(err.message || "导出模板失败");
    } finally {
      setExportingTemplate(false);
    }
  }, [backendBaseUrl, selectedTemplate, showSuccess]);

  const addMaterialFiles = useCallback((requirement, fileList) => {
    const acceptedPrefix = requirement.media_type === "image" ? "image/" : "video/";
    const selected = Array.from(fileList || []).filter((file) => file.type.startsWith(acceptedPrefix));
    if (!selected.length) return;
    setMaterials((current) => {
      const existing = current[requirement.key] || [];
      const available = Math.max(0, requirement.max_count - existing.length);
      const additions = selected.slice(0, available).map((file) => ({ id: makeId(), file }));
      return { ...current, [requirement.key]: [...existing, ...additions] };
    });
    setError("");
  }, []);

  const removeMaterial = useCallback((requirementId, itemId) => {
    setMaterials((current) => ({
      ...current,
      [requirementId]: (current[requirementId] || []).filter((item) => item.id !== itemId),
    }));
  }, []);

  const generateAiScripts = useCallback(async () => {
    setError("");
    if (!variablesReady) {
      setError(contentIssues[0] || "请先填写模板的必填信息。");
      return;
    }
    setGeneratingScripts(true);
    try {
      const materialContext = Object.fromEntries(
        selectedTemplate.material_requirements.map((requirement) => [
          requirement.key,
          materials[requirement.key]?.length || 0,
        ])
      );
      const data = await apiJson(
        "/api/template-production/scripts/generate",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            template_id: templateId,
            variables,
            count: defaultCandidateCount,
            material_context: materialContext,
          }),
          silentError: true,
        },
        backendBaseUrl
      );
      const nextScripts = Array.isArray(data.scripts) ? data.scripts : [];
      if (!nextScripts.length) throw new Error("LLM 没有返回可用候选文案");
      const nextCandidates = nextScripts.map((content) => ({ id: makeId(), content }));
      setScriptCandidates(nextCandidates);
      setSelectedCandidateId(nextCandidates[0].id);
      setFinalScript(nextCandidates[0].content);
      showSuccess(`已生成 ${nextCandidates.length} 条候选文案，已选择第 1 条。`);
    } catch (err) {
      setError(err.message || "AI 文案生成失败");
    } finally {
      setGeneratingScripts(false);
    }
  }, [
    backendBaseUrl,
    contentIssues,
    defaultCandidateCount,
    materials,
    selectedTemplate,
    showSuccess,
    templateId,
    variables,
    variablesReady,
  ]);

  const selectCandidate = useCallback((candidate) => {
    setSelectedCandidateId(candidate.id);
    setFinalScript(candidate.content);
    setError("");
    showSuccess("已将候选文案填入最终文案。");
  }, []);

  const updateSubtitleStyle = useCallback((field, value) => {
    setSubtitleStyle((current) => ({ ...current, [field]: value }));
    setError("");
  }, []);

  const resetSubtitleStyle = useCallback(() => {
    setSubtitleStyle(cloneDefaultSubtitleStyle());
    setError("");
  }, []);

  const rewriteCandidate = useCallback(async (candidate) => {
    setRewritingCandidateId(candidate.id);
    setError("");
    try {
      const materialContext = Object.fromEntries(
        selectedTemplate.material_requirements.map((requirement) => [
          requirement.key,
          materials[requirement.key]?.length || 0,
        ])
      );
      const data = await apiJson(
        "/api/template-production/scripts/rewrite",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            template_id: templateId,
            variables,
            original_script: candidate.content,
            material_context: materialContext,
          }),
          silentError: true,
        },
        backendBaseUrl
      );
      const nextContent = String(data.script || "").trim();
      if (!nextContent) throw new Error("LLM 没有返回可用候选文案");
      setScriptCandidates((current) =>
        current.map((item) => (item.id === candidate.id ? { ...item, content: nextContent } : item))
      );
      if (selectedCandidateId === candidate.id && finalScript.trim() === candidate.content.trim()) {
        setFinalScript(nextContent);
      }
      showSuccess("候选文案已重写。");
    } catch (err) {
      setError(err.message || "候选文案重写失败");
    } finally {
      setRewritingCandidateId("");
    }
  }, [backendBaseUrl, finalScript, materials, selectedCandidateId, selectedTemplate, showSuccess, templateId, variables]);

  const submitTask = useCallback(async () => {
    setError("");
    if (!canSubmit) {
      setError(
        contentIssues[0]
        || subtitleReplacementIssues[0]
        || materialIssues[0]
        || (hasUnsavedSubtitleReplacements ? "请先保存当前用户的敏感词替换规则。" : "请完善素材和文案后再生成。")
      );
      return;
    }

    const cleanScript = finalScript.trim();
    if (!cleanScript) {
      setError("请填写最终文案。");
      return;
    }

    stopPolling();
    setSubmitting(true);
    setTask({ status: "pending", progress: 0, message: "正在上传素材", items: [] });
    try {
      const form = new FormData();
      const manifest = [];
      let fileIndex = 0;
      selectedTemplate.material_requirements.forEach((requirement) => {
        (materials[requirement.key] || []).forEach((item) => {
          form.append("materials", item.file, item.file.name);
          manifest.push({
            requirement_id: requirement.key,
            file_index: fileIndex,
            media_type: requirement.media_type,
            name: item.file.name,
          });
          fileIndex += 1;
        });
      });
      form.append("template_id", templateId);
      form.append("scripts", JSON.stringify([cleanScript]));
      form.append("generate_count", String(generateCount));
      form.append("video_config", JSON.stringify({ subtitle_style: subtitleStyle }));
      form.append("material_manifest", JSON.stringify(manifest));
      if (selectedBgmId) form.append("bgm_id", selectedBgmId);

      const data = await apiJson(
        "/api/template-production/tasks",
        { method: "POST", body: form, silentError: true },
        backendBaseUrl
      );
      localStorage.setItem(taskStorageKey, data.task_id);
      pollTask(data.task_id);
    } catch (err) {
      setError(err.message || "创建模板量产任务失败");
      setSubmitting(false);
      setTask(null);
    }
  }, [
    backendBaseUrl,
    canSubmit,
    contentIssues,
    generateCount,
    hasUnsavedSubtitleReplacements,
    materialIssues,
    materials,
    pollTask,
    finalScript,
    selectedBgmId,
    selectedTemplate,
    stopPolling,
    subtitleStyle,
    subtitleReplacementIssues,
    taskStorageKey,
    templateId,
  ]);

  return (
    <section className="workspace-panel template-production-panel" aria-label="模板量产工作区">
      <div className="panel-heading">
        <div className="template-heading-actions">
          {currentUser?.is_admin ? <>
            <input ref={templateFileInputRef} hidden type="file" accept="application/json,.json" onChange={importTemplate} />
            <Button type="button" variant="outlined" size="small" onClick={() => templateFileInputRef.current?.click()} disabled={submitting || importingTemplate} title="导入共享模板 JSON"
              startIcon={<Icon name={importingTemplate ? "loading" : "upload"} size={15} />}>
              {importingTemplate ? "导入中" : "导入模板"}
            </Button>
          </> : null}
          <Button
            type="button"
            variant="outlined"
            size="small"
            onClick={exportTemplate}
            disabled={!selectedTemplate || exportingTemplate}
            title="导出当前模板 JSON"
            startIcon={<Icon name={exportingTemplate ? "loading" : "download"} size={15} />}
          >
            {exportingTemplate ? "导出中" : "导出模板"}
          </Button>
          <Chip
            size="small"
            icon={
              <Icon
                name={
                  templatesLoading || submitting
                    ? "loading"
                    : task?.status === "completed"
                      ? "check"
                      : task?.status === "partial_failed"
                        ? "alert"
                        : "template"
                }
                size={14}
              />
            }
            label={
              templatesLoading
                ? "加载模板"
                : task
                  ? statusLabel(task.status)
                  : !selectedTemplate
                    ? "暂无模板"
                    : canSubmit
                      ? "可以生成"
                      : "准备素材"
            }
            sx={{
              backgroundColor: statusChipColors[task?.status || (canSubmit ? "ready" : "pending")]?.bg || "#f3f1e9",
              color: statusChipColors[task?.status || (canSubmit ? "ready" : "pending")]?.fg || "#68645b",
              fontWeight: 600,
              "& .vf-icon": { color: statusChipColors[task?.status || (canSubmit ? "ready" : "pending")]?.fg || "#68645b" },
            }}
          />
        </div>
      </div>

      <div
        className="template-selector"
        role={templates.length ? "tablist" : "status"}
        aria-label="模板选择"
        aria-busy={templatesLoading}
      >
        {templatesLoading && !templates.length ? (
          <div className="template-empty-state"><Icon name="loading" size={20} />正在加载模板...</div>
        ) : templateError && !templates.length ? (
          <div className="template-empty-state is-error">
            <Icon name="alert" size={20} />
            <span>{templateError}</span>
            <Button variant="outlined" size="small" type="button" onClick={() => loadTemplates()}
              startIcon={<Icon name="refresh" size={14} />}>
              重新加载
            </Button>
          </div>
        ) : !templates.length ? (
          <div className="template-empty-state">
            <Icon name="template" size={20} />
            <span>还没有可用模板，请导入模板 JSON。</span>
          </div>
        ) : templates.map((item) => (
          <Button
            className={`template-choice ${item.id === templateId ? "is-active" : ""}`}
            key={item.id}
            onClick={() => switchTemplate(item)}
            role="tab"
            type="button"
            variant="outlined"
            color="inherit"
            aria-selected={item.id === templateId}
            disabled={submitting}
            sx={{ justifyContent: "flex-start", textTransform: "none" }}
          >
            <span className="template-choice-icon"><Icon name="template" size={20} /></span>
            <span>
              <strong>{item.name}</strong>
              <small>{item.description || "暂无模板说明"}</small>
            </span>
            {item.id === templateId ? <Icon name="check" size={17} /> : null}
          </Button>
        ))}
      </div>

      {templateError && templates.length ? <div className="form-alert failed">{templateError}</div> : null}

      {selectedTemplate ? <div className="template-production-grid">
        <div className="template-production-column">
          <section className="template-work-section" aria-labelledby="template-info-title">
            <div className="template-section-heading">
              <span><Icon name="edit" size={17} /></span>
              <div><strong id="template-info-title">内容信息</strong><small>用于生成匹配当前模板的口播文案</small></div>
            </div>
            <div className="field-grid template-variable-grid">
              {selectedTemplate.content_fields.map((field) => (
                <ContentFieldControl
                  field={field}
                  key={field.key}
                  value={variables[field.key] || ""}
                  onChange={(value) => setVariables((current) => ({ ...current, [field.key]: value }))}
                />
              ))}
            </div>
          </section>

          <section className="template-work-section" aria-labelledby="template-material-title">
            <div className="template-section-heading">
              <span><Icon name="upload" size={17} /></span>
              <div><strong id="template-material-title">上传素材</strong><small>素材会在每条成片中重新编排</small></div>
            </div>
            <div className="material-requirement-list">
              {selectedTemplate.material_requirements.map((requirement) => {
                const items = materials[requirement.key] || [];
                return (
                  <div className="material-requirement" key={requirement.key}>
                    <div className="material-requirement-heading">
                      <div>
                        <strong>{requirement.label}</strong>
                        {requirement.description ? <small>{requirement.description}</small> : null}
                        <span>
                          {requirement.media_type === "image" ? "图片" : "视频"} · {requirement.min_count > 0 ? `${requirement.min_count}-${requirement.max_count} 个` : `选填，最多 ${requirement.max_count} 个`}
                        </span>
                      </div>
                      <Button component="label" variant="outlined" size="small">
                        <Icon name="upload" size={15} />选择文件
                        <input
                          hidden
                          multiple
                          type="file"
                          accept={requirement.media_type === "image" ? "image/*" : "video/*"}
                          onChange={(event) => {
                            addMaterialFiles(requirement, event.target.files);
                            event.target.value = "";
                          }}
                        />
                      </Button>
                    </div>
                    {items.length ? (
                      <div className="material-file-list">
                        {items.map((item, index) => (
                          <div className="material-preview-card" key={item.id}>
                            <MaterialPreview
                              file={item.file}
                              mediaType={requirement.media_type}
                              label={`第 ${index + 1} 个${requirement.media_type === "image" ? "图片" : "视频"}素材`}
                            />
                            <div className="material-preview-footer">
                              <span><Icon name={requirement.media_type} size={14} />{formatFileSize(item.file.size)}</span>
                              <IconButton
                                type="button"
                                title={`移除第 ${index + 1} 个素材`}
                                aria-label={`移除第 ${index + 1} 个素材`}
                                onClick={() => removeMaterial(requirement.key, item.id)}
                                size="small"
                              >
                                <Icon name="x" size={15} />
                              </IconButton>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="material-empty">尚未选择{requirement.media_type === "image" ? "图片" : "视频"}</div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        <div className="template-production-column">
          <section className="template-work-section" aria-labelledby="template-script-title">
            <div className="template-section-heading with-actions">
              <span><Icon name="sparkles" size={17} /></span>
              <div><strong id="template-script-title">口播文案</strong><small>从候选中选择，再编辑最终文案</small></div>
              <Button type="button" variant="contained" size="small" onClick={generateAiScripts} disabled={generatingScripts}
                startIcon={<Icon name={generatingScripts ? "loading" : "sparkles"} size={15} />}>
                {generatingScripts ? "生成中" : "AI 生成"}
              </Button>
            </div>
            {scriptCandidates.length ? (
              <div className="script-candidate-grid" aria-label="AI 候选文案">
                {scriptCandidates.map((candidate, index) => (
                  <article
                    className={`script-candidate-card ${candidate.id === selectedCandidateId ? "is-selected" : ""}`}
                    key={candidate.id}
                  >
                    <div className="script-candidate-heading">
                      <span>候选 {index + 1}</span>
                      {selectedTemplate.runtime_capabilities?.script_rewrite ? (
                        <IconButton
                          type="button"
                          title={`重写候选 ${index + 1}`}
                          aria-label={`重写候选 ${index + 1}`}
                          onClick={() => rewriteCandidate(candidate)}
                          disabled={Boolean(rewritingCandidateId)}
                          size="small"
                        >
                          <Icon
                            name={rewritingCandidateId === candidate.id ? "loading" : "refresh"}
                            size={15}
                            data-loading={rewritingCandidateId === candidate.id ? "true" : undefined}
                          />
                        </IconButton>
                      ) : null}
                    </div>
                    <Button
                      className="script-candidate-select"
                      type="button"
                      variant="text"
                      onClick={() => selectCandidate(candidate)}
                      aria-pressed={candidate.id === selectedCandidateId}
                      sx={{ display: "block", textAlign: "left", textTransform: "none" }}
                    >
                      <span>{candidate.content}</span>
                      <small>{candidate.id === selectedCandidateId ? <><Icon name="check" size={13} />已选为最终文案</> : "点击选用"}</small>
                    </Button>
                  </article>
                ))}
              </div>
            ) : (
              <div className="script-empty-state">
                <Icon name="sparkles" size={22} />
                <span>填写内容信息后生成 {defaultCandidateCount} 条候选文案。</span>
              </div>
            )}
            <TextField
              className="final-script-field"
              placeholder="选择上方候选，或直接在这里输入最终用于配音和生成视频的文案"
              fullWidth
              multiline
              rows={5}
              value={finalScript}
              placeholder="选择上方候选，或直接在这里输入最终用于配音和生成视频的文案"
              onChange={(event) => {
                setFinalScript(event.target.value);
                setSelectedCandidateId("");
              }}
            />
            <div className="subtitle-style-launcher">
              <div className="subtitle-style-launcher-copy">
                <span className="subtitle-style-launcher-icon"><Icon name="sliders" size={17} /></span>
                <div>
                  <strong>字幕样式</strong>
                  <small>{subtitleStyle.notice_enabled ? "主字幕与小字免责申明" : "主字幕，已隐藏小字免责申明"}</small>
                </div>
              </div>
              <Button
                className="subtitle-style-open"
                type="button"
                variant="outlined"
                size="small"
                onClick={() => setSubtitleStyleDialogOpen(true)}
                disabled={submitting}
                aria-haspopup="dialog"
                aria-expanded={subtitleStyleDialogOpen}
                startIcon={<Icon name="edit" size={15} />}
              >
                编辑样式
              </Button>
            </div>
            <Dialog
              open={subtitleStyleDialogOpen}
              onClose={() => setSubtitleStyleDialogOpen(false)}
              aria-labelledby="subtitle-style-dialog-title"
              maxWidth="lg"
              fullWidth
            >
              <div className="subtitle-style-editor">
              <div className="subtitle-style-heading">
                <div>
                  <strong id="subtitle-style-dialog-title">字幕样式</strong>
                  <small>预览使用固定示例内容；成片仍按最终文案、分句和替换规则填充字幕</small>
                </div>
                <div className="subtitle-style-heading-actions">
                  <Button
                    className="subtitle-style-reset"
                    type="button"
                    variant="outlined"
                    size="small"
                    onClick={resetSubtitleStyle}
                    title="恢复当前默认字幕样式"
                    startIcon={<Icon name="refresh" size={14} />}
                  >
                    恢复默认
                  </Button>
                  <IconButton
                    className="subtitle-style-close"
                    type="button"
                    onClick={() => setSubtitleStyleDialogOpen(false)}
                    title="关闭字幕样式编辑"
                    aria-label="关闭字幕样式编辑"
                    size="small"
                  >
                    <Icon name="x" size={17} />
                  </IconButton>
                </div>
              </div>
              <div className="subtitle-style-layout">
                <SubtitleStylePreview style={subtitleStyle} />
                <div className="subtitle-style-controls">
                  <section className="subtitle-style-section" aria-labelledby="subtitle-main-style-title">
                    <div className="subtitle-style-section-heading">
                      <strong id="subtitle-main-style-title">主字幕</strong>
                      <span>仅调整样式</span>
                    </div>
                    <div className="subtitle-style-field-grid">
                      <TextField
                        className="field"
                        label="字体"
                        fullWidth
                        size="small"
                        select
                        value={subtitleStyle.font_family}
                        onChange={(event) => updateSubtitleStyle("font_family", event.target.value)}
                      >
                        <MenuItem value="Microsoft YaHei">微软雅黑</MenuItem>
                        <MenuItem value="SimHei">黑体</MenuItem>
                        <MenuItem value="SimSun">宋体</MenuItem>
                        <MenuItem value="KaiTi">楷体</MenuItem>
                      </TextField>
                      <TextField
                        className="field"
                        label="对齐"
                        fullWidth
                        size="small"
                        select
                        value={subtitleStyle.alignment}
                        onChange={(event) => updateSubtitleStyle("alignment", event.target.value)}
                      >
                        <MenuItem value="left">左对齐</MenuItem>
                        <MenuItem value="center">居中</MenuItem>
                        <MenuItem value="right">右对齐</MenuItem>
                      </TextField>
                    </div>
                    <div className="subtitle-style-slider-grid">
                      <div className="field">
                        <span className="field-label">字号 {subtitleStyle.font_size}</span>
                        <Slider size="small" min={36} max={108} value={subtitleStyle.font_size} onChange={(_, value) => updateSubtitleStyle("font_size", value)} />
                      </div>
                      <div className="field">
                        <span className="field-label">描边 {subtitleStyle.outline_width}</span>
                        <Slider size="small" min={0} max={12} value={subtitleStyle.outline_width} onChange={(_, value) => updateSubtitleStyle("outline_width", value)} />
                      </div>
                      <div className="field">
                        <span className="field-label">底部边距 {subtitleStyle.bottom_margin}</span>
                        <Slider size="small" min={80} max={480} step={5} value={subtitleStyle.bottom_margin} onChange={(_, value) => updateSubtitleStyle("bottom_margin", value)} />
                      </div>
                    </div>
                    <div className="subtitle-style-swatch-grid">
                      <label><span>文字</span><input type="color" value={subtitleStyle.color} onChange={(event) => updateSubtitleStyle("color", event.target.value)} /></label>
                      <label><span>描边</span><input type="color" value={subtitleStyle.outline_color} onChange={(event) => updateSubtitleStyle("outline_color", event.target.value)} /></label>
                    </div>
                  </section>
                  <section className="subtitle-style-section" aria-labelledby="subtitle-notice-style-title">
                    <div className="subtitle-style-section-heading">
                      <strong id="subtitle-notice-style-title">小字免责申明</strong>
                      <label className="subtitle-notice-toggle">
                        <Switch
                          size="small"
                          checked={subtitleStyle.notice_enabled}
                          onChange={(event) => updateSubtitleStyle("notice_enabled", event.target.checked)}
                        />
                        <em>{subtitleStyle.notice_enabled ? "显示" : "不显示"}</em>
                      </label>
                    </div>
                    {subtitleStyle.notice_enabled ? (
                      <>
                        <TextField
                          className="field subtitle-notice-text-field"
                          label="申明内容"
                          fullWidth
                          size="small"
                          multiline
                          rows={3}
                          slotProps={{ htmlInput: { maxLength: 120 } }}
                          value={subtitleStyle.notice_text}
                          onChange={(event) => updateSubtitleStyle("notice_text", event.target.value)}
                        />
                        <div className="subtitle-style-slider-grid">
                          <div className="field">
                            <span className="field-label">字号 {subtitleStyle.notice_font_size}</span>
                            <Slider size="small" min={18} max={58} value={subtitleStyle.notice_font_size} onChange={(_, value) => updateSubtitleStyle("notice_font_size", value)} />
                          </div>
                          <div className="field">
                            <span className="field-label">描边 {subtitleStyle.notice_outline_width}</span>
                            <Slider size="small" min={0} max={6} value={subtitleStyle.notice_outline_width} onChange={(_, value) => updateSubtitleStyle("notice_outline_width", value)} />
                          </div>
                          <div className="field">
                            <span className="field-label">顶部边距 {subtitleStyle.notice_top_margin}</span>
                            <Slider size="small" min={30} max={260} value={subtitleStyle.notice_top_margin} onChange={(_, value) => updateSubtitleStyle("notice_top_margin", value)} />
                          </div>
                        </div>
                        <div className="subtitle-style-swatch-grid">
                          <label><span>文字</span><input type="color" value={subtitleStyle.notice_color} onChange={(event) => updateSubtitleStyle("notice_color", event.target.value)} /></label>
                          <label><span>描边</span><input type="color" value={subtitleStyle.notice_outline_color} onChange={(event) => updateSubtitleStyle("notice_outline_color", event.target.value)} /></label>
                        </div>
                      </>
                    ) : (
                      <div className="subtitle-notice-hidden">小字免责申明不会显示在本次生成的成片中。</div>
                    )}
                  </section>
                </div>
              </div>
                  </div>
                  <div className="subtitle-style-modal-footer">
                    <Button
                      className="subtitle-style-confirm"
                      type="button"
                      variant="contained"
                      onClick={() => setSubtitleStyleDialogOpen(false)}
                      title="确认当前字幕样式"
                      startIcon={<Icon name="check" size={15} />}
                    >
                      确认
                    </Button>
                  </div>
            </Dialog>
            {selectedTemplate.runtime_capabilities?.subtitle_replacements ? (
              <SubtitleReplacementManager
                currentUserId={currentUser?.id}
                onStatusChange={setSubtitleReplacementStatus}
              />
            ) : null}
          </section>

          <BgmManager
            currentUserId={currentUser?.id}
            selectedBgmId={selectedBgmId}
            onSelectionChange={setSelectedBgmId}
            disabled={submitting}
            idPrefix="template"
          />

          {error ? <div className="form-alert failed">{error}</div> : null}
          {materialIssues.length && finalScript.trim() ? <div className="template-inline-warning">{materialIssues[0]}</div> : null}

          <div className="template-submit-row">
            <TextField
              id="template-generate-count"
              className="template-submit-count"
              label="生成数量"
              size="small"
              type="number"
              slotProps={{ htmlInput: { min: 1, max: maxBatchSize } }}
              value={generateCount}
              onChange={(event) => setGenerateCount(Math.max(1, Math.min(maxBatchSize, Number(event.target.value) || 1)))}
            />
            <Button className="template-submit-action" type="button" variant="contained" size="large" onClick={submitTask} disabled={!canSubmit}
              startIcon={<Icon name={submitting ? "loading" : "wand"} size={17} />}>
              {submitting ? "正在批量生成" : `生成 ${generateCount} 条视频`}
            </Button>
          </div>
        </div>
      </div> : null}

      {task ? (
        <section className="template-results" aria-labelledby="template-results-title">
          <div className="template-results-heading">
            <div>
              <Typography variant="kicker" component="span" className="section-kicker">Output</Typography>
              <h3 id="template-results-title">生成结果</h3>
              <p>{task.message}</p>
            </div>
            {task.zip_url ? (
              <ProtectedDownloadButton
                path={task.zip_url}
                filename="template_videos.zip"
                backendBaseUrl={backendBaseUrl}
              >
                <Icon name="download" size={16} />下载全部
              </ProtectedDownloadButton>
            ) : null}
          </div>
          <LinearProgress
            variant="determinate"
            value={task.progress || 0}
            aria-label={`生成进度 ${task.progress || 0}%`}
            sx={{ mt: 1.5, mb: 1.5 }}
          />
          <div className="template-result-grid">
            {(task.items || []).map((item) => (
              <article className={`template-result-item ${item.status}`} key={item.id || item.index}>
                <div className="template-result-media">
                  {item.video_url ? (
                    <ProtectedMedia
                      path={item.video_url}
                      kind="video"
                      backendBaseUrl={backendBaseUrl}
                    />
                  ) : (
                    <div className="template-result-placeholder"><Icon name={item.status === "failed" ? "alert" : "loading"} size={22} /></div>
                  )}
                </div>
                <div className="template-result-copy">
                  <div>
                    <strong>视频 {item.index}</strong>
                    <Chip
                      size="small"
                      label={statusLabel(item.status)}
                      sx={{
                        backgroundColor: statusChipColors[item.status]?.bg || "#f3f1e9",
                        color: statusChipColors[item.status]?.fg || "#68645b",
                        fontWeight: 600,
                      }}
                    />
                  </div>
                  <p>{item.script}</p>
                  {item.error ? <small className="result-error">{item.error}</small> : null}
                  {item.video_url ? (
                    <ProtectedDownloadButton
                      path={item.video_url}
                      filename={`template_video_${String(item.index).padStart(3, "0")}.mp4`}
                      backendBaseUrl={backendBaseUrl}
                    >
                      <Icon name="download" size={14} />下载视频
                    </ProtectedDownloadButton>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}
