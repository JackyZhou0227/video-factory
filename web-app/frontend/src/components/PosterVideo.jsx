import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Slider from "@mui/material/Slider";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import LinearProgress from "@mui/material/LinearProgress";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import ToggleButton from "@mui/material/ToggleButton";
import Box from "@mui/material/Box";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import Switch from "@mui/material/Switch";
import AudioFileOutlined from "@mui/icons-material/AudioFileOutlined";
import ImageOutlined from "@mui/icons-material/ImageOutlined";
import VideoFileOutlined from "@mui/icons-material/VideoFileOutlined";
import DeleteOutlined from "@mui/icons-material/DeleteOutlined";
import UploadFileOutlined from "@mui/icons-material/UploadFileOutlined";
import { statusChipColors } from "../theme";
import BgmManager from "./BgmManager";
import Icon from "./Icon";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import { apiJson, useBackendBaseUrl } from "../lib/backend";
import {
  classifySource,
  estimatePosterAsset,
  IMAGE_EXTENSIONS,
  isTerminalPosterStatus,
  MAX_BATCH_SIZE,
  NARRATION_EXTENSIONS,
  narrationFileError,
  posterDownloadFilename,
  selectSourceFiles,
  sourceFileError,
  VIDEO_EXTENSIONS,
} from "../lib/posterVideo";

const PREVIEW_SCALE = 0.3;

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
  cancelled: "已取消",
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

function formatDuration(value) {
  return Number.isFinite(Number(value)) && Number(value) > 0 ? `${Number(value).toFixed(1)} 秒` : "后端待确认";
}

function formatSpeed(value) {
  return Number.isFinite(Number(value)) && Number(value) > 0 ? `${Number(value).toFixed(2)}x` : "后端待确认";
}

function pollTask(taskId, signal, backendBaseUrl) {
  return apiJson(`/api/poster-videos/task/${taskId}`, { signal, silentError: true }, backendBaseUrl);
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

export default function PosterVideo({ currentUser }) {
  const backendBaseUrl = useBackendBaseUrl();
  const [outputMode, setOutputMode] = useState("video");
  const [videos, setVideos] = useState([]);
  const [previewId, setPreviewId] = useState("");
  const [fonts, setFonts] = useState([]);
  const [blocks, setBlocks] = useState(DEFAULT_BLOCKS);
  const [taskStatus, setTaskStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const [items, setItems] = useState([]);
  const [zipUrl, setZipUrl] = useState("");
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [narration, setNarration] = useState(null);
  const [narrationError, setNarrationError] = useState("");
  const [selectedBgmId, setSelectedBgmId] = useState("");
  const [selectedBgmTrack, setSelectedBgmTrack] = useState(null);
  const [bgmBusy, setBgmBusy] = useState(false);
  const [muteOriginalAudio, setMuteOriginalAudio] = useState(true);

  const videoInputRef = useRef(null);
  const narrationInputRef = useRef(null);
  const narrationRef = useRef(null);
  const pollRef = useRef(null);
  const mediaItemsRef = useRef([]);
  const requestRef = useRef({ token: 0, controller: null });
  const generatingRef = useRef(false);
  const bgmBusyRef = useRef(false);

  const isImageMode = outputMode === "image";
  const mediaLabel = isImageMode ? "图片" : "图片 / 视频";
  const outputLabel = isImageMode ? "大字报图片" : "大字报视频";
  const acceptTypes = isImageMode
    ? `image/*,${IMAGE_EXTENSIONS.join(",")}`
    : `image/*,video/*,${[...IMAGE_EXTENSIONS, ...VIDEO_EXTENSIONS].join(",")}`;
  const hasVideoSources = videos.some((item) => item.sourceType === "video");
  const previewSource = videos.find((item) => item.id === previewId) || videos[0];
  const estimates = useMemo(() => videos.map((item) => estimatePosterAsset(item, {
    narration,
    bgm: selectedBgmId ? selectedBgmTrack || {} : null,
  })), [narration, selectedBgmId, selectedBgmTrack, videos]);
  const audioRequired = !isImageMode && estimates.some((estimate) => estimate.requiresAudio);

  useEffect(() => {
    let cancelled = false;
    apiJson("/api/poster-videos/fonts", { silentError: true }, backendBaseUrl)
      .then((list) => {
        if (cancelled) return;
        const nextFonts = Array.isArray(list) ? list : [];
        setFonts(nextFonts);
        if (generatingRef.current) return;
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

  const cancelRequest = useCallback(() => {
    clearTimeout(pollRef.current);
    pollRef.current = null;
    requestRef.current.controller?.abort();
    requestRef.current = { token: requestRef.current.token + 1, controller: null };
    generatingRef.current = false;
  }, []);

  useEffect(() => () => {
    cancelRequest();
    mediaItemsRef.current.forEach((item) => URL.revokeObjectURL(item.localUrl));
    if (narrationRef.current) URL.revokeObjectURL(narrationRef.current.localUrl);
  }, [cancelRequest]);

  const canGenerate = Boolean(
    videos.length > 0 && blocks.some((block) => block.text.trim()) && !audioRequired && !generating && !bgmBusy
  );

  const videoPanelStatus = useMemo(() => {
    if (["pending", "running"].includes(taskStatus) || isTerminalPosterStatus(taskStatus)) {
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
              : taskStatus === "cancelled"
                ? "已取消"
                : isImageMode
                  ? "本地图片合成"
                  : "FFmpeg 转码",
      state: ["pending", "running"].includes(taskStatus) ? "running" : taskStatus,
      icon: "wand",
    },
  ];

  const resetTask = useCallback(() => {
    cancelRequest();
    setTaskStatus("idle");
    setProgress(0);
    setStatusMsg("");
    setItems([]);
    setZipUrl("");
    setError("");
    setGenerating(false);
  }, [cancelRequest]);

  useEffect(() => {
    resetTask();
    return cancelRequest;
  }, [backendBaseUrl, currentUser?.id, cancelRequest, resetTask]);

  const addVideoFiles = useCallback(
    (files) => {
      if (generatingRef.current) return;
      const incoming = Array.from(files || []);
      if (videoInputRef.current) videoInputRef.current.value = "";
      if (!incoming.length) return;
      resetTask();
      const current = mediaItemsRef.current;
      const additions = selectSourceFiles(current.map((item) => item.file), incoming, outputMode)
        .map((file) => ({
          id: makeId(),
          file,
          sourceType: classifySource(file, outputMode),
          duration: null,
          localUrl: URL.createObjectURL(file),
        }));
      mediaItemsRef.current = [...current, ...additions];
      setVideos(mediaItemsRef.current);
      const rejected = incoming.find((file) => sourceFileError(file, outputMode));
      if (rejected) {
        const issue = sourceFileError(rejected, outputMode);
        const messages = {
          type: "格式不支持，仅支持 JPG、JPEG、PNG、WEBP、BMP、MP4、MOV、M4V、WEBM、MKV、AVI",
          mime: "文件扩展名与媒体 MIME 类型不匹配或 MIME 类型不支持",
          mode: "图片输出只能添加图片",
          size: `${classifySource(rejected, outputMode) === "image" ? "图片不能超过 20 MB" : "视频不能超过 500 MB"}`,
          empty: "文件不能为空",
        };
        setError(`已跳过“${rejected.name}”：${messages[issue]}。`);
      } else if (current.length + incoming.length > MAX_BATCH_SIZE && mediaItemsRef.current.length === MAX_BATCH_SIZE) {
        setError(`每批最多 ${MAX_BATCH_SIZE} 个素材，超出的文件未添加。`);
      }
    },
    [isImageMode, outputMode, resetTask]
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
    if (generatingRef.current) return;
    mediaItemsRef.current.forEach((item) => URL.revokeObjectURL(item.localUrl));
    mediaItemsRef.current = [];
    setVideos([]);
    if (videoInputRef.current) videoInputRef.current.value = "";
    resetTask();
  }, [resetTask]);

  const removeVideo = useCallback(
    (id) => {
      if (generatingRef.current) return;
      const target = mediaItemsRef.current.find((item) => item.id === id);
      if (target) URL.revokeObjectURL(target.localUrl);
      mediaItemsRef.current = mediaItemsRef.current.filter((item) => item.id !== id);
      setVideos(mediaItemsRef.current);
      resetTask();
    },
    [resetTask]
  );

  const updateSourceMetadata = useCallback((id, duration) => {
    const value = Number.isFinite(duration) && duration > 0 ? duration : null;
    setVideos((current) => current.map((item) => (
      item.id === id && item.duration !== value ? { ...item, duration: value } : item
    )));
  }, []);

  const handleNarrationChange = useCallback((event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || generatingRef.current) return;
    const issue = narrationFileError(file);
    if (issue) {
      setNarrationError(issue === "size"
        ? "口播文件不能超过 50 MB。"
        : issue === "empty" ? "口播文件不能为空。"
          : issue === "mime" ? "口播文件 MIME 类型不支持，须为音频文件。"
            : "口播格式须为 MP3、WAV、AAC、M4A、OGG 或 FLAC。");
      return;
    }
    const next = { id: makeId(), file, duration: null, localUrl: URL.createObjectURL(file) };
    if (narrationRef.current) URL.revokeObjectURL(narrationRef.current.localUrl);
    narrationRef.current = next;
    setNarration(next);
    setNarrationError("");
    resetTask();
  }, [resetTask]);

  const removeNarration = useCallback(() => {
    if (generatingRef.current) return;
    if (narrationRef.current) URL.revokeObjectURL(narrationRef.current.localUrl);
    narrationRef.current = null;
    setNarration(null);
    setNarrationError("");
    resetTask();
  }, [resetTask]);

  const updateNarrationMetadata = useCallback((id, duration) => {
    const value = Number.isFinite(duration) && duration > 0 ? duration : null;
    setNarration((current) => current?.id === id && current.duration !== value
      ? { ...current, duration: value } : current);
  }, []);

  const handleBgmSelectionChange = useCallback((id) => {
    if (generatingRef.current) return;
    setSelectedBgmId(id);
    setSelectedBgmTrack(null);
    resetTask();
  }, [resetTask]);

  const handleBgmBusyChange = useCallback((busy) => {
    bgmBusyRef.current = busy;
    setBgmBusy(busy);
  }, []);

  const updateBlock = useCallback((id, patch) => {
    if (generatingRef.current) return;
    setBlocks((current) => current.map((block) => (block.id === id ? { ...block, ...patch } : block)));
    resetTask();
  }, [resetTask]);

  const centerBlockX = useCallback(
    (block) => {
      const centeredX = Math.max(0, Math.min(90, Math.round((100 - Number(block.width || 0)) / 2)));
      updateBlock(block.id, { x: centeredX });
    },
    [updateBlock]
  );

  const addBlock = useCallback(() => {
    if (generatingRef.current) return;
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
    resetTask();
  }, [fonts, resetTask]);

  const removeBlock = useCallback((id) => {
    if (generatingRef.current) return;
    setBlocks((current) => current.filter((block) => block.id !== id));
    resetTask();
  }, [resetTask]);

  const handleOutputModeChange = useCallback(
    (nextMode) => {
      if (generatingRef.current || bgmBusyRef.current || nextMode === outputMode) return;
      setOutputMode(nextMode);
      clearVideos();
    },
    [clearVideos, outputMode]
  );

  const handleGenerate = useCallback(async () => {
    if (!canGenerate || generatingRef.current || bgmBusyRef.current) return;

    cancelRequest();
    const controller = new AbortController();
    const token = requestRef.current.token;
    requestRef.current.controller = controller;
    const isCurrentRequest = () => token === requestRef.current.token && !controller.signal.aborted;
    generatingRef.current = true;
    setGenerating(true);
    setError("");
    setZipUrl("");
    setItems([]);
    setProgress(0);
    setTaskStatus("pending");
    setStatusMsg("正在上传素材并创建批量任务...");

    try {
      const formData = new FormData();
      videos.forEach((item) => formData.append("assets", item.file));
      formData.append("media_type", outputMode);
      formData.append("template", JSON.stringify({ blocks }));
      if (!isImageMode) {
        if (narration) formData.append("narration_audio", narration.file);
        if (selectedBgmId) formData.append("bgm_id", selectedBgmId);
        formData.append("mute_original_audio", String(muteOriginalAudio));
      }

      const data = await apiJson(
        "/api/poster-videos/generate",
        {
          method: "POST",
          body: formData,
          signal: controller.signal,
          silentError: true,
        },
        backendBaseUrl
      );

      if (!isCurrentRequest()) return;
      const { task_id: taskId } = data;
      if (!taskId) throw new Error("服务端未返回任务编号。");
      setTaskStatus("running");
      setStatusMsg(`${mediaLabel}已上传，正在本地处理...`);

      const poll = async () => {
        if (!isCurrentRequest()) return;
        try {
          const data = await pollTask(taskId, controller.signal, backendBaseUrl);
          if (!isCurrentRequest()) return;
          setTaskStatus(data.status || "running");
          setProgress(data.progress ?? 0);
          setStatusMsg(data.message || data.error || (data.status === "cancelled" ? "任务已取消。" : ""));
          setItems(Array.isArray(data.items) ? data.items : []);
          setZipUrl(data.zip_url || "");

          if (isTerminalPosterStatus(data.status)) {
            cancelRequest();
            setGenerating(false);
            if (data.status === "failed") setError(data.error || data.message || "批量处理失败");
            if (data.status === "cancelled") setError(data.error || data.message || "任务已取消，可重新生成。");
            return;
          }

          pollRef.current = setTimeout(poll, 1800);
        } catch (err) {
          if (!isCurrentRequest() || err.name === "AbortError") return;
          setTaskStatus("failed");
          setError(err.message);
          setGenerating(false);
          generatingRef.current = false;
        }
      };

      pollRef.current = setTimeout(poll, 900);
    } catch (err) {
      if (!isCurrentRequest() || err.name === "AbortError") return;
      setTaskStatus("failed");
      setError(err.message);
      setGenerating(false);
      generatingRef.current = false;
    }
  }, [backendBaseUrl, blocks, canGenerate, cancelRequest, isImageMode, mediaLabel, muteOriginalAudio, narration, outputMode, selectedBgmId, videos]);

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
            <div className="workflow-card poster-output-type-card">
              <div className="control-section-heading">
                <span>00</span>
                <strong>输出类型</strong>
              </div>
              <ToggleButtonGroup
                className="segmented-control poster-output-type-control"
                exclusive
                fullWidth
                disabled={generating || bgmBusy}
                value={outputMode}
                onChange={(_, nextMode) => nextMode && handleOutputModeChange(nextMode)}
              >
                {OUTPUT_MODES.map((mode) => (
                  <ToggleButton key={mode.value} value={mode.value}>
                    {mode.label}
                  </ToggleButton>
                ))}
              </ToggleButtonGroup>
            </div>

            <div className="workflow-card">
              <div className="control-section-heading">
                <span>01</span>
                <strong>批量{mediaLabel}素材</strong>
              </div>

              <label
                className={`upload-dropzone compact poster-upload ${videos.length ? "is-filled" : ""}`}
                aria-disabled={generating}
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleVideoDrop}
              >
                <span className="upload-placeholder">
                  <Icon name={videos.length ? "check" : "upload"} size={24} />
                  <strong>{videos.length ? `已加入 ${videos.length} 个${mediaLabel}` : `选择或拖入多个${mediaLabel}`}</strong>
                  <small>可一次多选，也可重复添加；最多 {MAX_BATCH_SIZE} 个</small>
                </span>
                <Box
                  component="input"
                  ref={videoInputRef}
                  name="assets"
                  type="file"
                  accept={acceptTypes}
                  multiple
                  disabled={generating}
                  aria-label={`批量${mediaLabel}素材`}
                  onChange={handleVideoChange}
                />
              </label>

              {videos.length > 0 && (
                <div className="poster-file-list">
                  {videos.map((item, index) => (
                    <div className="poster-file-row" key={item.id}>
                      <IconButton
                        size="small"
                        title={`预览${item.sourceType === "image" ? "图片" : "视频"}：${item.file.name}`}
                        aria-label={`预览 ${item.file.name}`}
                        aria-pressed={previewSource?.id === item.id}
                        onClick={() => {
                          if (!generatingRef.current) setPreviewId(item.id);
                        }}
                        disabled={generating}
                      >
                        {item.sourceType === "image" ? <ImageOutlined fontSize="inherit" /> : <VideoFileOutlined fontSize="inherit" />}
                      </IconButton>
                      <Box className="poster-file-copy">
                        <span title={item.file.name}>{item.file.name}</span>
                        {!isImageMode && (
                          <Typography component="small" className="poster-estimate">
                            预计时长 {formatDuration(estimates[index].targetDuration)}
                            {item.sourceType === "video" && ` · 视频 ${formatSpeed(estimates[index].videoSpeed)}`}
                            {narration && ` · 口播 ${formatSpeed(estimates[index].narrationSpeed)}`}
                          </Typography>
                        )}
                        {item.sourceType === "video" && (
                          <Box
                            component="video"
                            hidden
                            src={item.localUrl}
                            preload="metadata"
                            muted
                            onLoadedMetadata={(event) => updateSourceMetadata(item.id, event.currentTarget.duration)}
                            onDurationChange={(event) => updateSourceMetadata(item.id, event.currentTarget.duration)}
                            onError={() => updateSourceMetadata(item.id, null)}
                          />
                        )}
                      </Box>
                      <small>{formatFileSize(item.file.size)}</small>
                      <IconButton
                        size="small"
                        title={`移除 ${item.file.name}`}
                        aria-label={`移除 ${item.file.name}`}
                        disabled={generating}
                        onClick={() => removeVideo(item.id)}
                      >
                        <DeleteOutlined fontSize="small" />
                      </IconButton>
                    </div>
                  ))}
                  <Button variant="text" size="small" type="button" disabled={generating} onClick={clearVideos}>
                    清空素材
                  </Button>
                </div>
              )}
            </div>

            {!isImageMode && (
              <Box className="workflow-card poster-audio-settings">
                <Box className="control-section-heading">
                  <AudioFileOutlined fontSize="small" />
                  <strong>音频</strong>
                </Box>
                <Box component="section" className="poster-narration" aria-labelledby="poster-narration-title">
                  <Box className="poster-block-heading">
                    <Typography id="poster-narration-title" component="strong">口播音频</Typography>
                    <Button
                      variant="outlined"
                      size="small"
                      disabled={generating}
                      startIcon={<UploadFileOutlined fontSize="small" />}
                      onClick={() => narrationInputRef.current?.click()}
                    >
                      {narration ? "替换口播" : "上传口播"}
                    </Button>
                    <Box
                      component="input"
                      ref={narrationInputRef}
                      type="file"
                      hidden
                      accept={NARRATION_EXTENSIONS.join(",")}
                      disabled={generating}
                      aria-label="上传单个口播文件"
                      onChange={handleNarrationChange}
                    />
                  </Box>
                  {narration && (
                    <Box className="poster-narration-file">
                      <Box className="poster-narration-meta">
                        <AudioFileOutlined fontSize="small" />
                        <Box className="poster-file-copy">
                          <Typography component="strong" title={narration.file.name}>{narration.file.name}</Typography>
                          <Typography component="small">
                            {formatFileSize(narration.file.size)} · {formatDuration(narration.duration)}
                          </Typography>
                        </Box>
                        <IconButton
                          size="small"
                          title="移除口播"
                          aria-label="移除口播"
                          disabled={generating}
                          onClick={removeNarration}
                        >
                          <DeleteOutlined fontSize="small" />
                        </IconButton>
                      </Box>
                      <Box
                        component="audio"
                        key={narration.id}
                        src={narration.localUrl}
                        controls
                        preload="metadata"
                        aria-label={`口播试听：${narration.file.name}`}
                        onLoadedMetadata={(event) => updateNarrationMetadata(narration.id, event.currentTarget.duration)}
                        onDurationChange={(event) => updateNarrationMetadata(narration.id, event.currentTarget.duration)}
                        onError={() => updateNarrationMetadata(narration.id, null)}
                      />
                    </Box>
                  )}
                  {narrationError && <Box className="form-alert failed" role="alert">{narrationError}</Box>}
                </Box>
                <BgmManager
                  currentUserId={currentUser?.id}
                  selectedBgmId={selectedBgmId}
                  onSelectionChange={handleBgmSelectionChange}
                  onSelectedTrackChange={setSelectedBgmTrack}
                  onBusyChange={handleBgmBusyChange}
                  disabled={generating}
                  idPrefix="poster"
                />
                <FormControlLabel
                  label="关闭视频原声"
                  control={(
                    <Switch
                      checked={muteOriginalAudio}
                      disabled={generating || !hasVideoSources}
                      onChange={(_, checked) => {
                        if (generatingRef.current) return;
                        setMuteOriginalAudio(checked);
                        resetTask();
                      }}
                    />
                  )}
                />
              </Box>
            )}

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
                      <Button variant="text" size="small" type="button" disabled={generating} onClick={() => removeBlock(block.id)}>
                        删除
                      </Button>
                    </div>

                    <TextField
                      className="poster-block-text"
                      placeholder="输入大字报文字内容"
                      fullWidth
                      multiline
                      rows={3}
                      size="small"
                      disabled={generating}
                      value={block.text}
                      onChange={(event) => updateBlock(block.id, { text: event.target.value })}
                    />

                    <div className="poster-control-grid">
                      <TextField
                        className="field"
                        label="字体"
                        fullWidth
                        size="small"
                        select
                        disabled={generating}
                        value={block.fontPath}
                        onChange={(event) => updateBlock(block.id, { fontPath: event.target.value })}
                      >
                        {fonts.length === 0 && <MenuItem value="">系统默认字体</MenuItem>}
                        {fonts.map((font) => (
                          <MenuItem key={font.path} value={font.path}>
                            {font.label}
                          </MenuItem>
                        ))}
                      </TextField>

                      <TextField
                        className="field"
                        label="对齐"
                        fullWidth
                        size="small"
                        select
                        disabled={generating}
                        value={block.align}
                        onChange={(event) => updateBlock(block.id, { align: event.target.value })}
                      >
                        <MenuItem value="left">左对齐</MenuItem>
                        <MenuItem value="center">居中</MenuItem>
                        <MenuItem value="right">右对齐</MenuItem>
                      </TextField>
                    </div>

                    <div className="poster-control-grid three">
                      <div className="field">
                        <span className="field-label with-inline-action">
                          <span>X {block.x}%</span>
                          <Button variant="text" size="small" disabled={generating} onClick={() => centerBlockX(block)}>
                            一键居中
                          </Button>
                        </span>
                        <Slider disabled={generating} size="small" min={0} max={90} value={block.x} onChange={(_, value) => updateBlock(block.id, { x: value })} />
                      </div>
                      <div className="field">
                        <span className="field-label">Y {block.y}%</span>
                        <Slider disabled={generating} size="small" min={0} max={92} value={block.y} onChange={(_, value) => updateBlock(block.id, { y: value })} />
                      </div>
                      <div className="field">
                        <span className="field-label">宽度 {block.width}%</span>
                        <Slider disabled={generating} size="small" min={20} max={100} value={block.width} onChange={(_, value) => updateBlock(block.id, { width: value })} />
                      </div>
                    </div>

                    <div className="poster-control-grid three">
                      <div className="field">
                        <span className="field-label">字号 {block.fontSize}</span>
                        <Slider disabled={generating} size="small" min={24} max={120} value={block.fontSize} onChange={(_, value) => updateBlock(block.id, { fontSize: value })} />
                      </div>
                      <div className="field">
                        <span className="field-label">描边 {block.strokeWidth}</span>
                        <Slider disabled={generating} size="small" min={0} max={12} value={block.strokeWidth} onChange={(_, value) => updateBlock(block.id, { strokeWidth: value })} />
                      </div>
                      <div className="field">
                        <span className="field-label">背景 {Math.round(block.backgroundOpacity * 100)}%</span>
                        <Slider disabled={generating} size="small" min={0} max={1} step={0.05} value={block.backgroundOpacity} onChange={(_, value) => updateBlock(block.id, { backgroundOpacity: value })} />
                      </div>
                    </div>

                    <div className="poster-swatch-grid">
                      <label>
                        <span>文字</span>
                        <Box component="input" type="color" aria-label="文字颜色" disabled={generating} value={block.color} onChange={(event) => updateBlock(block.id, { color: event.target.value })} />
                      </label>
                      <label>
                        <span>描边</span>
                        <Box component="input" type="color" aria-label="描边颜色" disabled={generating} value={block.strokeColor} onChange={(event) => updateBlock(block.id, { strokeColor: event.target.value })} />
                      </label>
                      <label>
                        <span>背景</span>
                        <Box component="input" type="color" aria-label="背景颜色" disabled={generating} value={block.backgroundColor} onChange={(event) => updateBlock(block.id, { backgroundColor: event.target.value })} />
                      </label>
                    </div>
                  </div>
                ))}
              </div>

              <Button type="button" variant="outlined" disabled={generating} onClick={addBlock} startIcon={<Icon name="sparkles" size={16} />}>
                新增文字块
              </Button>
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
                    {previewSource?.localUrl ? (
                      previewSource.sourceType === "image" ? (
                        <img src={previewSource.localUrl} alt={previewSource.file.name} />
                      ) : (
                        <video src={previewSource.localUrl} muted playsInline />
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
            </div>

            <div className="poster-preview-actions">
              <Button type="button" variant="contained" disabled={!canGenerate} onClick={handleGenerate}
                startIcon={<Icon name={generating ? "loading" : "wand"} size={16} />}>
                {generating ? "正在批量生成" : `生成${outputLabel}`}
              </Button>

              {audioRequired && (
                <Box className="form-alert failed" role="alert">
                  本批包含图片，须选择口播或背景音乐后才能生成视频。
                </Box>
              )}

              {(taskStatus === "running" || taskStatus === "pending") && (
                <div className="progress-area" aria-label="批量处理进度">
                  <div className="progress-meta">
                    <span>{statusMsg}</span>
                    <strong>{progress}%</strong>
                  </div>
                  <LinearProgress variant="determinate" value={progress} sx={{ mt: 0.5 }} />
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
            <h2 id="poster-output-title">批量生成结果</h2>
          </div>
          <Chip
            size="small"
            icon={
              <Icon
                name={
                  ["failed", "partial_failed", "cancelled"].includes(videoPanelStatus)
                    ? "alert"
                    : videoPanelStatus === "completed"
                      ? "check"
                      : ["running", "pending"].includes(videoPanelStatus)
                        ? "loading"
                        : "gauge"
                }
                size={14}
              />
            }
            label={STATUS_LABELS[videoPanelStatus]}
            sx={{
              backgroundColor: statusChipColors[videoPanelStatus]?.bg || "#f3f1e9",
              color: statusChipColors[videoPanelStatus]?.fg || "#68645b",
              fontWeight: 600,
              "& .vf-icon": { color: statusChipColors[videoPanelStatus]?.fg || "#68645b" },
            }}
          />
        </div>

        <div className="poster-result-shell">
          <div className="video-status-card poster-result-summary">
            <Typography variant="kicker" component="span" className="section-kicker with-icon">
              <Icon name="video" size={13} />
              Batch
            </Typography>
            <h3>{STATUS_LABELS[videoPanelStatus]}</h3>
            <p>{statusMsg || `上传${mediaLabel}并确认模板后，可以开始本地批量生成。`}</p>
            {zipUrl && (
              <ProtectedDownloadButton
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
                      {item.source_type && (
                        <Typography component="small" className="poster-result-metadata">
                          {item.source_type === "image" ? <ImageOutlined fontSize="inherit" /> : <VideoFileOutlined fontSize="inherit" />}
                          {item.source_type === "image" ? "图片素材" : "视频素材"}
                        </Typography>
                      )}
                      {!isImageMode && (item.target_duration != null || item.video_speed != null || item.narration_speed != null) && (
                        <Typography component="small" className="poster-result-metadata">
                          时长 {formatDuration(item.target_duration)}
                          {item.source_type !== "image" && item.video_speed != null && ` · 视频 ${formatSpeed(item.video_speed)}`}
                          {narration && item.narration_speed != null && ` · 口播 ${formatSpeed(item.narration_speed)}`}
                        </Typography>
                      )}
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
                        path={item.asset_url || item.video_url || item.image_url}
                        filename={posterDownloadFilename(item.filename, outputMode)}
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
