import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";
import { apiFetch, resolveBackendAssetUrl, useBackendBaseUrl } from "../lib/backend";

const FINAL_STATUSES = new Set(["completed", "failed"]);
const MAX_SUBTITLE_REPLACEMENTS = 30;
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

async function responseError(response, fallback) {
  const data = await response.json().catch(() => ({}));
  return data.detail || data.message || fallback || `HTTP ${response.status}`;
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
    failed: "失败",
  }[status] || "准备中";
}

function formatFileSize(size) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
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
  const inputId = `template-variable-${field.key}`;
  const sharedProps = {
    className: "control",
    id: inputId,
    value,
    required: Boolean(field.required),
    onChange: (event) => onChange(event.target.value),
  };

  let control;
  if (field.input_type === "textarea") {
    control = (
      <textarea
        {...sharedProps}
        minLength={field.min_length ?? undefined}
        maxLength={field.max_length ?? undefined}
        placeholder={field.placeholder || "请输入内容"}
        rows={4}
      />
    );
  } else if (field.input_type === "select") {
    control = (
      <select {...sharedProps}>
        <option value="">{field.placeholder || `请选择${field.label}`}</option>
        {(field.options || []).map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    );
  } else {
    control = (
      <input
        {...sharedProps}
        type="text"
        minLength={field.min_length ?? undefined}
        maxLength={field.max_length ?? undefined}
        placeholder={field.placeholder || "请输入内容"}
      />
    );
  }

  return (
    <label className="field" htmlFor={inputId}>
      <span className="field-label">{field.label}{field.required ? " *" : ""}</span>
      {control}
      {field.help_text ? <small className="field-help">{field.help_text}</small> : null}
    </label>
  );
}

export default function TemplateProduction({ currentUser }) {
  const backendBaseUrl = useBackendBaseUrl();
  const [templates, setTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templateError, setTemplateError] = useState("");
  const [templateNotice, setTemplateNotice] = useState("");
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
  const [subtitleReplacements, setSubtitleReplacements] = useState([]);
  const [subtitleReplacementsLoading, setSubtitleReplacementsLoading] = useState(true);
  const [subtitleReplacementError, setSubtitleReplacementError] = useState("");
  const [subtitleReplacementNotice, setSubtitleReplacementNotice] = useState("");
  const [savingSubtitleReplacementIds, setSavingSubtitleReplacementIds] = useState(() => new Set());
  const [dirtySubtitleReplacementIds, setDirtySubtitleReplacementIds] = useState(() => new Set());
  const [savedSubtitleReplacementIds, setSavedSubtitleReplacementIds] = useState(() => new Set());
  const [subtitleReplacementPendingDelete, setSubtitleReplacementPendingDelete] = useState(null);
  const [rewritingCandidateId, setRewritingCandidateId] = useState("");
  const [generateCount, setGenerateCount] = useState(5);
  const [generatingScripts, setGeneratingScripts] = useState(false);
  const [task, setTask] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [bgmTracks, setBgmTracks] = useState([]);
  const [selectedBgmId, setSelectedBgmId] = useState("");
  const [bgmLoading, setBgmLoading] = useState(true);
  const [bgmError, setBgmError] = useState("");
  const [bgmNotice, setBgmNotice] = useState("");
  const [uploadingBgm, setUploadingBgm] = useState(false);
  const [deletingBgmId, setDeletingBgmId] = useState(null);
  const [pendingBgmDelete, setPendingBgmDelete] = useState(null);
  const pollRef = useRef(null);
  const templateFileInputRef = useRef(null);
  const bgmFileInputRef = useRef(null);
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
      const response = await apiFetch(
        "/api/template-production/templates",
        signal ? { signal } : undefined,
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "读取模板列表失败"));
      const data = await response.json();
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

  const loadSubtitleReplacements = useCallback(async ({ signal } = {}) => {
    setSubtitleReplacementsLoading(true);
    setSubtitleReplacementError("");
    setSubtitleReplacementNotice("");
    try {
      const response = await apiFetch(
        "/api/template-production/subtitle-replacements",
        signal ? { signal } : undefined,
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "读取全局敏感词替换失败"));
      const data = await response.json();
      setSubtitleReplacements(Array.isArray(data.replacements) ? data.replacements : []);
      setDirtySubtitleReplacementIds(new Set());
      setSavedSubtitleReplacementIds(new Set());
    } catch (err) {
      if (err?.name !== "AbortError") {
        setSubtitleReplacementError(err.message || "读取全局敏感词替换失败");
      }
    } finally {
      if (!signal?.aborted) setSubtitleReplacementsLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    loadSubtitleReplacements({ signal: controller.signal });
    return () => controller.abort();
  }, [currentUser?.id, loadSubtitleReplacements]);

  const loadBgmTracks = useCallback(async ({ signal } = {}) => {
    setBgmLoading(true);
    setBgmError("");
    setBgmNotice("");
    try {
      const response = await apiFetch(
        "/api/template-production/bgm",
        signal ? { signal } : undefined,
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "读取背景音乐列表失败"));
      const data = await response.json();
      const nextTracks = Array.isArray(data.bgm_tracks) ? data.bgm_tracks : [];
      setBgmTracks(nextTracks);
      setSelectedBgmId((currentId) => {
        if (currentId && nextTracks.some((track) => track.id === currentId)) return currentId;
        return "";
      });
    } catch (err) {
      if (err?.name !== "AbortError") {
        setBgmError(err.message || "读取背景音乐列表失败");
      }
    } finally {
      if (!signal?.aborted) setBgmLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    loadBgmTracks({ signal: controller.signal });
    return () => controller.abort();
  }, [currentUser?.id, loadBgmTracks]);

  const uploadBgm = useCallback(async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setUploadingBgm(true);
    setBgmError("");
    setBgmNotice("");
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const response = await apiFetch(
        "/api/template-production/bgm",
        { method: "POST", body: form },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "上传背景音乐失败"));
      const data = await response.json();
      const track = data.bgm_track;
      setBgmTracks((current) => [...current, track]);
      setSelectedBgmId(track.id);
      setBgmNotice(`已上传背景音乐“${track.name}”。`);
    } catch (err) {
      setBgmError(err.message || "上传背景音乐失败");
    } finally {
      setUploadingBgm(false);
    }
  }, [backendBaseUrl]);

  const requestBgmDelete = useCallback((track) => {
    if (track) setPendingBgmDelete(track);
  }, []);

  const confirmBgmDelete = useCallback(async () => {
    if (!pendingBgmDelete) return;
    const trackId = pendingBgmDelete.id;
    setDeletingBgmId(trackId);
    setBgmError("");
    setBgmNotice("");
    try {
      const response = await apiFetch(
        `/api/template-production/bgm/${encodeURIComponent(trackId)}`,
        { method: "DELETE" },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "删除背景音乐失败"));
      setBgmTracks((current) => current.filter((track) => track.id !== trackId));
      setSelectedBgmId((current) => (current === trackId ? "" : current));
      setBgmNotice("背景音乐已删除。");
      setPendingBgmDelete(null);
    } catch (err) {
      setBgmError(err.message || "删除背景音乐失败");
    } finally {
      setDeletingBgmId(null);
    }
  }, [backendBaseUrl, pendingBgmDelete]);

  const selectedBgmTrack = useMemo(
    () => bgmTracks.find((track) => track.id === selectedBgmId) || null,
    [bgmTracks, selectedBgmId]
  );

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
  const subtitleReplacementIssues = useMemo(() => {
    if (!selectedTemplate?.runtime_capabilities?.subtitle_replacements) return [];
    const issues = [];
    const seenSources = new Set();
    subtitleReplacements.forEach((item, index) => {
      const source = item.source.trim();
      const replacement = item.replacement.trim();
      if (!source || !replacement) {
        issues.push(`第 ${index + 1} 条字幕替换需要填写原词和替换词`);
      } else if (source === replacement) {
        issues.push(`第 ${index + 1} 条字幕替换的原词和替换词不能相同`);
      } else if (seenSources.has(source)) {
        issues.push(`字幕原词“${source}”重复添加`);
      }
      if (source) seenSources.add(source);
    });
    return issues;
  }, [selectedTemplate, subtitleReplacements]);
  const hasUnsavedSubtitleReplacements = dirtySubtitleReplacementIds.size > 0;
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
    setNotice("");

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
        const response = await apiFetch(`/api/template-production/tasks/${taskId}`, undefined, backendBaseUrl);
        if (response.status === 404) {
          localStorage.removeItem(taskStorageKey);
          setTask(null);
          setError("上一次任务已失效，可能是后端服务已经重启。");
          setSubmitting(false);
          return;
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const nextTask = await response.json();
        setTask(nextTask);
        setSubmitting(!FINAL_STATUSES.has(nextTask.status));
        if (!FINAL_STATUSES.has(nextTask.status)) {
          pollRef.current = setTimeout(() => pollTask(taskId), 1500);
        }
      } catch (err) {
        setError(err.message || "读取模板任务失败");
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
      setTemplateNotice("");
    },
    [submitting]
  );

  const importTemplate = useCallback(async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 128 * 1024) {
      setTemplateError("模板 JSON 不能超过 128 KiB");
      setTemplateNotice("");
      return;
    }

    setImportingTemplate(true);
    setTemplateError("");
    setTemplateNotice("");
    const knownIds = new Set(templates.map((item) => item.id));
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const response = await apiFetch(
        "/api/template-production/templates/import",
        { method: "POST", body: form },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "导入模板失败"));
      const data = await response.json().catch(() => ({}));
      const importedId = data.template?.id || data.id || data.template_id || "";
      const nextTemplates = await loadTemplates({ selectId: importedId });
      if (!nextTemplates) return;
      const inferredTemplate = importedId
        ? nextTemplates.find((item) => item.id === importedId)
        : nextTemplates.find((item) => !knownIds.has(item.id));
      if (inferredTemplate) setTemplateId(inferredTemplate.id);
      setTemplateNotice(`模板“${inferredTemplate?.name || importedId || file.name}”已导入`);
    } catch (err) {
      setTemplateError(err.message || "导入模板失败");
    } finally {
      setImportingTemplate(false);
    }
  }, [backendBaseUrl, loadTemplates, templates]);

  const exportTemplate = useCallback(async () => {
    if (!selectedTemplate) return;
    setExportingTemplate(true);
    setTemplateError("");
    setTemplateNotice("");
    try {
      const response = await apiFetch(
        `/api/template-production/templates/${encodeURIComponent(selectedTemplate.id)}/export`,
        undefined,
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "导出模板失败"));
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = exportFilename(response, selectedTemplate.id);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      setTemplateNotice(`模板“${selectedTemplate.name}”已导出`);
    } catch (err) {
      setTemplateError(err.message || "导出模板失败");
    } finally {
      setExportingTemplate(false);
    }
  }, [backendBaseUrl, selectedTemplate]);

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

  const addSubtitleReplacement = useCallback(() => {
    const id = makeId();
    setSubtitleReplacements((current) => {
      if (current.length >= MAX_SUBTITLE_REPLACEMENTS) return current;
      return [...current, { id, source: "", replacement: "" }];
    });
    setError("");
    setNotice("");
    setSubtitleReplacementNotice("");
  }, []);

  const updateSubtitleReplacement = useCallback((id, field, value) => {
    setSubtitleReplacements((current) => current.map((item) => (
      item.id === id ? { ...item, [field]: value } : item
    )));
    setDirtySubtitleReplacementIds((current) => new Set(current).add(id));
    setSavedSubtitleReplacementIds((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
    setSubtitleReplacementNotice("");
    setError("");
    setNotice("");
  }, []);

  const saveSubtitleReplacement = useCallback(async (id) => {
    const item = subtitleReplacements.find((replacement) => replacement.id === id);
    if (!item) return;
    const source = item.source.trim();
    const replacement = item.replacement.trim();
    if (!source || !replacement || source === replacement) return;

    setSavingSubtitleReplacementIds((current) => new Set(current).add(id));
    setSubtitleReplacementError("");
    try {
      const isDraft = typeof id === "string";
      const response = await apiFetch(
        isDraft
          ? "/api/template-production/subtitle-replacements"
          : `/api/template-production/subtitle-replacements/${id}`,
        {
          method: isDraft ? "POST" : "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source, replacement }),
        },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "保存全局敏感词替换失败"));
      const data = await response.json();
      setSubtitleReplacements((current) => current.map((currentItem) => (
        currentItem.id === id ? data.replacement : currentItem
      )));
      setDirtySubtitleReplacementIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSavedSubtitleReplacementIds((current) => new Set(current).add(data.replacement.id));
      setSubtitleReplacementNotice("全局敏感词替换已保存。");
    } catch (err) {
      setSubtitleReplacementError(err.message || "保存全局敏感词替换失败");
    } finally {
      setSavingSubtitleReplacementIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }, [backendBaseUrl, subtitleReplacements]);

  const removeSubtitleReplacement = useCallback(async (id) => {
    if (typeof id === "string") {
      setSubtitleReplacements((current) => current.filter((item) => item.id !== id));
      setDirtySubtitleReplacementIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSavedSubtitleReplacementIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSubtitleReplacementNotice("全局敏感词替换已删除。");
      return true;
    }

    setSavingSubtitleReplacementIds((current) => new Set(current).add(id));
    setSubtitleReplacementError("");
    try {
      const response = await apiFetch(
        `/api/template-production/subtitle-replacements/${id}`,
        { method: "DELETE" },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "删除全局敏感词替换失败"));
      setSubtitleReplacements((current) => current.filter((item) => item.id !== id));
      setDirtySubtitleReplacementIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSavedSubtitleReplacementIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSubtitleReplacementNotice("全局敏感词替换已删除。");
      return true;
    } catch (err) {
      setSubtitleReplacementError(err.message || "删除全局敏感词替换失败");
      return false;
    } finally {
      setSavingSubtitleReplacementIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }, [backendBaseUrl]);

  const requestSubtitleReplacementDelete = useCallback((id) => {
    const item = subtitleReplacements.find((replacement) => replacement.id === id);
    if (item) setSubtitleReplacementPendingDelete(item);
  }, [subtitleReplacements]);

  const confirmSubtitleReplacementDelete = useCallback(async () => {
    if (!subtitleReplacementPendingDelete) return;
    const deleted = await removeSubtitleReplacement(subtitleReplacementPendingDelete.id);
    if (deleted) setSubtitleReplacementPendingDelete(null);
  }, [removeSubtitleReplacement, subtitleReplacementPendingDelete]);

  const generateAiScripts = useCallback(async () => {
    setError("");
    setNotice("");
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
      const response = await apiFetch(
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
        },
        backendBaseUrl
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      const nextScripts = Array.isArray(data.scripts) ? data.scripts : [];
      if (!nextScripts.length) throw new Error("LLM 没有返回可用候选文案");
      const nextCandidates = nextScripts.map((content) => ({ id: makeId(), content }));
      setScriptCandidates(nextCandidates);
      setSelectedCandidateId(nextCandidates[0].id);
      setFinalScript(nextCandidates[0].content);
      setNotice(`已生成 ${nextCandidates.length} 条候选文案，已选择第 1 条。`);
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
    templateId,
    variables,
    variablesReady,
  ]);

  const selectCandidate = useCallback((candidate) => {
    setSelectedCandidateId(candidate.id);
    setFinalScript(candidate.content);
    setError("");
    setNotice("已将候选文案填入最终文案。");
  }, []);

  const updateSubtitleStyle = useCallback((field, value) => {
    setSubtitleStyle((current) => ({ ...current, [field]: value }));
    setError("");
    setNotice("");
  }, []);

  const resetSubtitleStyle = useCallback(() => {
    setSubtitleStyle(cloneDefaultSubtitleStyle());
    setError("");
    setNotice("");
  }, []);

  const rewriteCandidate = useCallback(async (candidate) => {
    setRewritingCandidateId(candidate.id);
    setError("");
    setNotice("");
    try {
      const materialContext = Object.fromEntries(
        selectedTemplate.material_requirements.map((requirement) => [
          requirement.key,
          materials[requirement.key]?.length || 0,
        ])
      );
      const response = await apiFetch(
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
        },
        backendBaseUrl
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      const nextContent = String(data.script || "").trim();
      if (!nextContent) throw new Error("LLM 没有返回可用候选文案");
      setScriptCandidates((current) =>
        current.map((item) => (item.id === candidate.id ? { ...item, content: nextContent } : item))
      );
      if (selectedCandidateId === candidate.id && finalScript.trim() === candidate.content.trim()) {
        setFinalScript(nextContent);
      }
      setNotice("候选文案已重写。");
    } catch (err) {
      setError(err.message || "候选文案重写失败");
    } finally {
      setRewritingCandidateId("");
    }
  }, [backendBaseUrl, finalScript, materials, selectedCandidateId, selectedTemplate, templateId, variables]);

  const submitTask = useCallback(async () => {
    setError("");
    setNotice("");
    if (!canSubmit) {
      setError(
        contentIssues[0]
        || subtitleReplacementIssues[0]
        || materialIssues[0]
        || (hasUnsavedSubtitleReplacements ? "请先保存全局敏感词替换规则。" : "请完善素材和文案后再生成。")
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

      const response = await apiFetch(
        "/api/template-production/tasks",
        { method: "POST", body: form },
        backendBaseUrl
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
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
    <section className="workspace-panel template-production-panel" aria-labelledby="template-production-title">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Template Production</span>
          <h2 id="template-production-title">模板量产</h2>
        </div>
        <div className="template-heading-actions">
          <input
            ref={templateFileInputRef}
            hidden
            type="file"
            accept="application/json,.json"
            onChange={importTemplate}
          />
          <button
            className="secondary-action compact-action"
            type="button"
            onClick={() => templateFileInputRef.current?.click()}
            disabled={submitting || importingTemplate}
            title="导入模板 JSON"
          >
            <Icon name={importingTemplate ? "loading" : "upload"} size={15} />
            {importingTemplate ? "导入中" : "导入模板"}
          </button>
          <button
            className="secondary-action compact-action"
            type="button"
            onClick={exportTemplate}
            disabled={!selectedTemplate || exportingTemplate}
            title="导出当前模板 JSON"
          >
            <Icon name={exportingTemplate ? "loading" : "download"} size={15} />
            {exportingTemplate ? "导出中" : "导出模板"}
          </button>
          <span className={`status-pill ${task?.status || (canSubmit ? "ready" : "pending")}`}>
            <Icon
              name={templatesLoading || submitting ? "loading" : task?.status === "completed" ? "check" : "template"}
              size={14}
            />
            {templatesLoading
              ? "加载模板"
              : task
                ? statusLabel(task.status)
                : !selectedTemplate
                  ? "暂无模板"
                  : canSubmit
                    ? "可以生成"
                    : "准备素材"}
          </span>
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
            <button className="secondary-action compact-action" type="button" onClick={() => loadTemplates()}>
              <Icon name="refresh" size={14} />重新加载
            </button>
          </div>
        ) : !templates.length ? (
          <div className="template-empty-state">
            <Icon name="template" size={20} />
            <span>还没有可用模板，请导入模板 JSON。</span>
          </div>
        ) : templates.map((item) => (
          <button
            className={`template-choice ${item.id === templateId ? "is-active" : ""}`}
            key={item.id}
            onClick={() => switchTemplate(item)}
            role="tab"
            type="button"
            aria-selected={item.id === templateId}
            disabled={submitting}
          >
            <span className="template-choice-icon"><Icon name="template" size={20} /></span>
            <span>
              <strong>{item.name}{!item.is_builtin ? <em className="template-owned-label">我的</em> : null}</strong>
              <small>{item.description || "暂无模板说明"}</small>
            </span>
            {item.id === templateId ? <Icon name="check" size={17} /> : null}
          </button>
        ))}
      </div>

      {templateError && templates.length ? <div className="form-alert failed">{templateError}</div> : null}
      {templateNotice ? <div className="form-alert completed">{templateNotice}</div> : null}

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
                      <label className="secondary-action compact-action">
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
                      </label>
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
                              <button
                                className="material-preview-remove"
                                type="button"
                                title={`移除第 ${index + 1} 个素材`}
                                aria-label={`移除第 ${index + 1} 个素材`}
                                onClick={() => removeMaterial(requirement.key, item.id)}
                              >
                                <Icon name="x" size={15} />
                              </button>
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
              <button className="primary-action compact-action" type="button" onClick={generateAiScripts} disabled={generatingScripts}>
                <Icon name={generatingScripts ? "loading" : "sparkles"} size={15} />
                {generatingScripts ? "生成中" : "AI 生成"}
              </button>
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
                        <button
                          type="button"
                          title={`重写候选 ${index + 1}`}
                          aria-label={`重写候选 ${index + 1}`}
                          onClick={() => rewriteCandidate(candidate)}
                          disabled={Boolean(rewritingCandidateId)}
                        >
                          <Icon
                            name={rewritingCandidateId === candidate.id ? "loading" : "refresh"}
                            size={15}
                            data-loading={rewritingCandidateId === candidate.id ? "true" : undefined}
                          />
                        </button>
                      ) : null}
                    </div>
                    <button
                      className="script-candidate-select"
                      type="button"
                      onClick={() => selectCandidate(candidate)}
                      aria-pressed={candidate.id === selectedCandidateId}
                    >
                      <span>{candidate.content}</span>
                      <small>{candidate.id === selectedCandidateId ? <><Icon name="check" size={13} />已选为最终文案</> : "点击选用"}</small>
                    </button>
                  </article>
                ))}
              </div>
            ) : (
              <div className="script-empty-state">
                <Icon name="sparkles" size={22} />
                <span>填写内容信息后生成 {defaultCandidateCount} 条候选文案。</span>
              </div>
            )}
            <label className="field final-script-field">
              <span className="field-label">最终文案</span>
              <textarea
                className="control"
                value={finalScript}
                placeholder="选择上方候选，或直接在这里输入最终用于配音和生成视频的文案"
                onChange={(event) => {
                  setFinalScript(event.target.value);
                  setSelectedCandidateId("");
                  setNotice("");
                }}
              />
            </label>
            <div className="subtitle-style-launcher">
              <div className="subtitle-style-launcher-copy">
                <span className="subtitle-style-launcher-icon"><Icon name="sliders" size={17} /></span>
                <div>
                  <strong>字幕样式</strong>
                  <small>{subtitleStyle.notice_enabled ? "主字幕与小字免责申明" : "主字幕，已隐藏小字免责申明"}</small>
                </div>
              </div>
              <button
                className="secondary-action compact-action subtitle-style-open"
                type="button"
                onClick={() => setSubtitleStyleDialogOpen(true)}
                disabled={submitting}
                aria-haspopup="dialog"
                aria-expanded={subtitleStyleDialogOpen}
              >
                <Icon name="edit" size={15} />编辑样式
              </button>
            </div>
            {subtitleStyleDialogOpen ? (
              <div
                className="modal-backdrop subtitle-style-modal-backdrop"
                role="presentation"
                onMouseDown={(event) => {
                  if (event.target === event.currentTarget) setSubtitleStyleDialogOpen(false);
                }}
              >
                <section
                  className="modal-panel subtitle-style-modal"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="subtitle-style-dialog-title"
                  onMouseDown={(event) => event.stopPropagation()}
                >
                  <div className="subtitle-style-editor">
              <div className="subtitle-style-heading">
                <div>
                  <strong id="subtitle-style-dialog-title">字幕样式</strong>
                  <small>预览使用固定示例内容；成片仍按最终文案、分句和替换规则填充字幕</small>
                </div>
                <div className="subtitle-style-heading-actions">
                  <button
                    className="secondary-action subtitle-style-reset"
                    type="button"
                    onClick={resetSubtitleStyle}
                    title="恢复当前默认字幕样式"
                  >
                    <Icon name="refresh" size={14} />恢复默认
                  </button>
                  <button
                    className="icon-button subtitle-style-close"
                    type="button"
                    onClick={() => setSubtitleStyleDialogOpen(false)}
                    title="关闭字幕样式编辑"
                    aria-label="关闭字幕样式编辑"
                  >
                    <Icon name="x" size={17} />
                  </button>
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
                      <label className="field">
                        <span className="field-label">字体</span>
                        <select
                          className="control"
                          value={subtitleStyle.font_family}
                          onChange={(event) => updateSubtitleStyle("font_family", event.target.value)}
                        >
                          <option value="Microsoft YaHei">微软雅黑</option>
                          <option value="SimHei">黑体</option>
                          <option value="SimSun">宋体</option>
                          <option value="KaiTi">楷体</option>
                        </select>
                      </label>
                      <label className="field">
                        <span className="field-label">对齐</span>
                        <select
                          className="control"
                          value={subtitleStyle.alignment}
                          onChange={(event) => updateSubtitleStyle("alignment", event.target.value)}
                        >
                          <option value="left">左对齐</option>
                          <option value="center">居中</option>
                          <option value="right">右对齐</option>
                        </select>
                      </label>
                    </div>
                    <div className="subtitle-style-slider-grid">
                      <label className="field">
                        <span className="field-label">字号 {subtitleStyle.font_size}</span>
                        <input className="speed-slider" type="range" min="36" max="108" value={subtitleStyle.font_size} onChange={(event) => updateSubtitleStyle("font_size", Number(event.target.value))} />
                      </label>
                      <label className="field">
                        <span className="field-label">描边 {subtitleStyle.outline_width}</span>
                        <input className="speed-slider" type="range" min="0" max="12" value={subtitleStyle.outline_width} onChange={(event) => updateSubtitleStyle("outline_width", Number(event.target.value))} />
                      </label>
                      <label className="field">
                        <span className="field-label">底部边距 {subtitleStyle.bottom_margin}</span>
                        <input className="speed-slider" type="range" min="80" max="480" step="5" value={subtitleStyle.bottom_margin} onChange={(event) => updateSubtitleStyle("bottom_margin", Number(event.target.value))} />
                      </label>
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
                        <input
                          type="checkbox"
                          checked={subtitleStyle.notice_enabled}
                          onChange={(event) => updateSubtitleStyle("notice_enabled", event.target.checked)}
                        />
                        <span aria-hidden="true" />
                        <em>{subtitleStyle.notice_enabled ? "显示" : "不显示"}</em>
                      </label>
                    </div>
                    {subtitleStyle.notice_enabled ? (
                      <>
                        <label className="field subtitle-notice-text-field">
                          <span className="field-label">申明内容</span>
                          <textarea
                            className="control"
                            rows={3}
                            maxLength={120}
                            value={subtitleStyle.notice_text}
                            onChange={(event) => updateSubtitleStyle("notice_text", event.target.value)}
                          />
                        </label>
                        <div className="subtitle-style-slider-grid">
                          <label className="field">
                            <span className="field-label">字号 {subtitleStyle.notice_font_size}</span>
                            <input className="speed-slider" type="range" min="18" max="58" value={subtitleStyle.notice_font_size} onChange={(event) => updateSubtitleStyle("notice_font_size", Number(event.target.value))} />
                          </label>
                          <label className="field">
                            <span className="field-label">描边 {subtitleStyle.notice_outline_width}</span>
                            <input className="speed-slider" type="range" min="0" max="6" value={subtitleStyle.notice_outline_width} onChange={(event) => updateSubtitleStyle("notice_outline_width", Number(event.target.value))} />
                          </label>
                          <label className="field">
                            <span className="field-label">顶部边距 {subtitleStyle.notice_top_margin}</span>
                            <input className="speed-slider" type="range" min="30" max="260" value={subtitleStyle.notice_top_margin} onChange={(event) => updateSubtitleStyle("notice_top_margin", Number(event.target.value))} />
                          </label>
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
                    <button
                      className="primary-action subtitle-style-confirm"
                      type="button"
                      onClick={() => setSubtitleStyleDialogOpen(false)}
                      title="确认当前字幕样式"
                    >
                      <Icon name="check" size={15} />确认
                    </button>
                  </div>
                </section>
              </div>
            ) : null}
            {selectedTemplate.runtime_capabilities?.subtitle_replacements ? (
              <div className="subtitle-replacement-editor">
                <div className="subtitle-replacement-heading">
                  <div>
                    <strong>全局敏感词替换</strong>
                    <small>所有用户和模板共用，只修改成片字幕，配音仍使用最终文案原文</small>
                  </div>
                  {subtitleReplacements.length ? (
                    <button
                      className="secondary-action subtitle-replacement-add"
                      type="button"
                      onClick={addSubtitleReplacement}
                      disabled={subtitleReplacements.length >= MAX_SUBTITLE_REPLACEMENTS}
                    >
                      <Icon name="plus" size={14} />添加
                    </button>
                  ) : null}
                </div>
                {subtitleReplacements.length ? (
                  <div className="subtitle-replacement-list">
                    {subtitleReplacements.map((item, index) => {
                      const isSaving = savingSubtitleReplacementIds.has(item.id);
                      const isDirty = dirtySubtitleReplacementIds.has(item.id);
                      const isSaved = savedSubtitleReplacementIds.has(item.id);
                      const source = item.source.trim();
                      const replacement = item.replacement.trim();
                      const duplicateSource = subtitleReplacements.some((other) => (
                        other.id !== item.id && other.source.trim() === source
                      ));
                      const canSave = isDirty && Boolean(source) && Boolean(replacement)
                        && source !== replacement && !duplicateSource;
                      return (
                      <div className="subtitle-replacement-card" key={item.id}>
                        <label className="field subtitle-replacement-source">
                          <span className="field-label">需要替换的词</span>
                          <input
                            className="control"
                            value={item.source}
                            maxLength={80}
                            placeholder="例如：医生"
                            aria-label={`第 ${index + 1} 条需要替换的词`}
                            onChange={(event) => updateSubtitleReplacement(item.id, "source", event.target.value)}
                            disabled={isSaving}
                          />
                        </label>
                        <span className="subtitle-replacement-arrow" aria-hidden="true">
                          <Icon name="arrowRight" size={16} />
                        </span>
                        <label className="field subtitle-replacement-target">
                          <span className="field-label">字幕替换成</span>
                          <input
                            className="control"
                            value={item.replacement}
                            maxLength={80}
                            placeholder="例如：yi生"
                            aria-label={`第 ${index + 1} 条字幕替换词`}
                            onChange={(event) => updateSubtitleReplacement(item.id, "replacement", event.target.value)}
                            disabled={isSaving}
                          />
                        </label>
                        <button
                          className="primary-action subtitle-replacement-save"
                          type="button"
                          title="保存此条全局敏感词替换"
                          onClick={() => saveSubtitleReplacement(item.id)}
                          disabled={!canSave || isSaving}
                        >
                          <Icon name={isSaving ? "loading" : isSaved ? "check" : "save"} size={14} />
                          {isSaving ? "保存中" : isSaved ? "已保存" : "保存"}
                        </button>
                        <button
                          className="subtitle-replacement-remove"
                          type="button"
                          title={`删除第 ${index + 1} 条字幕替换`}
                          aria-label={`删除第 ${index + 1} 条字幕替换`}
                          onClick={() => requestSubtitleReplacementDelete(item.id)}
                          disabled={isSaving}
                        >
                          <Icon name="trash" size={15} />
                        </button>
                      </div>
                      );
                    })}
                  </div>
                ) : (
                  <button className="subtitle-replacement-add-card" type="button" onClick={addSubtitleReplacement}>
                    <Icon name="plus" size={18} />
                    <span><strong>添加替换规则</strong><small>原词用于配音，替换词仅显示在字幕中</small></span>
                  </button>
                )}
                {subtitleReplacementIssues.length ? (
                  <div className="subtitle-replacement-issue"><Icon name="alert" size={14} />{subtitleReplacementIssues[0]}</div>
                ) : null}
                {subtitleReplacementsLoading ? (
                  <div className="subtitle-replacement-issue"><Icon name="loading" size={14} />正在加载全局规则</div>
                ) : null}
                {subtitleReplacementError ? (
                  <div className="subtitle-replacement-issue"><Icon name="alert" size={14} />{subtitleReplacementError}</div>
                ) : null}
                {subtitleReplacementNotice ? (
                  <div className="subtitle-replacement-notice"><Icon name="check" size={14} />{subtitleReplacementNotice}</div>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="template-work-section" aria-labelledby="template-bgm-title">
            <div className="template-section-heading with-actions">
              <span><Icon name="music" size={17} /></span>
              <div><strong id="template-bgm-title">背景音乐</strong><small>为所有成片添加 BGM，可上传保存后反复使用</small></div>
              <input
                ref={bgmFileInputRef}
                hidden
                type="file"
                accept="audio/*,.mp3,.wav,.aac,.m4a,.ogg,.flac"
                onChange={uploadBgm}
              />
              <button
                className="secondary-action compact-action"
                type="button"
                onClick={() => bgmFileInputRef.current?.click()}
                disabled={submitting || uploadingBgm}
                title="上传背景音乐"
              >
                <Icon name={uploadingBgm ? "loading" : "upload"} size={15} />
                {uploadingBgm ? "上传中" : "上传"}
              </button>
            </div>
            <div className="bgm-control-row">
              <label className="field bgm-select-field">
                <span className="field-label">选择背景音乐</span>
                <select
                  className="control"
                  value={selectedBgmId}
                  onChange={(event) => {
                    setSelectedBgmId(event.target.value);
                    setBgmNotice("");
                    setBgmError("");
                  }}
                  disabled={submitting || uploadingBgm || bgmLoading}
                >
                  <option value="">不使用背景音乐</option>
                  {bgmTracks.map((track) => (
                    <option key={track.id} value={track.id}>
                      {track.name}（{formatDuration(track.duration)}）
                    </option>
                  ))}
                </select>
              </label>
              {selectedBgmTrack ? (
                <button
                  className="bgm-delete-button"
                  type="button"
                  title={`删除背景音乐“${selectedBgmTrack.name}”`}
                  aria-label={`删除背景音乐“${selectedBgmTrack.name}”`}
                  onClick={() => requestBgmDelete(selectedBgmTrack)}
                  disabled={submitting || uploadingBgm || deletingBgmId === selectedBgmTrack.id}
                >
                  <Icon name={deletingBgmId === selectedBgmTrack.id ? "loading" : "trash"} size={15} />
                </button>
              ) : null}
            </div>
            {selectedBgmTrack ? (
              <div className="bgm-preview">
                <audio
                  controls
                  preload="metadata"
                  src={resolveBackendAssetUrl(selectedBgmTrack.preview_url, backendBaseUrl)}
                />
                <span className="bgm-preview-meta">
                  <Icon name="audio" size={14} />
                  {formatFileSize(selectedBgmTrack.file_size)} · {formatDuration(selectedBgmTrack.duration)}
                </span>
              </div>
            ) : null}
            {bgmLoading ? (
              <div className="bgm-status-line"><Icon name="loading" size={14} />正在加载背景音乐</div>
            ) : null}
            {bgmError ? (
              <div className="bgm-status-line is-error"><Icon name="alert" size={14} />{bgmError}</div>
            ) : null}
            {bgmNotice ? (
              <div className="bgm-status-line is-success"><Icon name="check" size={14} />{bgmNotice}</div>
            ) : null}
          </section>

          {error ? <div className="form-alert failed">{error}</div> : null}
          {notice ? <div className="form-alert completed">{notice}</div> : null}
          {materialIssues.length && finalScript.trim() ? <div className="template-inline-warning">{materialIssues[0]}</div> : null}

          <div className="template-submit-row">
            <label className="template-submit-count" htmlFor="template-generate-count">
              <span>生成数量</span>
              <input
                id="template-generate-count"
                className="control"
                type="number"
                min="1"
                max={maxBatchSize}
                value={generateCount}
                onChange={(event) => setGenerateCount(Math.max(1, Math.min(maxBatchSize, Number(event.target.value) || 1)))}
              />
            </label>
            <button className="primary-action template-submit-action" type="button" onClick={submitTask} disabled={!canSubmit}>
              <Icon name={submitting ? "loading" : "wand"} size={17} />
              {submitting ? "正在批量生成" : `生成 ${generateCount} 条视频`}
            </button>
          </div>
        </div>
      </div> : null}

      {subtitleReplacementPendingDelete ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal-panel"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="subtitle-replacement-delete-title"
          >
            <div className="modal-heading">
              <div>
                <span className="section-kicker">Global Rule</span>
                <h3 id="subtitle-replacement-delete-title">确认删除敏感词替换？</h3>
              </div>
            </div>
            <div className="modal-body">
              <p>“{subtitleReplacementPendingDelete.source}”将不再替换为“{subtitleReplacementPendingDelete.replacement}”。</p>
              <small>此变更会影响所有用户后续创建的视频任务，已创建的任务不受影响。</small>
            </div>
            <div className="delete-confirm-actions">
              <button
                className="secondary-action"
                type="button"
                onClick={() => setSubtitleReplacementPendingDelete(null)}
              >取消</button>
              <button
                className="danger-action"
                type="button"
                onClick={confirmSubtitleReplacementDelete}
              ><Icon name="trash" size={15} />确认删除</button>
            </div>
          </section>
        </div>
      ) : null}

      {pendingBgmDelete ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal-panel"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="bgm-delete-title"
          >
            <div className="modal-heading">
              <div>
                <span className="section-kicker">BGM</span>
                <h3 id="bgm-delete-title">确认删除背景音乐？</h3>
              </div>
            </div>
            <div className="modal-body">
              <p>“{pendingBgmDelete.name}”将被永久删除，无法恢复。</p>
            </div>
            <div className="delete-confirm-actions">
              <button
                className="secondary-action"
                type="button"
                onClick={() => setPendingBgmDelete(null)}
              >取消</button>
              <button
                className="danger-action"
                type="button"
                onClick={confirmBgmDelete}
              ><Icon name="trash" size={15} />确认删除</button>
            </div>
          </section>
        </div>
      ) : null}

      {task ? (
        <section className="template-results" aria-labelledby="template-results-title">
          <div className="template-results-heading">
            <div>
              <span className="section-kicker">Output</span>
              <h3 id="template-results-title">生成结果</h3>
              <p>{task.message}</p>
            </div>
            {task.zip_url ? (
              <a className="secondary-action" href={resolveBackendAssetUrl(task.zip_url, backendBaseUrl)} download>
                <Icon name="download" size={16} />下载全部
              </a>
            ) : null}
          </div>
          <div className="template-progress-track" aria-label={`生成进度 ${task.progress || 0}%`}>
            <span style={{ width: `${task.progress || 0}%` }} />
          </div>
          <div className="template-result-grid">
            {(task.items || []).map((item) => (
              <article className={`template-result-item ${item.status}`} key={item.id || item.index}>
                <div className="template-result-media">
                  {item.video_url ? (
                    <video controls preload="metadata" src={resolveBackendAssetUrl(item.video_url, backendBaseUrl)} />
                  ) : (
                    <div className="template-result-placeholder"><Icon name={item.status === "failed" ? "alert" : "loading"} size={22} /></div>
                  )}
                </div>
                <div className="template-result-copy">
                  <div><strong>视频 {item.index}</strong><span className={`status-pill ${item.status}`}>{statusLabel(item.status)}</span></div>
                  <p>{item.script}</p>
                  {item.error ? <small className="result-error">{item.error}</small> : null}
                  {item.video_url ? (
                    <a href={resolveBackendAssetUrl(item.video_url, backendBaseUrl)} download>
                      <Icon name="download" size={14} />下载视频
                    </a>
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
