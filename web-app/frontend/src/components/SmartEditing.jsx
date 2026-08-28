import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import BgmManager from "./BgmManager";
import Icon from "./Icon";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import SubtitleReplacementManager from "./SubtitleReplacementManager";
import { apiFetch, useBackendBaseUrl } from "../lib/backend";
import smartEditingSkill from "../../skills/generate-smart-edit-copy/skill.json";

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
const SMART_EDITING_SKILL_FILENAME = `${smartEditingSkill.id}-${smartEditingSkill.version}.zip`;
const SMART_EDITING_SKILL_DOWNLOAD_URL = `${import.meta.env.BASE_URL}skills/${smartEditingSkill.id}/${SMART_EDITING_SKILL_FILENAME}`;

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

async function responseError(response, fallback) {
  const data = await response.json().catch(() => ({}));
  return data.detail || data.message || fallback || `HTTP ${response.status}`;
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
  const [script, setScript] = useState("");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keywordGroups, setKeywordGroups] = useState([]);
  const [editingKeywords, setEditingKeywords] = useState(true);
  const [keywordNotice, setKeywordNotice] = useState("");
  const [keywordError, setKeywordError] = useState("");
  const [pendingKeywordChange, setPendingKeywordChange] = useState(null);
  const [scriptAtKeywordParse, setScriptAtKeywordParse] = useState(null);
  const [pacing, setPacing] = useState("standard");
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
  const [notice, setNotice] = useState("");
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
    && replacementStatus.issues.length === 0
    && !replacementStatus.hasUnsaved
    && !submitting;

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = null;
  }, []);

  const pollTask = useCallback(async (taskId) => {
    try {
      const response = await apiFetch(
        `/api/smart-editing/tasks/${encodeURIComponent(taskId)}`,
        undefined,
        backendBaseUrl
      );
      if (response.status === 404) {
        localStorage.removeItem(taskStorageKey);
        setTask(null);
        setError("上一次智能剪辑任务已失效，可能是后端服务已经重启。");
        setSubmitting(false);
        return;
      }
      if (!response.ok) throw new Error(await responseError(response, "读取智能剪辑任务失败"));
      const nextTask = await response.json();
      setTask(nextTask);
      setSubmitting(!FINAL_STATUSES.has(nextTask.status));
      if (!FINAL_STATUSES.has(nextTask.status)) {
        pollRef.current = window.setTimeout(() => pollTask(taskId), 1500);
      }
    } catch (pollError) {
      setError(pollError.message || "读取智能剪辑任务失败");
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
        ? `已按首次出现位置合并重复关键词：${duplicateKeywords.join("、")}`
        : `已解析 ${nextGroups.length} 个关键词，顺序将作为剪辑依据。`
    );
  }, [script]);

  const parseKeywordDraft = useCallback((value = keywordDraftRef.current) => {
    const parsed = splitKeywords(value);
    if (!parsed.length) {
      setKeywordError("请粘贴至少 1 个关键词。");
      return false;
    }

    const uniqueKeywords = [];
    const duplicateKeywords = [];
    const seen = new Set();
    for (const keyword of parsed) {
      if (keyword.length > 100) {
        setKeywordError(`关键词“${keyword.slice(0, 20)}”不能超过 100 个字符。`);
        return false;
      }
      const key = normalizeKeywordKey(keyword);
      if (seen.has(key)) {
        if (!duplicateKeywords.includes(keyword)) duplicateKeywords.push(keyword);
        continue;
      }
      seen.add(key);
      uniqueKeywords.push({ keyword, key });
    }
    if (uniqueKeywords.length > MAX_KEYWORDS) {
      setKeywordError(`关键词最多 ${MAX_KEYWORDS} 个，当前解析出 ${uniqueKeywords.length} 个。`);
      return false;
    }

    const previousByKey = new Map(keywordGroups.map((group) => [group.key, group]));
    const nextGroups = uniqueKeywords.map(({ keyword, key }) => {
      const previous = previousByKey.get(key);
      return {
        id: previous?.id || makeId(),
        key,
        keyword,
        materials: previous?.materials || [],
      };
    });
    const nextKeys = new Set(nextGroups.map((group) => group.key));
    const removedGroups = keywordGroups.filter(
      (group) => !nextKeys.has(group.key) && group.materials.length > 0
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
    setNotice("");
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
    if (replacementStatus.issues.length) {
      setError(replacementStatus.issues[0]);
      return;
    }
    if (replacementStatus.hasUnsaved) {
      setError("请先保存全局敏感词替换规则。");
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
      form.append("material_manifest", JSON.stringify(manifest));
      if (selectedBgmId) form.append("bgm_id", selectedBgmId);

      const response = await apiFetch(
        "/api/smart-editing/tasks",
        { method: "POST", body: form },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "创建智能剪辑任务失败"));
      const data = await response.json();
      localStorage.setItem(taskStorageKey, data.task_id);
      setNotice("任务已创建，配音只生成一次，多个画面版本将复用同一音频。");
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
    scriptIssue,
    stopPolling,
    taskStorageKey,
  ]);

  return (
    <section className="workspace-panel smart-editing-panel" aria-label="智能剪辑工作区">
      <section className="smart-skill-card" aria-labelledby="smart-skill-title">
        <span className="smart-skill-icon" aria-hidden="true"><Icon name="wand" size={21} /></span>
        <div className="smart-skill-content">
          <div className="smart-skill-heading">
            <strong id="smart-skill-title">智能剪辑文案与关键词</strong>
            <span className="smart-skill-version">最新版 v{smartEditingSkill.version}</span>
          </div>
          <p>配套 Skill：{smartEditingSkill.summary}。</p>
          <small>请与您当前使用的下载文件名或 <code>skill.json</code> 手动对比版本。</small>
        </div>
        <a
          className="download-action compact-action smart-skill-download"
          href={SMART_EDITING_SKILL_DOWNLOAD_URL}
          download={SMART_EDITING_SKILL_FILENAME}
        >
          <Icon name="download" size={15} />下载 Skill v{smartEditingSkill.version}
        </a>
      </section>

      <div className="smart-editing-grid">
        <div className="smart-editing-column">
          <section className="template-work-section" aria-labelledby="smart-script-title">
            <div className="template-section-heading">
              <span><Icon name="file" size={17} /></span>
              <div><strong id="smart-script-title">文案</strong><small>10-5000 字，敏感词替换不会修改原文或配音</small></div>
            </div>
            <label className="field">
              <span className="field-label">最终文案</span>
              <textarea
                className="control smart-script-input"
                rows={10}
                value={script}
                maxLength={5000}
                placeholder="粘贴 Agent 仿写后的完整文案"
                onChange={(event) => setScript(event.target.value)}
              />
              <small className="field-help">{cleanScript.length}/5000 字符</small>
            </label>
            {scriptChangedAfterKeywords ? (
              <div className="smart-inline-warning"><Icon name="alert" size={14} />文案已修改，请确认 Agent 关键词仍然适用。</div>
            ) : null}
          </section>

          <section className="template-work-section" aria-labelledby="smart-keywords-title">
            <div className="template-section-heading with-actions">
              <span><Icon name="list" size={17} /></span>
              <div><strong id="smart-keywords-title">有序关键词</strong><small>支持逗号、分号和换行，顺序不可拖动</small></div>
              {!editingKeywords && keywordGroups.length ? (
                <button className="secondary-action compact-action" type="button" onClick={beginKeywordEdit}>
                  <Icon name="edit" size={14} />重新编辑关键词
                </button>
              ) : null}
            </div>
            {editingKeywords ? (
              <div className="smart-keyword-editor">
                <textarea
                  className="control"
                  rows={7}
                  value={keywordDraft}
                  placeholder={'例如：\n医院\n医生\n问诊'}
                  onChange={(event) => updateKeywordDraft(event.target.value)}
                  onPaste={handleKeywordPaste}
                  onBlur={() => keywordDraftRef.current.trim() && parseKeywordDraft()}
                />
                <button className="primary-action compact-action" type="button" onClick={() => parseKeywordDraft()}>
                  <Icon name="check" size={14} />解析并确认顺序
                </button>
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
              {PACING_OPTIONS.map((option) => (
                <label className={`smart-pacing-option ${pacing === option.value ? "is-active" : ""}`} key={option.value}>
                  <input
                    type="radio"
                    name="smart-pacing"
                    value={option.value}
                    checked={pacing === option.value}
                    onChange={(event) => setPacing(event.target.value)}
                  />
                  <span><strong>{option.label}</strong><small>{option.description}</small></span>
                </label>
              ))}
            </div>
            <label className="field smart-count-field">
              <span className="field-label">生成数量</span>
              <input
                className="control"
                type="number"
                min="1"
                max="10"
                value={generateCount}
                onChange={(event) => setGenerateCount(Math.max(1, Math.min(10, Number(event.target.value) || 1)))}
              />
              <small className="field-help">同一配音生成 1-10 个不同画面版本</small>
            </label>
          </section>

          <BgmManager
            currentUserId={currentUser?.id}
            selectedBgmId={selectedBgmId}
            onSelectionChange={setSelectedBgmId}
            disabled={submitting}
            idPrefix="smart"
          />

          <section className="template-work-section" aria-labelledby="smart-replacements-title">
            <div className="template-section-heading">
              <span><Icon name="shield" size={17} /></span>
              <div><strong id="smart-replacements-title">敏感词管理</strong><small>与模板量产共享同一套全局规则</small></div>
            </div>
            <SubtitleReplacementManager
              currentUserId={currentUser?.id}
              onStatusChange={setReplacementStatus}
            />
          </section>
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
                              <button
                                className="material-preview-remove"
                                type="button"
                                title={`删除 ${item.file.name}`}
                                aria-label={`删除 ${item.file.name}`}
                                onClick={() => removeMaterial(groupIndex, item.id)}
                              >
                                <Icon name="trash" size={14} />
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="material-empty">该关键词还没有素材，提交前必须上传。</div>
                    )}
                    <label className="secondary-action compact-action smart-material-upload">
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
                    </label>
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
            {notice ? <div className="form-alert completed">{notice}</div> : null}
            <button className="primary-action smart-submit-action" type="button" onClick={submitTask} disabled={!canSubmit}>
              <Icon name={submitting ? "loading" : "wand"} size={17} />
              {submitting ? "正在智能剪辑" : `生成 ${generateCount} 条视频`}
            </button>
          </section>

          {task ? (
            <section className="template-work-section smart-task-section" aria-labelledby="smart-task-title">
              <div className="template-section-heading with-actions">
                <span><Icon name={FINAL_STATUSES.has(task.status) ? "check" : "loading"} size={17} /></span>
                <div>
                  <strong id="smart-task-title">任务结果</strong>
                  <small>{task.message || statusLabel(task.status)} · {task.bgm_name ? `BGM：${task.bgm_name}` : "无 BGM"}</small>
                </div>
                <span className={`status-pill ${task.status}`}>{statusLabel(task.status)}</span>
              </div>
              <div className="task-progress-block">
                <div className="task-progress-meta"><span>处理进度</span><strong>{task.progress || 0}%</strong></div>
                <div className="task-progress-track"><span style={{ width: `${Math.max(0, Math.min(100, task.progress || 0))}%` }} /></div>
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
                            className="secondary-action compact-action"
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
                  className="secondary-action smart-zip-action"
                >
                  <Icon name="download" size={15} />下载全部成片
                </ProtectedDownloadButton>
              ) : null}
            </section>
          ) : null}
        </div>
      </div>

      {pendingKeywordChange ? (
        <div className="modal-backdrop" role="presentation">
          <section className="modal-panel" role="alertdialog" aria-modal="true" aria-labelledby="keyword-change-title">
            <div className="modal-heading">
              <div>
                <span className="section-kicker">Keyword Update</span>
                <h3 id="keyword-change-title">确认重新解析关键词？</h3>
              </div>
            </div>
            <div className="modal-body">
              <p>以下关键词已被删除或重命名，其已上传素材将不再保留：</p>
              <strong>{pendingKeywordChange.removedGroups.map((group) => `${group.keyword}（${group.materials.length} 个）`).join("、")}</strong>
              <small>名称完全相同的关键词仍会自动保留原素材。</small>
            </div>
            <div className="delete-confirm-actions">
              <button className="secondary-action" type="button" onClick={() => setPendingKeywordChange(null)}>取消</button>
              <button
                className="danger-action"
                type="button"
                onClick={() => applyKeywordChange(
                  pendingKeywordChange.nextGroups,
                  pendingKeywordChange.duplicateKeywords
                )}
              >
                <Icon name="refresh" size={15} />确认重新解析
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
