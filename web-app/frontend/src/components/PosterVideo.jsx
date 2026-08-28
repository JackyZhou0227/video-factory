import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import { apiFetch, useBackendBaseUrl } from "../lib/backend";

const PREVIEW_SCALE = 0.3;
const MAX_BATCH_SIZE = 50;
const VIDEO_EXTENSIONS = [".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"];
const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".bmp"];

const OUTPUT_MODES = [
  { value: "video", label: "批量出视频" },
  { value: "image", label: "批量出图片" },
];

const STATUS_LABELS = {
  idle: "等待素材",
  ready: "可以生成",
  pending: "任务排队中",
  running: "正在处理",
  completed: "处理完成",
  partial_failed: "部分完成",
  failed: "处理失败",
};

const DEFAULT_BLOCKS = [
  {
    id: "headline",
    text: "高效工具使用指南",
    x: 16,
    y: 8,
    width: 68,
    fontSize: 58,
    color: "#141413",
    strokeColor: "#000000",
    strokeWidth: 0,
    backgroundColor: "#ffd20a",
    backgroundOpacity: 1,
    paddingX: 28,
    paddingY: 18,
    radius: 14,
    align: "center",
    lineHeight: 1.12,
    fontPath: "",
  },
  {
    id: "subhead",
    text: "三步快速上手",
    x: 23,
    y: 17,
    width: 54,
    fontSize: 48,
    color: "#141413",
    strokeColor: "#000000",
    strokeWidth: 0,
    backgroundColor: "#fffefa",
    backgroundOpacity: 1,
    paddingX: 24,
    paddingY: 16,
    radius: 10,
    align: "center",
    lineHeight: 1.12,
    fontPath: "",
  },
  {
    id: "middle",
    text: "核心功能一目了然",
    x: 20,
    y: 28,
    width: 60,
    fontSize: 42,
    color: "#e82018",
    strokeColor: "#ffffff",
    strokeWidth: 5,
    backgroundColor: "#000000",
    backgroundOpacity: 0,
    paddingX: 0,
    paddingY: 0,
    radius: 0,
    align: "center",
    lineHeight: 1.12,
    fontPath: "",
  },
  {
    id: "bottom",
    text: "适合日常操作、流程说明、产品亮点\n和教程内容。支持批量生成，统一\n画面比例与文字样式，快速完成\n短视频素材制作。",
    x: 10,
    y: 69,
    width: 80,
    fontSize: 42,
    color: "#ffe31a",
    strokeColor: "#000000",
    strokeWidth: 4,
    backgroundColor: "#141413",
    backgroundOpacity: 0.58,
    paddingX: 28,
    paddingY: 20,
    radius: 10,
    align: "center",
    lineHeight: 1.18,
    fontPath: "",
  },
];

function formatFileSize(size) {
  if (!size) return "";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function makeId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function isMediaFile(file, outputMode) {
  const name = file.name.toLowerCase();
  const extensions = outputMode === "image" ? IMAGE_EXTENSIONS : VIDEO_EXTENSIONS;
  const expectedType = outputMode === "image" ? "image/" : "video/";
  return file.type.startsWith(expectedType) || extensions.some((extension) => name.endsWith(extension));
}

function pollTask(taskId, signal, backendBaseUrl) {
  return apiFetch(`/api/poster-videos/task/${taskId}`, { signal }, backendBaseUrl).then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  });
}

function blockPreviewStyle(block) {
  const background =
    Number(block.backgroundOpacity) > 0
      ? `${block.backgroundColor}${Math.round(Number(block.backgroundOpacity) * 255)
          .toString(16)
          .padStart(2, "0")}`
      : "transparent";

  return {
    left: `${block.x}%`,
    top: `${block.y}%`,
    width: `${block.width}%`,
    color: block.color,
    background,
    borderRadius: block.radius * PREVIEW_SCALE,
    padding: `${block.paddingY * PREVIEW_SCALE}px ${block.paddingX * PREVIEW_SCALE}px`,
    fontSize: block.fontSize * PREVIEW_SCALE,
    lineHeight: block.lineHeight,
    textAlign: block.align,
    WebkitTextStroke:
      Number(block.strokeWidth) > 0 ? `${block.strokeWidth * PREVIEW_SCALE}px ${block.strokeColor}` : undefined,
    textShadow:
      Number(block.strokeWidth) > 0 ? `0 0 ${Math.max(1, block.strokeWidth * PREVIEW_SCALE)}px ${block.strokeColor}` : "none",
  };
}

export default function PosterVideo() {
  const backendBaseUrl = useBackendBaseUrl();
  const [outputMode, setOutputMode] = useState("video");
  const [videos, setVideos] = useState([]);
  const [fonts, setFonts] = useState([]);
  const [blocks, setBlocks] = useState(DEFAULT_BLOCKS);
  const [taskStatus, setTaskStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const [items, setItems] = useState([]);
  const [zipUrl, setZipUrl] = useState("");
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);

  const videoInputRef = useRef(null);
  const pollRef = useRef(null);
  const mediaItemsRef = useRef([]);

  const isImageMode = outputMode === "image";
  const mediaLabel = isImageMode ? "图片" : "视频";
  const outputLabel = isImageMode ? "大字报图片" : "大字报视频";
  const acceptTypes = isImageMode ? "image/*" : "video/*";

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/poster-videos/fonts", undefined, backendBaseUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((list) => {
        if (cancelled) return;
        const nextFonts = Array.isArray(list) ? list : [];
        setFonts(nextFonts);
        setBlocks((current) =>
          current.map((block) => ({
            ...block,
            fontPath: block.fontPath || nextFonts[0]?.path || "",
          }))
        );
      })
      .catch(() => {
        if (!cancelled) setFonts([]);
      });
    return () => {
      cancelled = true;
    };
  }, [backendBaseUrl]);

  useEffect(() => {
    mediaItemsRef.current = videos;
  }, [videos]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
      mediaItemsRef.current.forEach((item) => URL.revokeObjectURL(item.localUrl));
    };
  }, []);

  const canGenerate = Boolean(videos.length > 0 && blocks.some((block) => block.text.trim()) && !generating);

  const videoPanelStatus = useMemo(() => {
    if (["pending", "running", "completed", "partial_failed", "failed"].includes(taskStatus)) {
      return taskStatus;
    }
    if (videos.length > 0) return "ready";
    return "idle";
  }, [taskStatus, videos.length]);

  const pipelineItems = [
    {
      label: `${mediaLabel}素材`,
      detail: videos.length ? `${videos.length} 个${mediaLabel}已选择` : "等待批量上传",
      state: videos.length ? "completed" : "idle",
      icon: isImageMode ? "image" : "video",
    },
    {
      label: "大字报模板",
      detail: `${blocks.filter((block) => block.text.trim()).length} 个文字块`,
      state: blocks.some((block) => block.text.trim()) ? "completed" : "idle",
      icon: "type",
    },
    {
      label: "本地批处理",
      detail:
        taskStatus === "completed"
          ? "成品可下载"
          : taskStatus === "partial_failed"
            ? "部分成品可下载"
            : taskStatus === "failed"
              ? "需要检查失败项"
              : isImageMode
                ? "本地图片合成"
                : "FFmpeg 转码",
      state: ["pending", "running"].includes(taskStatus) ? "running" : taskStatus,
      icon: "wand",
    },
  ];

  const resetTask = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    setTaskStatus("idle");
    setProgress(0);
    setStatusMsg("");
    setItems([]);
    setZipUrl("");
    setError("");
    setGenerating(false);
  }, []);

  const addVideoFiles = useCallback(
    (files) => {
      const selected = Array.from(files || []).filter((file) => isMediaFile(file, outputMode));
      if (!selected.length) return;

      setVideos((current) => {
        const existingKeys = new Set(current.map((item) => `${item.file.name}:${item.file.size}:${item.file.lastModified}`));
        const additions = selected
          .filter((file) => !existingKeys.has(`${file.name}:${file.size}:${file.lastModified}`))
          .slice(0, Math.max(0, MAX_BATCH_SIZE - current.length))
          .map((file) => ({
            id: makeId(),
            file,
            localUrl: URL.createObjectURL(file),
          }));

        if (!additions.length) return current;
        return [...current, ...additions];
      });

      if (videoInputRef.current) videoInputRef.current.value = "";
      resetTask();
    },
    [outputMode, resetTask]
  );

  const handleVideoChange = useCallback(
    (event) => {
      addVideoFiles(event.target.files);
    },
    [addVideoFiles]
  );

  const handleVideoDrop = useCallback(
    (event) => {
      event.preventDefault();
      addVideoFiles(event.dataTransfer.files);
    },
    [addVideoFiles]
  );

  const clearVideos = useCallback(() => {
    setVideos((current) => {
      current.forEach((item) => URL.revokeObjectURL(item.localUrl));
      return [];
    });
    if (videoInputRef.current) videoInputRef.current.value = "";
    resetTask();
  }, [resetTask]);

  const removeVideo = useCallback(
    (id) => {
      setVideos((current) => {
        const target = current.find((item) => item.id === id);
        if (target) URL.revokeObjectURL(target.localUrl);
        return current.filter((item) => item.id !== id);
      });
      resetTask();
    },
    [resetTask]
  );

  const updateBlock = useCallback((id, patch) => {
    setBlocks((current) => current.map((block) => (block.id === id ? { ...block, ...patch } : block)));
    setTaskStatus((current) => (current === "completed" || current === "failed" ? "idle" : current));
    setZipUrl("");
    setError("");
  }, []);

  const centerBlockX = useCallback(
    (block) => {
      const centeredX = Math.max(0, Math.min(90, Math.round((100 - Number(block.width || 0)) / 2)));
      updateBlock(block.id, { x: centeredX });
    },
    [updateBlock]
  );

  const addBlock = useCallback(() => {
    const firstFont = fonts[0]?.path || "";
    setBlocks((current) => [
      ...current,
      {
        ...DEFAULT_BLOCKS[1],
        id: makeId(),
        text: "新文字块",
        y: 38,
        fontPath: firstFont,
      },
    ]);
  }, [fonts]);

  const removeBlock = useCallback((id) => {
    setBlocks((current) => current.filter((block) => block.id !== id));
  }, []);

  const handleOutputModeChange = useCallback(
    (nextMode) => {
      if (nextMode === outputMode) return;
      setOutputMode(nextMode);
      setVideos((current) => {
        current.forEach((item) => URL.revokeObjectURL(item.localUrl));
        return [];
      });
      if (videoInputRef.current) videoInputRef.current.value = "";
      resetTask();
    },
    [outputMode, resetTask]
  );

  const handleGenerate = useCallback(async () => {
    if (!canGenerate) return;

    setGenerating(true);
    setError("");
    setZipUrl("");
    setItems([]);
    setProgress(0);
    setTaskStatus("pending");
    setStatusMsg("正在上传视频并创建批量任务...");

    try {
      const formData = new FormData();
      videos.forEach((item) => formData.append("assets", item.file));
      formData.append("media_type", outputMode);
      formData.append("template", JSON.stringify({ blocks }));

      const response = await apiFetch(
        "/api/poster-videos/generate",
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
      setStatusMsg(`${mediaLabel}已上传，正在本地处理...`);

      const controller = new AbortController();
      const poll = async () => {
        try {
          const data = await pollTask(taskId, controller.signal, backendBaseUrl);
          setTaskStatus(data.status || "running");
          setProgress(data.progress ?? 0);
          setStatusMsg(data.message || "");
          setItems(Array.isArray(data.items) ? data.items : []);
          setZipUrl(data.zip_url || "");

          if (["completed", "partial_failed", "failed"].includes(data.status)) {
            setGenerating(false);
            if (data.status === "failed") setError(data.error || data.message || "批量处理失败");
            return;
          }

          pollRef.current = setTimeout(poll, 1800);
        } catch (err) {
          if (err.name === "AbortError") return;
          setTaskStatus("failed");
          setError(err.message);
          setGenerating(false);
        }
      };

      pollRef.current = setTimeout(poll, 900);
    } catch (err) {
      setTaskStatus("failed");
      setError(err.message);
      setGenerating(false);
    }
  }, [backendBaseUrl, blocks, canGenerate, mediaLabel, outputMode, videos]);

  return (
    <>
      <section className="workspace-panel production-panel" aria-label="大字报视频制作工作区">
        <div className="pipeline-strip poster-video-pipeline" aria-label="大字报视频流程状态">
          {pipelineItems.map((item, index) => (
            <div key={item.label} className={`pipeline-step ${item.state}`}>
              <span className="pipeline-index">
                <Icon name={item.icon} size={14} />
                <span>{String(index + 1).padStart(2, "0")}</span>
              </span>
              <span className="pipeline-copy">
                <strong>{item.label}</strong>
                <span>{item.detail}</span>
              </span>
            </div>
          ))}
        </div>

        <div className="poster-layout">
          <div className="poster-controls">
            <div className="workflow-card">
              <div className="control-section-heading">
                <span>00</span>
                <strong>输出类型</strong>
              </div>
              <div className="segmented-control">
                {OUTPUT_MODES.map((mode) => (
                  <button
                    key={mode.value}
                    className={`segment ${outputMode === mode.value ? "is-active" : ""}`}
                    type="button"
                    onClick={() => handleOutputModeChange(mode.value)}
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="workflow-card">
              <div className="control-section-heading">
                <span>01</span>
                <strong>批量{mediaLabel}素材</strong>
              </div>

              <label
                className={`upload-dropzone compact poster-upload ${videos.length ? "is-filled" : ""}`}
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleVideoDrop}
              >
                <span className="upload-placeholder">
                  <Icon name={videos.length ? "check" : "upload"} size={24} />
                  <strong>{videos.length ? `已加入 ${videos.length} 个${mediaLabel}` : `选择或拖入多个${mediaLabel}`}</strong>
                  <small>可一次多选，也可重复添加；最多 {MAX_BATCH_SIZE} 个</small>
                </span>
                <input
                  ref={videoInputRef}
                  name="assets"
                  type="file"
                  accept={acceptTypes}
                  multiple
                  onChange={handleVideoChange}
                />
              </label>

              {videos.length > 0 && (
                <div className="poster-file-list">
                  {videos.map((item) => (
                    <div className="poster-file-row" key={item.id}>
                      <Icon name="video" size={15} />
                      <span title={item.file.name}>{item.file.name}</span>
                      <small>{formatFileSize(item.file.size)}</small>
                      <button className="text-button" type="button" onClick={() => removeVideo(item.id)}>
                        移除
                      </button>
                    </div>
                  ))}
                  <button className="text-button" type="button" onClick={clearVideos}>
                    清空素材
                  </button>
                </div>
              )}
            </div>

            <div className="workflow-card">
              <div className="control-section-heading">
                <span>02</span>
                <strong>文字块模板</strong>
              </div>

              <div className="poster-block-list">
                {blocks.map((block, index) => (
                  <div className="poster-block-card" key={block.id}>
                    <div className="poster-block-heading">
                      <strong>文字块 {index + 1}</strong>
                      <button className="text-button" type="button" onClick={() => removeBlock(block.id)}>
                        删除
                      </button>
                    </div>

                    <label className="field">
                      <span className="field-label">内容</span>
                      <textarea
                        className="control textarea poster-block-text"
                        rows={3}
                        value={block.text}
                        onChange={(event) => updateBlock(block.id, { text: event.target.value })}
                      />
                    </label>

                    <div className="poster-control-grid">
                      <label className="field">
                        <span className="field-label">字体</span>
                        <select
                          className="control"
                          value={block.fontPath}
                          onChange={(event) => updateBlock(block.id, { fontPath: event.target.value })}
                        >
                          {fonts.length === 0 && <option value="">系统默认字体</option>}
                          {fonts.map((font) => (
                            <option key={font.path} value={font.path}>
                              {font.label}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="field">
                        <span className="field-label">对齐</span>
                        <select
                          className="control"
                          value={block.align}
                          onChange={(event) => updateBlock(block.id, { align: event.target.value })}
                        >
                          <option value="left">左对齐</option>
                          <option value="center">居中</option>
                          <option value="right">右对齐</option>
                        </select>
                      </label>
                    </div>

                    <div className="poster-control-grid three">
                      <label className="field">
                        <span className="field-label with-inline-action">
                          <span>X {block.x}%</span>
                          <button className="mini-text-action" type="button" onClick={() => centerBlockX(block)}>
                            一键居中
                          </button>
                        </span>
                        <input className="speed-slider" type="range" min="0" max="90" value={block.x} onChange={(event) => updateBlock(block.id, { x: Number(event.target.value) })} />
                      </label>
                      <label className="field">
                        <span className="field-label">Y {block.y}%</span>
                        <input className="speed-slider" type="range" min="0" max="92" value={block.y} onChange={(event) => updateBlock(block.id, { y: Number(event.target.value) })} />
                      </label>
                      <label className="field">
                        <span className="field-label">宽度 {block.width}%</span>
                        <input className="speed-slider" type="range" min="20" max="100" value={block.width} onChange={(event) => updateBlock(block.id, { width: Number(event.target.value) })} />
                      </label>
                    </div>

                    <div className="poster-control-grid three">
                      <label className="field">
                        <span className="field-label">字号 {block.fontSize}</span>
                        <input className="speed-slider" type="range" min="24" max="120" value={block.fontSize} onChange={(event) => updateBlock(block.id, { fontSize: Number(event.target.value) })} />
                      </label>
                      <label className="field">
                        <span className="field-label">描边 {block.strokeWidth}</span>
                        <input className="speed-slider" type="range" min="0" max="12" value={block.strokeWidth} onChange={(event) => updateBlock(block.id, { strokeWidth: Number(event.target.value) })} />
                      </label>
                      <label className="field">
                        <span className="field-label">背景 {Math.round(block.backgroundOpacity * 100)}%</span>
                        <input className="speed-slider" type="range" min="0" max="1" step="0.05" value={block.backgroundOpacity} onChange={(event) => updateBlock(block.id, { backgroundOpacity: Number(event.target.value) })} />
                      </label>
                    </div>

                    <div className="poster-swatch-grid">
                      <label>
                        <span>文字</span>
                        <input type="color" value={block.color} onChange={(event) => updateBlock(block.id, { color: event.target.value })} />
                      </label>
                      <label>
                        <span>描边</span>
                        <input type="color" value={block.strokeColor} onChange={(event) => updateBlock(block.id, { strokeColor: event.target.value })} />
                      </label>
                      <label>
                        <span>背景</span>
                        <input type="color" value={block.backgroundColor} onChange={(event) => updateBlock(block.id, { backgroundColor: event.target.value })} />
                      </label>
                    </div>
                  </div>
                ))}
              </div>

              <button className="secondary-action" type="button" onClick={addBlock}>
                <Icon name="sparkles" size={16} />
                新增文字块
              </button>
            </div>
          </div>

          <div className="poster-preview-column">
            <div className="workflow-card poster-preview-card">
              <div className="control-section-heading">
                <span>03</span>
                <strong>9:16 效果预览</strong>
              </div>

              <div className="poster-preview-stage">
                <div className="poster-phone-frame">
                  <div className="poster-video-bg">
                    {videos[0]?.localUrl ? (
                      isImageMode ? (
                        <img src={videos[0].localUrl} alt="预览素材" />
                      ) : (
                        <video src={videos[0].localUrl} muted playsInline />
                      )
                    ) : (
                      <div className="poster-empty-bg">
                        <Icon name={isImageMode ? "image" : "video"} size={28} />
                      </div>
                    )}
                    {blocks.map((block) => (
                      <div className="poster-preview-block" key={block.id} style={blockPreviewStyle(block)}>
                        {block.text}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <button className="primary-action" type="button" disabled={!canGenerate} onClick={handleGenerate}>
                <Icon name={generating ? "loading" : "wand"} size={16} />
                {generating ? "正在批量生成" : `生成${outputLabel}`}
              </button>

              {(taskStatus === "running" || taskStatus === "pending") && (
                <div className="progress-area" aria-label="批量处理进度">
                  <div className="progress-meta">
                    <span>{statusMsg}</span>
                    <strong>{progress}%</strong>
                  </div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${progress}%` }} />
                  </div>
                </div>
              )}

              {error && <div className="form-alert failed">{error}</div>}
            </div>
          </div>
        </div>
      </section>

      <section className="workspace-panel output-panel" aria-labelledby="poster-output-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">输出</span>
            <h2 id="poster-output-title">批量生成结果</h2>
          </div>
          <span className={`status-pill ${videoPanelStatus}`}>
            <Icon
              name={
                ["failed", "partial_failed"].includes(videoPanelStatus)
                  ? "alert"
                  : videoPanelStatus === "completed"
                    ? "check"
                    : ["running", "pending"].includes(videoPanelStatus)
                      ? "loading"
                      : "gauge"
              }
              size={14}
            />
            {STATUS_LABELS[videoPanelStatus]}
          </span>
        </div>

        <div className="poster-result-shell">
          <div className="video-status-card poster-result-summary">
            <span className="section-kicker with-icon">
              <Icon name="video" size={13} />
              Batch
            </span>
            <h3>{STATUS_LABELS[videoPanelStatus]}</h3>
            <p>{statusMsg || `上传${mediaLabel}并确认模板后，可以开始本地批量生成。`}</p>
            {zipUrl && (
              <ProtectedDownloadButton
                className="download-action"
                path={zipUrl}
                filename={isImageMode ? "poster_images.zip" : "poster_videos.zip"}
                backendBaseUrl={backendBaseUrl}
              >
                <Icon name="download" size={16} />
                下载全部 ZIP
              </ProtectedDownloadButton>
            )}
          </div>

          <div className="poster-result-list">
            {items.length > 0 ? (
              items.map((item) => (
                <div className={`poster-result-item ${item.status}`} key={item.id}>
                  <div className="poster-result-main">
                    <span className={`status-dot ${item.status}`} />
                    <div>
                      <strong title={item.filename}>{item.filename}</strong>
                      <span>{item.error || item.message}</span>
                    </div>
                  </div>
                  {(item.asset_url || item.video_url || item.image_url) && (
                    <div className="poster-result-actions">
                      <ProtectedMedia
                        path={item.asset_url || item.video_url || item.image_url}
                        kind={isImageMode ? "image" : "video"}
                        backendBaseUrl={backendBaseUrl}
                        alt={item.filename}
                      />
                      <ProtectedDownloadButton
                        className="secondary-link-action"
                        path={item.asset_url || item.video_url || item.image_url}
                        filename={item.filename}
                        backendBaseUrl={backendBaseUrl}
                      >
                        <Icon name="download" size={15} />
                        下载
                      </ProtectedDownloadButton>
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div className="empty-state poster-empty-result">
                <div className={`state-orb ${videoPanelStatus}`} aria-hidden="true">
                  <Icon name={isImageMode ? "image" : "video"} size={28} />
                </div>
                <h3>暂无成品</h3>
                <p>完成批量处理后，每个{mediaLabel}会显示预览和单独下载入口。</p>
              </div>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
