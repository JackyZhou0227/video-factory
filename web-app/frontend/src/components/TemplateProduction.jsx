import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";
import { apiFetch, resolveBackendAssetUrl, useBackendBaseUrl } from "../lib/backend";

const TEMPLATES = [
  {
    id: "zhongyi-xunfang",
    name: "中医寻访",
    description: "用问诊和诊所画面生成真实、有温度的寻访口播。",
    ratio: "9:16",
    supportsSubtitleReplacements: true,
    variables: [
      { id: "address", label: "医生地址", placeholder: "例如：湖北阳新的一条老街", required: true },
      { id: "name", label: "医生称呼", placeholder: "例如：马医生", required: true },
      { id: "specialty", label: "医生专长", placeholder: "例如：中医内科、慢性病调理", required: true },
      { id: "feature", label: "医生特点", placeholder: "例如：三代中医世家", required: false },
    ],
    requirements: [
      { id: "doctor-scene", name: "中医师问诊画面", type: "video", min: 1, max: 5 },
      { id: "clinic-scene", name: "诊所环境展示", type: "video", min: 1, max: 3 },
    ],
  },
  {
    id: "doctor-intro",
    name: "医生介绍",
    description: "组合医生形象和医院环境，批量制作专业介绍视频。",
    ratio: "9:16",
    supportsSubtitleReplacements: false,
    variables: [
      { id: "doctor-name", label: "医生姓名", placeholder: "例如：张医生", required: true },
      { id: "hospital", label: "所在医院", placeholder: "例如：北京协和医院", required: true },
      { id: "department", label: "科室", placeholder: "例如：心内科", required: true },
      { id: "specialty", label: "专业特长", placeholder: "例如：冠心病、高血压诊疗", required: true },
    ],
    requirements: [
      { id: "doctor-image", name: "医生形象照", type: "image", min: 1, max: 3 },
      { id: "hospital-scene", name: "医院环境", type: "video", min: 1, max: 3 },
    ],
  },
];

const RATIO_OPTIONS = ["9:16", "16:9", "1:1", "3:4"];
const FINAL_STATUSES = new Set(["completed", "failed"]);
const MAX_SUBTITLE_REPLACEMENTS = 30;

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

export default function TemplateProduction({ currentUser }) {
  const backendBaseUrl = useBackendBaseUrl();
  const [templateId, setTemplateId] = useState(TEMPLATES[0].id);
  const [variables, setVariables] = useState({});
  const [materials, setMaterials] = useState({});
  const [scriptCandidates, setScriptCandidates] = useState([]);
  const [selectedCandidateId, setSelectedCandidateId] = useState("");
  const [finalScript, setFinalScript] = useState("");
  const [subtitleReplacements, setSubtitleReplacements] = useState([]);
  const [rewritingCandidateId, setRewritingCandidateId] = useState("");
  const [ratio, setRatio] = useState("9:16");
  const [generateCount, setGenerateCount] = useState(5);
  const [generatingScripts, setGeneratingScripts] = useState(false);
  const [task, setTask] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const pollRef = useRef(null);

  const selectedTemplate = useMemo(
    () => TEMPLATES.find((item) => item.id === templateId) || TEMPLATES[0],
    [templateId]
  );
  const taskStorageKey = `vf.templateProductionTask.v1.${currentUser?.id || "local"}`;

  const materialIssues = useMemo(() => {
    return selectedTemplate.requirements.flatMap((requirement) => {
      const count = materials[requirement.id]?.length || 0;
      if (count < requirement.min) return [`${requirement.name}至少需要 ${requirement.min} 个素材`];
      if (count > requirement.max) return [`${requirement.name}最多选择 ${requirement.max} 个素材`];
      return [];
    });
  }, [materials, selectedTemplate]);

  const variablesReady = selectedTemplate.variables.every(
    (field) => !field.required || String(variables[field.id] || "").trim()
  );
  const subtitleReplacementIssues = useMemo(() => {
    if (!selectedTemplate.supportsSubtitleReplacements) return [];
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
  }, [selectedTemplate.supportsSubtitleReplacements, subtitleReplacements]);
  const normalizedSubtitleReplacements = useMemo(
    () => subtitleReplacements.map((item) => ({
      source: item.source.trim(),
      replacement: item.replacement.trim(),
    })),
    [subtitleReplacements]
  );
  const canSubmit = variablesReady
    && materialIssues.length === 0
    && subtitleReplacementIssues.length === 0
    && Boolean(finalScript.trim())
    && !submitting;

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = null;
  }, []);

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
      stopPolling();
      localStorage.removeItem(taskStorageKey);
      setTemplateId(nextTemplate.id);
      setRatio(nextTemplate.ratio);
      setVariables({});
      setMaterials({});
      setScriptCandidates([]);
      setSelectedCandidateId("");
      setFinalScript("");
      setSubtitleReplacements([]);
      setRewritingCandidateId("");
      setTask(null);
      setError("");
      setNotice("");
    },
    [stopPolling, submitting, taskStorageKey]
  );

  const addMaterialFiles = useCallback((requirement, fileList) => {
    const acceptedPrefix = requirement.type === "image" ? "image/" : "video/";
    const selected = Array.from(fileList || []).filter((file) => file.type.startsWith(acceptedPrefix));
    if (!selected.length) return;
    setMaterials((current) => {
      const existing = current[requirement.id] || [];
      const available = Math.max(0, requirement.max - existing.length);
      const additions = selected.slice(0, available).map((file) => ({ id: makeId(), file }));
      return { ...current, [requirement.id]: [...existing, ...additions] };
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
    setSubtitleReplacements((current) => {
      if (current.length >= MAX_SUBTITLE_REPLACEMENTS) return current;
      return [...current, { id: makeId(), source: "", replacement: "" }];
    });
    setError("");
    setNotice("");
  }, []);

  const updateSubtitleReplacement = useCallback((id, field, value) => {
    setSubtitleReplacements((current) => current.map((item) => (
      item.id === id ? { ...item, [field]: value } : item
    )));
    setError("");
    setNotice("");
  }, []);

  const removeSubtitleReplacement = useCallback((id) => {
    setSubtitleReplacements((current) => current.filter((item) => item.id !== id));
    setError("");
    setNotice("");
  }, []);

  const generateAiScripts = useCallback(async () => {
    setError("");
    setNotice("");
    if (!variablesReady) {
      setError("请先填写模板的必填信息。");
      return;
    }
    setGeneratingScripts(true);
    try {
      const materialContext = Object.fromEntries(
        selectedTemplate.requirements.map((requirement) => [requirement.id, materials[requirement.id]?.length || 0])
      );
      const response = await apiFetch(
        "/api/template-production/scripts/generate",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            template_id: templateId,
            variables,
            count: 3,
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
  }, [backendBaseUrl, materials, selectedTemplate, templateId, variables, variablesReady]);

  const selectCandidate = useCallback((candidate) => {
    setSelectedCandidateId(candidate.id);
    setFinalScript(candidate.content);
    setError("");
    setNotice("已将候选文案填入最终文案。");
  }, []);

  const rewriteCandidate = useCallback(async (candidate) => {
    setRewritingCandidateId(candidate.id);
    setError("");
    setNotice("");
    try {
      const materialContext = Object.fromEntries(
        selectedTemplate.requirements.map((requirement) => [requirement.id, materials[requirement.id]?.length || 0])
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
      setError(subtitleReplacementIssues[0] || materialIssues[0] || "请完善素材和文案后再生成。");
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
      selectedTemplate.requirements.forEach((requirement) => {
        (materials[requirement.id] || []).forEach((item) => {
          form.append("materials", item.file, item.file.name);
          manifest.push({
            requirement_id: requirement.id,
            file_index: fileIndex,
            media_type: requirement.type,
            name: item.file.name,
          });
          fileIndex += 1;
        });
      });
      form.append("template_id", templateId);
      form.append("scripts", JSON.stringify([cleanScript]));
      form.append("generate_count", String(generateCount));
      form.append("video_config", JSON.stringify({ ratio }));
      form.append("subtitle_replacements", JSON.stringify(normalizedSubtitleReplacements));
      form.append("material_manifest", JSON.stringify(manifest));

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
    generateCount,
    materialIssues,
    materials,
    normalizedSubtitleReplacements,
    pollTask,
    ratio,
    finalScript,
    selectedTemplate,
    stopPolling,
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
        <span className={`status-pill ${task?.status || (canSubmit ? "ready" : "pending")}`}>
          <Icon name={submitting ? "loading" : task?.status === "completed" ? "check" : "template"} size={14} />
          {task ? statusLabel(task.status) : canSubmit ? "可以生成" : "准备素材"}
        </span>
      </div>

      <div className="template-selector" role="tablist" aria-label="模板选择">
        {TEMPLATES.map((item) => (
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
            <span><strong>{item.name}</strong><small>{item.description}</small></span>
            {item.id === templateId ? <Icon name="check" size={17} /> : null}
          </button>
        ))}
      </div>

      <div className="template-production-grid">
        <div className="template-production-column">
          <section className="template-work-section" aria-labelledby="template-info-title">
            <div className="template-section-heading">
              <span><Icon name="edit" size={17} /></span>
              <div><strong id="template-info-title">内容信息</strong><small>用于生成匹配当前模板的口播文案</small></div>
            </div>
            <div className="field-grid template-variable-grid">
              {selectedTemplate.variables.map((field) => (
                <label className="field" key={field.id} htmlFor={`template-variable-${field.id}`}>
                  <span className="field-label">{field.label}{field.required ? " *" : ""}</span>
                  <input
                    className="control"
                    id={`template-variable-${field.id}`}
                    value={variables[field.id] || ""}
                    placeholder={field.placeholder}
                    onChange={(event) => setVariables((current) => ({ ...current, [field.id]: event.target.value }))}
                  />
                </label>
              ))}
            </div>
          </section>

          <section className="template-work-section" aria-labelledby="template-material-title">
            <div className="template-section-heading">
              <span><Icon name="upload" size={17} /></span>
              <div><strong id="template-material-title">上传素材</strong><small>素材会在每条成片中重新编排</small></div>
            </div>
            <div className="material-requirement-list">
              {selectedTemplate.requirements.map((requirement) => {
                const items = materials[requirement.id] || [];
                return (
                  <div className="material-requirement" key={requirement.id}>
                    <div className="material-requirement-heading">
                      <div>
                        <strong>{requirement.name}</strong>
                        <span>
                          {requirement.type === "image" ? "图片" : "视频"} · {requirement.min > 0 ? `${requirement.min}-${requirement.max} 个` : `选填，最多 ${requirement.max} 个`}
                        </span>
                      </div>
                      <label className="secondary-action compact-action">
                        <Icon name="upload" size={15} />选择文件
                        <input
                          hidden
                          multiple
                          type="file"
                          accept={requirement.type === "image" ? "image/*" : "video/*"}
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
                              mediaType={requirement.type}
                              label={`第 ${index + 1} 个${requirement.type === "image" ? "图片" : "视频"}素材`}
                            />
                            <div className="material-preview-footer">
                              <span><Icon name={requirement.type} size={14} />{formatFileSize(item.file.size)}</span>
                              <button
                                className="material-preview-remove"
                                type="button"
                                title={`移除第 ${index + 1} 个素材`}
                                aria-label={`移除第 ${index + 1} 个素材`}
                                onClick={() => removeMaterial(requirement.id, item.id)}
                              >
                                <Icon name="x" size={15} />
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="material-empty">尚未选择{requirement.type === "image" ? "图片" : "视频"}</div>
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
                <span>填写内容信息后生成三条候选文案。</span>
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
            {selectedTemplate.supportsSubtitleReplacements ? (
              <div className="subtitle-replacement-editor">
                <div className="subtitle-replacement-heading">
                  <div>
                    <strong>字幕敏感词替换</strong>
                    <small>只修改成片字幕，配音仍使用最终文案原文</small>
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
                    {subtitleReplacements.map((item, index) => (
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
                          />
                        </label>
                        <button
                          className="subtitle-replacement-remove"
                          type="button"
                          title={`删除第 ${index + 1} 条字幕替换`}
                          aria-label={`删除第 ${index + 1} 条字幕替换`}
                          onClick={() => removeSubtitleReplacement(item.id)}
                        >
                          <Icon name="trash" size={15} />
                        </button>
                      </div>
                    ))}
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
              </div>
            ) : null}
          </section>

          <section className="template-work-section" aria-labelledby="template-output-config-title">
            <div className="template-section-heading">
              <span><Icon name="sliders" size={17} /></span>
              <div><strong id="template-output-config-title">生成设置</strong><small>成片规格</small></div>
            </div>
            <div className="template-config-grid">
              <div className="field ratio-field">
                <span className="field-label">画面比例</span>
                <div className="segmented-control compact-segments" role="radiogroup" aria-label="画面比例">
                  {RATIO_OPTIONS.map((item) => (
                    <button key={item} type="button" className={`segment ${ratio === item ? "is-active" : ""}`} onClick={() => setRatio(item)}>{item}</button>
                  ))}
                </div>
              </div>
              <label className="field count-field">
                <span className="field-label">生成数量</span>
                <input className="control" type="number" min="1" max="50" value={generateCount} onChange={(event) => setGenerateCount(Math.max(1, Math.min(50, Number(event.target.value) || 1)))} />
              </label>
            </div>
          </section>

          {error ? <div className="form-alert failed">{error}</div> : null}
          {notice ? <div className="form-alert completed">{notice}</div> : null}
          {materialIssues.length && finalScript.trim() ? <div className="template-inline-warning">{materialIssues[0]}</div> : null}

          <button className="primary-action template-submit-action" type="button" onClick={submitTask} disabled={!canSubmit}>
            <Icon name={submitting ? "loading" : "wand"} size={17} />
            {submitting ? "正在批量生成" : `生成 ${generateCount} 条视频`}
          </button>
        </div>
      </div>

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
