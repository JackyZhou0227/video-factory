import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import FormControlLabel from "@mui/material/FormControlLabel";
import { statusChipColors } from "../theme";
import BgmManager from "./BgmManager";
import Icon from "./Icon";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import SubtitleReplacementManager from "./SubtitleReplacementManager";
import SubtitleSettings, { cloneDefaultSubtitleStyle } from "./SubtitleSettings";
import { apiJson, useBackendBaseUrl } from "../lib/backend";
import { useGlobalMessage } from "./GlobalMessageProvider";

const FINAL_STATUSES = new Set(["completed", "partial_failed", "failed"]);
const MAX_KEYWORDS = 20;
const MAX_MATERIALS = 20;
const MAX_MATERIAL_FILE_SIZE = 500 * 1024 * 1024;
const IMAGE_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "bmp"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "m4v", "webm", "mkv", "avi"]);
const PACING_OPTIONS = [
  { value: "fast", label: "快节奏", description: "每镜头 1.5-2.5 秒" },
  { value: "standard", label: "标准节奏", description: "每镜头 2.5-4.0 秒" },
  { value: "slow", label: "舒缓节奏", description: "每镜头 4.0-6.0 秒" },
];

function makeId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function normalizeKeywordKey(value) {
  return String(value || "").normalize("NFKC").trim().toLocaleLowerCase("zh-CN");
}

function splitKeywords(value) {
  return String(value || "")
    .split(/[，,；;\r\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isChineseKeyword(value) {
  return /^[\u3400-\u4dbf\u4e00-\u9fff]+$/.test(value);
}

function detectMediaType(file) {
  const extension = String(file?.name || "").split(".").pop()?.toLowerCase() || "";
  if (IMAGE_EXTENSIONS.has(extension)) return "image";
  if (VIDEO_EXTENSIONS.has(extension)) return "video";
  return "";
}

function formatFileSize(size) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
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

export default function SmartEditing({ currentUser }) {
  const backendBaseUrl = useBackendBaseUrl();
  const { showSuccess } = useGlobalMessage();
  const [script, setScript] = useState("");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keywordGroups, setKeywordGroups] = useState([]);
  const [editingKeywords, setEditingKeywords] = useState(true);
  const [keywordNotice, setKeywordNotice] = useState("");
  const [keywordError, setKeywordError] = useState("");
  const [extractingKeywords, setExtractingKeywords] = useState(false);
  const [pendingKeywordChange, setPendingKeywordChange] = useState(null);
  const [scriptAtKeywordParse, setScriptAtKeywordParse] = useState(null);
  const [pacing, setPacing] = useState("standard");
  const [subtitleEnabled, setSubtitleEnabled] = useState(false);
  const [subtitleStyle, setSubtitleStyle] = useState(cloneDefaultSubtitleStyle);
  const [generateCount, setGenerateCount] = useState(5);
  const [selectedBgmId, setSelectedBgmId] = useState("");
  const [replacementStatus, setReplacementStatus] = useState({
    issues: [],
    hasUnsaved: false,
    loading: true,
    error: "",
  });
  const [missingKeywordIndex, setMissingKeywordIndex] = useState(-1);
  const [task, setTask] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const keywordDraftRef = useRef("");
  const pollRef = useRef(null);
  const taskStorageKey = `vf.smartEditingTask.v1.${currentUser?.id || "local"}`;

  const totalMaterials = useMemo(
    () => keywordGroups.reduce((total, group) => total + group.materials.length, 0),
    [keywordGroups]
  );
  const firstMissingGroupIndex = keywordGroups.findIndex((group) => group.materials.length === 0);
  const cleanScript = script.trim();
  const scriptIssue = cleanScript.length < 10
    ? "文案至少需要 10 个字符。"
    : cleanScript.length > 5000
      ? "文案不能超过 5000 个字符。"
      : "";
  const scriptChangedAfterKeywords = scriptAtKeywordParse !== null
    && cleanScript !== scriptAtKeywordParse
    && keywordGroups.length > 0;
  const canSubmit = !scriptIssue
    && keywordGroups.length > 0
    && !editingKeywords
    && firstMissingGroupIndex < 0
    && (!subtitleEnabled || replacementStatus.issues.length === 0)
    && (!subtitleEnabled || !replacementStatus.hasUnsaved)
    && !submitting;

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = null;
  }, []);

  const pollTask = useCallback(async (taskId) => {
    try {
      const nextTask = await apiJson(
        `/api/smart-editing/tasks/${encodeURIComponent(taskId)}`,
        { silentError: true },
        backendBaseUrl
      );
      setTask(nextTask);
      setSubmitting(!FINAL_STATUSES.has(nextTask.status));
      if (!FINAL_STATUSES.has(nextTask.status)) {
        pollRef.current = window.setTimeout(() => pollTask(taskId), 1500);
      }
    } catch (pollError) {
      if (pollError?.status === 404) {
        localStorage.removeItem(taskStorageKey);
        setTask(null);
        setError("上一次智能剪辑任务已失效，可能是后端服务已经重启。");
      } else {
        setError(pollError.message || "读取智能剪辑任务失败");
      }
      setSubmitting(false);
    }
  }, [backendBaseUrl, taskStorageKey]);

  useEffect(() => {
    const storedTaskId = localStorage.getItem(taskStorageKey);
    if (storedTaskId) pollTask(storedTaskId);
    return stopPolling;
  }, [pollTask, stopPolling, taskStorageKey]);

  const applyKeywordChange = useCallback((nextGroups, duplicateKeywords = []) => {
    setKeywordGroups(nextGroups);
    const nextDraft = nextGroups.map((group) => group.keyword).join("\n");
    setKeywordDraft(nextDraft);
    keywordDraftRef.current = nextDraft;
    setEditingKeywords(false);
    setPendingKeywordChange(null);
    setMissingKeywordIndex(-1);
    setScriptAtKeywordParse(script.trim());
    setKeywordError("");
    setKeywordNotice(
      duplicateKeywords.length
        ? `检测到重复关键词，已按文案顺序保留：${duplicateKeywords.join("、")}`
        : `已解析 ${nextGroups.length} 个关键词，顺序将作为剪辑依据。`
    );
  }, [script]);

  const parseKeywordDraft = useCallback((value = keywordDraftRef.current) => {
    const parsed = splitKeywords(value);
    if (!parsed.length) {
      setKeywordError("请粘贴至少 1 个关键词。");
      return false;
    }

    const normalizedKeywords = [];
    const occurrences = new Map();
    const duplicateKeywords = [];
    for (const keyword of parsed) {
      if (!isChineseKeyword(keyword)) {
        setKeywordError(`关键词“${keyword.slice(0, 20)}”必须使用中文。`);
        return false;
      }
      if (keyword.length > 100) {
        setKeywordError(`关键词“${keyword.slice(0, 20)}”不能超过 100 个字符。`);
        return false;
      }
      const key = normalizeKeywordKey(keyword);
      const occurrence = (occurrences.get(key) || 0) + 1;
      occurrences.set(key, occurrence);
      if (occurrence > 1 && !duplicateKeywords.includes(keyword)) duplicateKeywords.push(keyword);
      normalizedKeywords.push({ keyword, key, occurrence });
    }
    if (normalizedKeywords.length > MAX_KEYWORDS) {
      setKeywordError(`关键词最多 ${MAX_KEYWORDS} 个，当前解析出 ${normalizedKeywords.length} 个。`);
      return false;
    }

    const previousByIdentity = new Map(
      keywordGroups.map((group) => [`${group.key}::${group.occurrence || 1}`, group])
    );
    const nextGroups = normalizedKeywords.map(({ keyword, key, occurrence }) => {
      const previous = previousByIdentity.get(`${key}::${occurrence}`);
      return {
        id: previous?.id || makeId(),
        key,
        keyword,
        occurrence,
        materials: previous?.materials || [],
      };
    });
    const nextIds = new Set(nextGroups.map((group) => group.id));
    const removedGroups = keywordGroups.filter(
      (group) => !nextIds.has(group.id) && group.materials.length > 0
    );
    if (removedGroups.length) {
      setPendingKeywordChange({ nextGroups, duplicateKeywords, removedGroups });
      setKeywordError("");
      return false;
    }

    applyKeywordChange(nextGroups, duplicateKeywords);
    return true;
  }, [applyKeywordChange, keywordGroups]);

  const updateKeywordDraft = useCallback((value) => {
    setKeywordDraft(value);
    keywordDraftRef.current = value;
    setKeywordError("");
    setKeywordNotice("");
  }, []);

  const handleKeywordPaste = useCallback(() => {
    window.setTimeout(() => parseKeywordDraft(keywordDraftRef.current), 0);
  }, [parseKeywordDraft]);

  const extractKeywords = useCallback(async () => {
    setError("");
    setKeywordError("");
    if (scriptIssue) {
      setError(scriptIssue);
      return;
    }

    setExtractingKeywords(true);
    try {
      const data = await apiJson(
        "/api/smart-editing/keywords/extract",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ script: cleanScript, count: 8 }),
          silentError: true,
        },
        backendBaseUrl
      );
      const keywords = Array.isArray(data?.keywords) ? data.keywords : [];
      if (!keywords.length) throw new Error("没有提取到可用关键词，请重试或手动编辑。");
      const nextDraft = keywords.join("\n");
      setKeywordDraft(nextDraft);
      keywordDraftRef.current = nextDraft;
      parseKeywordDraft(nextDraft);
    } catch (extractError) {
      setError(extractError.message || "提取关键词失败");
    } finally {
      setExtractingKeywords(false);
    }
  }, [backendBaseUrl, cleanScript, parseKeywordDraft, scriptIssue]);

  const beginKeywordEdit = useCallback(() => {
    const nextDraft = keywordGroups.map((group) => group.keyword).join("\n");
    setKeywordDraft(nextDraft);
    keywordDraftRef.current = nextDraft;
    setEditingKeywords(true);
    setKeywordError("");
    setKeywordNotice("修改或重新粘贴完整关键词列表，解析后再继续生成。");
  }, [keywordGroups]);

  const addMaterials = useCallback((groupIndex, fileList) => {
    const selectedFiles = Array.from(fileList || []);
    if (!selectedFiles.length) return;
    const available = Math.max(0, MAX_MATERIALS - totalMaterials);
    const additions = [];
    const rejected = [];
    selectedFiles.forEach((file) => {
      if (additions.length >= available) return;
      const mediaType = detectMediaType(file);
      if (!mediaType) {
        rejected.push(`${file.name} 格式不支持`);
      } else if (file.size > MAX_MATERIAL_FILE_SIZE) {
        rejected.push(`${file.name} 超过 500 MB`);
      } else {
        additions.push({ id: makeId(), file, mediaType });
      }
    });

    if (additions.length) {
      setKeywordGroups((current) => current.map((group, index) => (
        index === groupIndex
          ? { ...group, materials: [...group.materials, ...additions] }
          : group
      )));
      if (missingKeywordIndex === groupIndex) setMissingKeywordIndex(-1);
    }
    if (selectedFiles.length > available) {
      rejected.push(`素材总数最多 ${MAX_MATERIALS} 个`);
    }
    setError(rejected.join("；"));
  }, [missingKeywordIndex, totalMaterials]);

  const removeMaterial = useCallback((groupIndex, materialId) => {
    setKeywordGroups((current) => current.map((group, index) => (
      index === groupIndex
        ? { ...group, materials: group.materials.filter((item) => item.id !== materialId) }
        : group
    )));
  }, []);

  const focusMissingGroup = useCallback((groupIndex) => {
    setMissingKeywordIndex(groupIndex);
    window.setTimeout(() => {
      document.getElementById(`smart-material-group-${groupIndex}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }, 0);
  }, []);

  const submitTask = useCallback(async () => {
    setError("");
    if (scriptIssue) {
      setError(scriptIssue);
      return;
    }
    if (!keywordGroups.length || editingKeywords) {
      setError("请先解析并确认完整关键词列表。");
      return;
    }
    const missingIndex = keywordGroups.findIndex((group) => group.materials.length === 0);
    if (missingIndex >= 0) {
      setError(`关键词“${keywordGroups[missingIndex].keyword}”还没有上传素材。`);
      focusMissingGroup(missingIndex);
      return;
    }
    if (subtitleEnabled && replacementStatus.issues.length) {
      setError(replacementStatus.issues[0]);
      return;
    }
    if (subtitleEnabled && replacementStatus.hasUnsaved) {
      setError("请先保存当前用户的敏感词替换规则。");
      return;
    }

    stopPolling();
    setSubmitting(true);
    setTask({ status: "pending", progress: 0, message: "正在上传素材", items: [] });
    try {
      const form = new FormData();
      const manifest = [];
      let fileIndex = 0;
      keywordGroups.forEach((group, keywordIndex) => {
        group.materials.forEach((item) => {
          form.append("materials", item.file, item.file.name);
          manifest.push({
            keyword_index: keywordIndex,
            file_index: fileIndex,
            media_type: item.mediaType,
            name: item.file.name,
          });
          fileIndex += 1;
        });
      });
      form.append("script", cleanScript);
      form.append("keywords", JSON.stringify(keywordGroups.map((group) => group.keyword)));
      form.append("pacing", pacing);
      form.append("generate_count", String(generateCount));
      form.append("subtitle_enabled", String(subtitleEnabled));
      form.append("subtitle_style", JSON.stringify(subtitleStyle));
      form.append("material_manifest", JSON.stringify(manifest));
      if (selectedBgmId) form.append("bgm_id", selectedBgmId);

      const data = await apiJson(
        "/api/smart-editing/tasks",
        { method: "POST", body: form, silentError: true },
        backendBaseUrl
      );
      localStorage.setItem(taskStorageKey, data.task_id);
      showSuccess("任务已创建，配音只生成一次，多个画面版本将复用同一音频。");
      pollTask(data.task_id);
    } catch (submitError) {
      setError(submitError.message || "创建智能剪辑任务失败");
      setSubmitting(false);
      setTask(null);
    }
  }, [
    backendBaseUrl,
    cleanScript,
    editingKeywords,
    focusMissingGroup,
    generateCount,
    keywordGroups,
    pacing,
    pollTask,
    replacementStatus.hasUnsaved,
    replacementStatus.issues,
    selectedBgmId,
    subtitleEnabled,
    subtitleStyle,
    scriptIssue,
    stopPolling,
    taskStorageKey,
  ]);

  return (
    <section className="workspace-panel smart-editing-panel" aria-label="智能剪辑工作区">
      <div className="smart-editing-grid">
        <div className="smart-editing-column">
          <section className="template-work-section" aria-labelledby="smart-script-title">
            <div className="template-section-heading with-actions">
              <span><Icon name="file" size={17} /></span>
              <div><strong id="smart-script-title">文案</strong><small>输入完整文案，关键词会按叙事顺序提取，重复关键词会保留</small></div>
              <Button
                type="button"
                variant="outlined"
                size="small"
                onClick={extractKeywords}
                disabled={extractingKeywords || submitting}
                startIcon={<Icon name={extractingKeywords ? "loading" : "sparkles"} size={14} />}
              >
                {extractingKeywords ? "正在提取" : "提取关键词"}
              </Button>
            </div>
            <TextField
              className="smart-script-input"
              placeholder="输入要制作的视频文案"
              fullWidth
              multiline
              rows={10}
              value={script}
              slotProps={{ htmlInput: { maxLength: 5000 } }}
              onChange={(event) => setScript(event.target.value)}
              helperText={`${cleanScript.length}/5000 字符`}
            />
            {scriptChangedAfterKeywords ? (
              <div className="smart-inline-warning"><Icon name="alert" size={14} />文案已修改，请确认 Agent 关键词仍然适用。</div>
            ) : null}
          </section>

          <section className="template-work-section" aria-labelledby="smart-keywords-title">
            <div className="template-section-heading with-actions">
              <span><Icon name="list" size={17} /></span>
              <div><strong id="smart-keywords-title">有序关键词</strong><small>支持逗号、分号和换行，顺序不可拖动</small></div>
              {!editingKeywords && keywordGroups.length ? (
                <Button type="button" variant="outlined" size="small" onClick={beginKeywordEdit}
                  startIcon={<Icon name="edit" size={14} />}>
                  重新编辑关键词
                </Button>
              ) : null}
            </div>
            {editingKeywords ? (
              <div className="smart-keyword-editor">
                <TextField
                  className="smart-keyword-textarea"
                  fullWidth
                  multiline
                  rows={4}
                  value={keywordDraft}
                  placeholder={'例如：\n医院\n医生\n问诊'}
                  onChange={(event) => updateKeywordDraft(event.target.value)}
                  onPaste={handleKeywordPaste}
                  onBlur={() => keywordDraftRef.current.trim() && parseKeywordDraft()}
                />
                <Button type="button" variant="contained" size="small" onClick={() => parseKeywordDraft()}
                  startIcon={<Icon name="check" size={14} />}>
                  解析并确认顺序
                </Button>
              </div>
            ) : (
              <ol className="smart-keyword-list">
                {keywordGroups.map((group) => <li key={group.id}>{group.keyword}</li>)}
              </ol>
            )}
            {keywordError ? <div className="smart-inline-error"><Icon name="alert" size={14} />{keywordError}</div> : null}
            {keywordNotice ? <div className="smart-inline-notice"><Icon name="check" size={14} />{keywordNotice}</div> : null}
          </section>

          <section className="template-work-section" aria-labelledby="smart-settings-title">
            <div className="template-section-heading">
              <span><Icon name="sliders" size={17} /></span>
              <div><strong id="smart-settings-title">生成设置</strong><small>V1 开放剪辑节奏、生成数量和可选 BGM</small></div>
            </div>
            <div className="smart-pacing-grid">
              <RadioGroup
                row
                aria-labelledby="smart-settings-title"
                name="smart-pacing"
                value={pacing}
                onChange={(event) => setPacing(event.target.value)}
                sx={{ gridColumn: "1 / -1", display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 1.5 }}
              >
                {PACING_OPTIONS.map((option) => (
                  <FormControlLabel
                    key={option.value}
                    value={option.value}
                    control={<Radio size="small" sx={{ display: "none" }} />}
                    label={
                      <span>
                        <strong>{option.label}</strong>
                        <small>{option.description}</small>
                      </span>
                    }
                    sx={{
                      m: 0,
                      minWidth: 0,
                      display: "grid",
                      gap: "3px",
                      padding: "11px 12px",
                      border: "1px solid",
                      borderRadius: "8px",
                      cursor: "pointer",
                      borderColor: pacing === option.value ? "primary.main" : "divider",
                      backgroundColor: pacing === option.value ? "var(--accent-soft)" : "var(--surface-muted)",
                      "&:hover": { borderColor: "primary.main" },
                      "& span strong": { fontSize: 13, display: "block" },
                      "& span small": { color: "text.secondary", fontSize: 11 },
                    }}
                  />
                ))}
              </RadioGroup>
            </div>
            <TextField
              className="smart-count-field"
              label="生成数量"
              size="small"
              type="number"
              slotProps={{ htmlInput: { min: 1, max: 10 } }}
              value={generateCount}
              onChange={(event) => setGenerateCount(Math.max(1, Math.min(10, Number(event.target.value) || 1)))}
              helperText="同一配音生成 1-10 个不同画面版本"
            />
          </section>

          <BgmManager
            currentUserId={currentUser?.id}
            selectedBgmId={selectedBgmId}
            onSelectionChange={setSelectedBgmId}
            disabled={submitting}
            idPrefix="smart"
          />

          <section className="template-work-section" aria-labelledby="smart-subtitle-title">
            <SubtitleSettings
              idPrefix="smart"
              enabled={subtitleEnabled}
              onEnabledChange={setSubtitleEnabled}
              style={subtitleStyle}
              onStyleChange={setSubtitleStyle}
              disabled={submitting}
            />
          </section>

          {subtitleEnabled ? <section className="template-work-section" aria-label="敏感词替换">
            <SubtitleReplacementManager
              currentUserId={currentUser?.id}
              onStatusChange={setReplacementStatus}
            />
          </section> : null}
        </div>

        <div className="smart-editing-column">
          <section className="template-work-section smart-material-section" aria-labelledby="smart-materials-title">
            <div className="template-section-heading">
              <span><Icon name="upload" size={17} /></span>
              <div><strong id="smart-materials-title">关键词素材</strong><small>每组至少 1 个，图片和视频可混合，总计最多 {MAX_MATERIALS} 个</small></div>
            </div>
            <div className="smart-material-summary">
              <span>{keywordGroups.length} 个关键词</span>
              <span>{totalMaterials}/{MAX_MATERIALS} 个素材</span>
            </div>
            {keywordGroups.length ? (
              <div className="smart-material-groups">
                {keywordGroups.map((group, groupIndex) => (
                  <article
                    className={`material-requirement smart-material-group ${missingKeywordIndex === groupIndex ? "has-error" : ""}`}
                    id={`smart-material-group-${groupIndex}`}
                    key={group.id}
                  >
                    <div className="material-requirement-heading">
                      <div>
                        <span className="smart-keyword-number">{groupIndex + 1}</span>
                        <div><strong>{group.keyword}</strong><small>按此位置参与每一轮素材轮询</small></div>
                      </div>
                      <span>{group.materials.length} 个素材</span>
                    </div>
                    {group.materials.length ? (
                      <div className="material-file-list">
                        {group.materials.map((item, materialIndex) => (
                          <div className="material-preview-card" key={item.id}>
                            <MaterialPreview
                              file={item.file}
                              mediaType={item.mediaType}
                              label={`${group.keyword}素材 ${materialIndex + 1}`}
                            />
                            <div className="material-preview-footer">
                              <span title={item.file.name}>
                                <strong>{item.file.name}</strong>
                                <small>{formatFileSize(item.file.size)} · {item.mediaType === "image" ? "图片" : "视频"}</small>
                              </span>
                              <IconButton
                                type="button"
                                title={`删除 ${item.file.name}`}
                                aria-label={`删除 ${item.file.name}`}
                                onClick={() => removeMaterial(groupIndex, item.id)}
                                size="small"
                              >
                                <Icon name="trash" size={14} />
                              </IconButton>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="material-empty">该关键词还没有素材，提交前必须上传。</div>
                    )}
                    <Button component="label" variant="outlined" size="small" className="smart-material-upload">
                      <Icon name="plus" size={14} />添加图片或视频
                      <input
                        hidden
                        type="file"
                        multiple
                        accept="image/*,video/*,.jpg,.jpeg,.png,.webp,.bmp,.mp4,.mov,.m4v,.webm,.mkv,.avi"
                        onChange={(event) => {
                          addMaterials(groupIndex, event.target.files);
                          event.target.value = "";
                        }}
                      />
                    </Button>
                  </article>
                ))}
              </div>
            ) : (
              <div className="smart-material-empty-state">
                <Icon name="list" size={22} />
                <strong>先解析关键词</strong>
                <span>系统会为每个关键词自动创建一个独立素材上传区。</span>
              </div>
            )}
          </section>

          <section className="template-work-section smart-submit-section" aria-labelledby="smart-submit-title">
            <div className="template-section-heading">
              <span><Icon name="wand" size={17} /></span>
              <div><strong id="smart-submit-title">创建任务</strong><small>硬切、轻微图片放大、最终严格裁剪到配音时长</small></div>
            </div>
            {error ? <div className="form-alert failed">{error}</div> : null}
            <Button className="smart-submit-action" type="button" variant="contained" size="large" onClick={submitTask} disabled={!canSubmit}
              startIcon={<Icon name={submitting ? "loading" : "wand"} size={17} />}>
              {submitting ? "正在智能剪辑" : `生成 ${generateCount} 条视频`}
            </Button>
          </section>

          {task ? (
            <section className="template-work-section smart-task-section" aria-labelledby="smart-task-title">
              <div className="template-section-heading with-actions">
                <span><Icon name={FINAL_STATUSES.has(task.status) ? "check" : "loading"} size={17} /></span>
                <div>
                  <strong id="smart-task-title">任务结果</strong>
                  <small>{task.message || statusLabel(task.status)} · {task.bgm_name ? `BGM：${task.bgm_name}` : "无 BGM"}</small>
                </div>
                <Chip
                  size="small"
                  label={statusLabel(task.status)}
                  sx={{
                    backgroundColor: statusChipColors[task.status]?.bg || "#f3f1e9",
                    color: statusChipColors[task.status]?.fg || "#68645b",
                    fontWeight: 600,
                  }}
                />
              </div>
              <div className="task-progress-block">
                <div className="task-progress-meta"><span>处理进度</span><strong>{task.progress || 0}%</strong></div>
                <LinearProgress variant="determinate" value={Math.max(0, Math.min(100, task.progress || 0))} sx={{ mt: 0.5 }} />
              </div>
              {task.error ? <div className="form-alert failed">{task.error}</div> : null}
              {task.items?.length ? (
                <div className="smart-result-grid">
                  {task.items.map((item) => (
                    <article className={`smart-result-card ${item.status || ""}`} key={item.id}>
                      <div className="smart-result-preview">
                        {item.video_url ? (
                          <ProtectedMedia
                            path={item.video_url}
                            kind="video"
                            backendBaseUrl={backendBaseUrl}
                          />
                        ) : (
                          <div className="task-artifact-placeholder">
                            <Icon name={item.status === "failed" ? "alert" : "loading"} size={22} />
                            <span>{item.message || statusLabel(item.status)}</span>
                          </div>
                        )}
                      </div>
                      <div className="smart-result-footer">
                        <span><strong>版本 {item.index}</strong><small>{item.error || item.message}</small></span>
                        {item.download_url ? (
                          <ProtectedDownloadButton
                            path={item.download_url}
                            filename={`smart_edit_video_${String(item.index).padStart(3, "0")}.mp4`}
                            backendBaseUrl={backendBaseUrl}
                          >
                            <Icon name="download" size={14} />下载
                          </ProtectedDownloadButton>
                        ) : null}
                      </div>
                    </article>
                  ))}
                </div>
              ) : null}
              {task.zip_url ? (
                <ProtectedDownloadButton
                  path={task.zip_url}
                  filename="smart_edit_videos.zip"
                  backendBaseUrl={backendBaseUrl}
                >
                  <Icon name="download" size={15} />下载全部成片
                </ProtectedDownloadButton>
              ) : null}
            </section>
          ) : null}
        </div>
      </div>

      <Dialog
        open={Boolean(pendingKeywordChange)}
        onClose={() => setPendingKeywordChange(null)}
        aria-labelledby="keyword-change-title"
      >
        <DialogTitle>
          <Typography variant="kicker" component="span" className="section-kicker">Keyword Update</Typography>
          <h3 id="keyword-change-title">确认重新解析关键词？</h3>
        </DialogTitle>
        <DialogContent>
          <p>以下关键词已被删除或重命名，其已上传素材将不再保留：</p>
          <strong>{pendingKeywordChange?.removedGroups.map((group) => `${group.keyword}（${group.materials.length} 个）`).join("、")}</strong>
          <small>名称完全相同的关键词仍会自动保留原素材。</small>
        </DialogContent>
        <DialogActions>
          <Button type="button" onClick={() => setPendingKeywordChange(null)}>取消</Button>
          <Button
            type="button"
            color="error"
            variant="contained"
            onClick={() => applyKeywordChange(
              pendingKeywordChange?.nextGroups || [],
              pendingKeywordChange?.duplicateKeywords || []
            )}
            startIcon={<Icon name="refresh" size={15} />}
          >
            确认重新解析
          </Button>
        </DialogActions>
      </Dialog>
    </section>
  );
}
