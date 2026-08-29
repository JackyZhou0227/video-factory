import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Chip from "@mui/material/Chip";
import Slider from "@mui/material/Slider";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import ToggleButton from "@mui/material/ToggleButton";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import { statusChipColors } from "../theme";
import Icon from "./Icon";
import { ProtectedDownloadButton, ProtectedMedia } from "./ProtectedAsset";
import { apiJson, resolveBackendAssetUrl, useBackendBaseUrl } from "../lib/backend";
import { PAGE_NAMES } from "../lib/pageNames";

const TTS_MODE_OPTIONS = [
  {
    value: "base",
    providerId: "qwen3_tts_base",
    label: "音色克隆",
    detail: "Qwen3-TTS Base · 本地",
    description: "本地运行，支持参考音频克隆音色；效果更自然，但依赖模型、PyTorch 和机器性能。",
  },
  {
    value: "edge-tts",
    providerId: "edge_tts",
    label: "预设音色",
    detail: "Edge-TTS · 云端",
    description: "轻量、快速、免费，使用在线预设音色；无需本地算力，但声音质感偏电子音。",
  },
];

const DEFAULT_LANGUAGES = [
  { id: "Chinese", label: "中文" },
  { id: "English", label: "英语" },
  { id: "Japanese", label: "日语" },
  { id: "Korean", label: "韩语" },
  { id: "German", label: "德语" },
  { id: "French", label: "法语" },
  { id: "Russian", label: "俄语" },
  { id: "Portuguese", label: "葡萄牙语" },
  { id: "Spanish", label: "西班牙语" },
  { id: "Italian", label: "意大利语" },
];

const DEFAULT_EDGE_LANGUAGE = "zh-CN";

const EDGE_TTS_STATIC_STATUS = {
  id: "edge_tts",
  model_name: "Edge-TTS",
  display_name: "预设音色",
  runtime: "cloud",
  enabled: true,
  available: true,
  status: "available",
  reason: null,
  validation: "static",
  checks: { configuration: "passed", network: "skipped" },
};

function formatFileSize(size) {
  if (!size) return "";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function edgeVoiceLocale(voice) {
  if (voice?.language || voice?.locale) return voice.language || voice.locale;
  const match = String(voice?.id || "").match(/^([a-z]{2,3}(?:-[A-Za-z]{4})?-[A-Z]{2})-/);
  return match?.[1] || "";
}

export default function TTSStudio({ active = false }) {
  const backendBaseUrl = useBackendBaseUrl();
  const refAudioInputRef = useRef(null);
  const [text, setText] = useState("");
  const [ttsMode, setTtsMode] = useState("edge-tts");
  const [providerStatuses, setProviderStatuses] = useState([EDGE_TTS_STATIC_STATUS]);
  const [providerStatusesLoading, setProviderStatusesLoading] = useState(true);
  const [providerStatusError, setProviderStatusError] = useState("");
  const [edgeVoices, setEdgeVoices] = useState([]);
  const [edgeVoicesLoading, setEdgeVoicesLoading] = useState(true);
  const [edgeVoice, setEdgeVoice] = useState("zh-CN-XiaoxiaoNeural");
  const [edgeLanguage, setEdgeLanguage] = useState(DEFAULT_EDGE_LANGUAGE);
  const [languages, setLanguages] = useState(DEFAULT_LANGUAGES);
  const [language, setLanguage] = useState("Chinese");
  const [speechRate, setSpeechRate] = useState(1);
  const [voiceProfiles, setVoiceProfiles] = useState([]);
  const [voiceProfilesLoading, setVoiceProfilesLoading] = useState(true);
  const [voiceProfileId, setVoiceProfileId] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewStale, setPreviewStale] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [applyingSpeechRate, setApplyingSpeechRate] = useState(false);
  const [profileDialog, setProfileDialog] = useState(null);
  const [profileName, setProfileName] = useState("");
  const [refAudioFile, setRefAudioFile] = useState(null);
  const [refAudioUrl, setRefAudioUrl] = useState("");
  const [refText, setRefText] = useState("");
  const [profileError, setProfileError] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [deletingProfile, setDeletingProfile] = useState(false);
  const [deleteConfirmation, setDeleteConfirmation] = useState(false);

  const selectedEdgeVoice = useMemo(
    () => edgeVoices.find((item) => item.id === edgeVoice) ?? edgeVoices.find((item) => edgeVoiceLocale(item) === edgeLanguage) ?? edgeVoices[0] ?? null,
    [edgeLanguage, edgeVoice, edgeVoices]
  );
  const edgeLanguages = useMemo(() => {
    return edgeVoices.length ? [{ id: DEFAULT_EDGE_LANGUAGE, label: "中文" }] : [];
  }, [edgeVoices]);
  const filteredEdgeVoices = useMemo(
    () => edgeVoices,
    [edgeVoices]
  );
  const providerStatusById = useMemo(
    () => new Map(providerStatuses.map((provider) => [provider.id, provider])),
    [providerStatuses]
  );
  const qwenProviderStatus = providerStatusById.get("qwen3_tts_base") ?? null;
  const qwenProviderAvailable = qwenProviderStatus?.available === true;
  const qwenProviderReason =
    providerStatusError ||
    qwenProviderStatus?.reason ||
    (!providerStatusesLoading && !qwenProviderStatus ? "无法确认本地 Qwen3-TTS Base 状态" : "");

  useEffect(() => {
    if (!filteredEdgeVoices.length) {
      setEdgeVoice("");
      return;
    }
    if (!filteredEdgeVoices.some((voice) => voice.id === edgeVoice)) {
      setEdgeVoice(filteredEdgeVoices[0].id);
    }
  }, [edgeVoice, filteredEdgeVoices]);
  const selectedVoiceProfile = useMemo(
    () => voiceProfiles.find((item) => item.id === voiceProfileId) ?? null,
    [voiceProfileId, voiceProfiles]
  );
  const editingVoiceProfile = useMemo(
    () => voiceProfiles.find((item) => item.id === profileDialog?.voiceId) ?? null,
    [profileDialog?.voiceId, voiceProfiles]
  );
  const isEditingVoiceProfile = profileDialog?.mode === "edit";

  const markPreviewStale = useCallback(() => {
    setPreviewStale((wasStale) => (preview ? true : wasStale));
  }, [preview]);

  const refreshVoiceProfiles = useCallback(async () => {
    setVoiceProfilesLoading(true);
    try {
      const list = await apiJson("/api/tts-studio/voice-profiles", undefined, backendBaseUrl);
      const nextProfiles = Array.isArray(list) ? list : [];
      setVoiceProfiles(nextProfiles);
      setVoiceProfileId((current) => {
        if (current && nextProfiles.some((item) => item.id === current)) return current;
        return nextProfiles[0]?.id || "";
      });
    } catch {
      setVoiceProfiles([]);
      setVoiceProfileId("");
    } finally {
      setVoiceProfilesLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    if (!active) return undefined;
    let cancelled = false;
    setProviderStatusesLoading(true);
    setProviderStatusError("");
    apiJson("/api/tts-studio/providers", { silentError: true }, backendBaseUrl)
      .then((list) => {
        if (cancelled) return;
        const remoteStatuses = Array.isArray(list) ? list : [];
        const hasEdgeStatus = remoteStatuses.some((provider) => provider.id === EDGE_TTS_STATIC_STATUS.id);
        setProviderStatuses(hasEdgeStatus ? remoteStatuses : [EDGE_TTS_STATIC_STATUS, ...remoteStatuses]);
      })
      .catch((err) => {
        if (cancelled) return;
        setProviderStatuses([EDGE_TTS_STATIC_STATUS]);
        setProviderStatusError(err.message || "无法加载 TTS 服务状态");
      })
      .finally(() => {
        if (!cancelled) setProviderStatusesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [active, backendBaseUrl]);

  useEffect(() => {
    if (!active) return undefined;
    let cancelled = false;
    setEdgeVoicesLoading(true);
    apiJson("/api/tts-studio/edge-tts/voices", { silentError: true }, backendBaseUrl)
      .then((list) => {
        if (cancelled) return;
        const nextVoices = Array.isArray(list) ? list : [];
        setEdgeVoices(nextVoices);
        const preferredLanguage = DEFAULT_EDGE_LANGUAGE;
        setEdgeLanguage(preferredLanguage);
        setEdgeVoice((current) => {
          if (nextVoices.some((item) => item.id === current && edgeVoiceLocale(item) === preferredLanguage)) return current;
          return nextVoices.find((item) => edgeVoiceLocale(item) === preferredLanguage)?.id || nextVoices[0]?.id || "";
        });
      })
      .catch(() => {
        if (cancelled) return;
        setEdgeVoices([]);
        setEdgeVoice("");
      })
      .finally(() => {
        if (!cancelled) setEdgeVoicesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [active, backendBaseUrl]);

  useEffect(() => {
    if (!active) return undefined;
    let cancelled = false;
    apiJson("/api/tts-studio/languages", { silentError: true }, backendBaseUrl)
      .then((list) => {
        if (cancelled) return;
        const nextLanguages = Array.isArray(list) && list.length ? list : DEFAULT_LANGUAGES;
        setLanguages(nextLanguages);
        setLanguage((current) =>
          nextLanguages.some((item) => item.id === current) ? current : nextLanguages[0]?.id || "Chinese"
        );
      })
      .catch(() => {
        if (!cancelled) setLanguages(DEFAULT_LANGUAGES);
      });
    return () => {
      cancelled = true;
    };
  }, [active, backendBaseUrl]);

  useEffect(() => {
    if (!active) return undefined;
    refreshVoiceProfiles();
  }, [active, refreshVoiceProfiles]);

  useEffect(() => {
    if (ttsMode === "base" && selectedVoiceProfile?.language) {
      setLanguage(selectedVoiceProfile.language);
    }
  }, [selectedVoiceProfile, ttsMode]);

  useEffect(() => {
    if (!providerStatusesLoading && ttsMode === "base" && !qwenProviderAvailable) {
      setTtsMode("edge-tts");
    }
  }, [providerStatusesLoading, qwenProviderAvailable, ttsMode]);

  useEffect(() => {
    return () => {
      if (refAudioUrl) URL.revokeObjectURL(refAudioUrl);
    };
  }, [refAudioUrl]);

  const clearReferenceAudio = useCallback(() => {
    setRefAudioFile(null);
    setRefAudioUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
    if (refAudioInputRef.current) refAudioInputRef.current.value = "";
  }, []);

  const openCreateVoiceProfile = useCallback(() => {
    clearReferenceAudio();
    setProfileDialog({ mode: "create" });
    setProfileName("");
    setRefText("");
    setProfileError("");
    setDeleteConfirmation(false);
  }, [clearReferenceAudio]);

  const openEditVoiceProfile = useCallback(
    (profile) => {
      clearReferenceAudio();
      setProfileDialog({ mode: "edit", voiceId: profile.id });
      setProfileName(profile.name || "");
      setRefText(profile.ref_text || "");
      setLanguage(profile.language || "Chinese");
      setProfileError("");
      setDeleteConfirmation(false);
    },
    [clearReferenceAudio]
  );

  const closeVoiceProfileDialog = useCallback(() => {
    clearReferenceAudio();
    setProfileDialog(null);
    setProfileError("");
    setDeleteConfirmation(false);
  }, [clearReferenceAudio]);

  const handleReferenceAudioChange = useCallback((event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setRefAudioFile(file);
    setRefAudioUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return URL.createObjectURL(file);
    });
  }, []);

  const handleSaveVoiceProfile = useCallback(async () => {
    const needsAudio = !isEditingVoiceProfile;
    if (!profileName.trim() || !refText.trim() || (needsAudio && !refAudioFile)) return;

    setSavingProfile(true);
    setProfileError("");
    try {
      const formData = new FormData();
      formData.append("name", profileName.trim());
      formData.append("language", language);
      formData.append("ref_text", refText.trim());
      if (refAudioFile) formData.append("ref_audio", refAudioFile);

      const endpoint = isEditingVoiceProfile
        ? `/api/tts-studio/voice-profiles/${editingVoiceProfile.id}`
        : "/api/tts-studio/voice-profiles";
      const saved = await apiJson(
        endpoint,
        { method: isEditingVoiceProfile ? "PUT" : "POST", body: formData, silentError: true },
        backendBaseUrl
      );
      await refreshVoiceProfiles();
      setVoiceProfileId(saved.id || "");
      markPreviewStale();
      closeVoiceProfileDialog();
    } catch (err) {
      setProfileError(err.message || "保存音色档案失败");
    } finally {
      setSavingProfile(false);
    }
  }, [
    backendBaseUrl,
    closeVoiceProfileDialog,
    editingVoiceProfile?.id,
    isEditingVoiceProfile,
    language,
    markPreviewStale,
    profileName,
    refAudioFile,
    refText,
    refreshVoiceProfiles,
  ]);

  const handleDeleteVoiceProfile = useCallback(async () => {
    if (!editingVoiceProfile) return;
    setDeletingProfile(true);
    setProfileError("");
    try {
      await apiJson(
        `/api/tts-studio/voice-profiles/${editingVoiceProfile.id}`,
        { method: "DELETE", silentError: true },
        backendBaseUrl
      );
      await refreshVoiceProfiles();
      markPreviewStale();
      closeVoiceProfileDialog();
    } catch (err) {
      setProfileError(err.message || "删除音色档案失败");
    } finally {
      setDeletingProfile(false);
    }
  }, [backendBaseUrl, closeVoiceProfileDialog, editingVoiceProfile, markPreviewStale, refreshVoiceProfiles]);

  const handleGeneratePreview = useCallback(async () => {
    if (!text.trim()) return;
    if (ttsMode === "base" && !voiceProfileId) return;
    if (ttsMode === "edge-tts" && !edgeVoice) return;

    setGenerating(true);
    try {
      const formData = new FormData();
      formData.append("text", text.trim());
      // TTS generation always produces the canonical 1.0x source audio.
      formData.append("speech_rate", "1.0");

      const endpoint = ttsMode === "edge-tts" ? "/api/tts-studio/edge-tts/preview" : "/api/tts-studio/voice-clone/preview";
      if (ttsMode === "edge-tts") {
        formData.append("voice_id", edgeVoice);
        formData.append("language", edgeLanguage);
      } else {
        formData.append("language", language);
        formData.append("voice_profile_id", voiceProfileId);
      }

      const generated = await apiJson(endpoint, { method: "POST", body: formData }, backendBaseUrl);
      const originalAudioUrl = generated.original_audio_url || generated.audio_url;
      setSpeechRate(1);
      setPreview({
        ...generated,
        audio_url: originalAudioUrl,
        original_audio_url: originalAudioUrl,
        adjusted_audio_url: null,
        processed_audio_url: null,
        adjusted_speech_rate: null,
        speech_rate: 1,
      });
      setPreviewStale(false);
    } catch {
      // apiJson 已弹全局错误提示
    } finally {
      setGenerating(false);
    }
  }, [backendBaseUrl, edgeLanguage, edgeVoice, language, text, ttsMode, voiceProfileId]);

  const handleApplySpeechRate = useCallback(async () => {
    if (!preview?.original_audio_url) return;
    setApplyingSpeechRate(true);
    try {
      const formData = new FormData();
      if (preview.task_id && preview.artifact_id) {
        formData.append("task_id", preview.task_id);
        formData.append("artifact_id", preview.artifact_id);
      } else {
        formData.append("audio_url", preview.original_audio_url);
      }
      formData.append("speech_rate", String(speechRate));
      const updated = await apiJson(
        "/api/tts-studio/preview/speech-rate",
        { method: "POST", body: formData },
        backendBaseUrl
      );
      setPreview((current) => {
        if (!current) return current;
        const originalAudioUrl = current.original_audio_url || updated.original_audio_url || current.audio_url;
        return {
          ...current,
          ...updated,
          audio_url: originalAudioUrl,
          original_audio_url: originalAudioUrl,
          adjusted_audio_url: updated.adjusted_audio_url || updated.processed_audio_url || null,
          processed_audio_url: updated.processed_audio_url || updated.adjusted_audio_url || null,
          adjusted_speech_rate: updated.adjusted_audio_url ? Number(updated.speech_rate) : null,
          speech_rate: 1,
        };
      });
      setPreviewStale(false);
    } catch {
      // apiJson 已弹全局错误提示
    } finally {
      setApplyingSpeechRate(false);
    }
  }, [backendBaseUrl, preview?.artifact_id, preview?.original_audio_url, preview?.task_id, speechRate]);

  const originalAudioUrl = preview?.original_audio_url || preview?.audio_url || "";
  const adjustedAudioUrl = preview?.adjusted_audio_url || preview?.processed_audio_url || "";
  const adjustedSpeechRate = adjustedAudioUrl ? Number(preview?.adjusted_speech_rate ?? preview?.speech_rate ?? 1) : null;
  const audioExtension = preview?.tts_mode === "edge-tts" ? "mp3" : "wav";
  const originalAudioFilename = `preview_original.${audioExtension}`;
  const adjustedAudioFilename = `preview_${adjustedSpeechRate?.toFixed(1) || speechRate.toFixed(1)}x.${audioExtension}`;
  const hasPendingRate = Boolean(
    originalAudioUrl &&
      Math.abs(speechRate - 1) > 0.001 &&
      (!adjustedAudioUrl || adjustedSpeechRate === null || Math.abs(speechRate - adjustedSpeechRate) > 0.001)
  );
  const canGenerate = Boolean(
    text.trim() &&
      !generating &&
      (ttsMode === "edge-tts"
        ? edgeVoice && selectedEdgeVoice
        : qwenProviderAvailable && voiceProfileId && selectedVoiceProfile)
  );
  const status = generating ? "previewing" : preview && !previewStale ? "completed" : previewStale ? "ready" : "idle";
  const statusLabel =
    status === "previewing"
      ? "正在生成"
      : status === "completed"
        ? adjustedAudioUrl
          ? "双版本已就绪"
          : "原速已生成"
        : status === "ready"
          ? "参数已变更"
          : "等待生成";
  const previewTitle = generating
    ? "正在生成原速语音"
    : previewStale
      ? "参数已更新"
      : adjustedAudioUrl
        ? "原速与调速版"
        : preview
          ? "原速语音"
          : "等待生成";
  const previewDescription = generating
    ? "正在生成 1.0x 原速音频，完成后会自动显示在下方。"
    : preview
      ? previewStale
        ? "当前结果保留用于对比；文案或音色变化后，重新生成会刷新原速音频。"
        : adjustedAudioUrl
          ? `原速和 ${adjustedSpeechRate?.toFixed(1) || speechRate.toFixed(1)}x 调速版都已保留。`
          : "原速语音已生成，可以试听、下载，或继续生成调速版。"
      : "先生成原速语音，再按需要生成调速版本。";

  const pipelineItems = useMemo(
    () => [
      {
        label: "输入文案",
        detail: text.trim() ? `${text.trim().length} 字内容已准备` : "填写待合成文本",
        state: text.trim() ? "completed" : "idle",
        icon: "edit",
      },
      {
        label: "选择音色",
        detail:
          ttsMode === "edge-tts"
            ? selectedEdgeVoice?.name || (edgeVoicesLoading ? "加载 Edge 音色中" : "选择 Edge 音色")
            : selectedVoiceProfile?.name || (voiceProfilesLoading ? "加载音色中" : "选择克隆音色"),
        state:
          ttsMode === "edge-tts"
            ? selectedEdgeVoice
              ? "completed"
              : "idle"
            : selectedVoiceProfile
              ? "completed"
              : "idle",
        icon: "mic",
      },
      {
        label: "生成语音",
        detail: generating ? "正在生成 1.0x 原速音频" : preview ? "原速已生成，可继续调速" : "确认参数后生成 1.0x 原速",
        state: generating ? "previewing" : preview ? "completed" : canGenerate ? "ready" : "idle",
        icon: "wand",
      },
      {
        label: "试听下载",
         detail: preview
           ? previewStale
             ? "结果保留，需重新生成"
             : adjustedAudioUrl
               ? "原速与调速版可交付"
               : "原速可下载，可继续调速"
           : "等待原速音频",
         state: preview ? (previewStale ? "ready" : "completed") : "idle",
        icon: "download",
      },
    ],
    [
      canGenerate,
      generating,
      preview,
      previewStale,
      edgeVoicesLoading,
      selectedEdgeVoice,
      selectedVoiceProfile,
      text,
      ttsMode,
      voiceProfilesLoading,
    ]
  );

  return (
    <>
      <section className="workspace-panel tts-studio-panel" aria-label="独立语音合成工作区">
        <div className="pipeline-strip tts-studio-pipeline" aria-label="语音合成流程">
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

        <div className="tts-studio-layout">
          <div className="tts-studio-flow">
            <section className="tts-studio-step tts-studio-step-primary" aria-labelledby="tts-studio-step-text">
              <div className="tts-studio-step-header">
                <div className="control-section-heading">
                  <span>01</span>
                  <strong id="tts-studio-step-text">输入文案</strong>
                </div>
                <div className="tts-studio-step-copy">
                  <p>先整理要播报的内容，再统一完成音色和语速设置。</p>
                </div>
              </div>

              <TextField
                id="tts-studio-text"
                className="tts-studio-textarea"
                fullWidth
                multiline
                rows={11}
                placeholder="请输入需要生成的语音内容"
                value={text}
                onChange={(event) => {
                  setText(event.target.value);
                  markPreviewStale();
                }}
              />
            </section>

            <section className="tts-studio-step" aria-labelledby="tts-studio-step-voice">
              <div className="tts-studio-step-header">
                <div className="control-section-heading">
                  <span>02</span>
                  <strong id="tts-studio-step-voice">选择音色</strong>
                </div>
                <div className="tts-studio-step-copy">
                  <p>选择共享克隆音色，或使用 edge-tts 在线音色。</p>
                </div>
              </div>

                <div className="field">
                  <span className="field-label">合成方式</span>
                  <ToggleButtonGroup
                    className="tts-studio-mode-control"
                    exclusive
                    fullWidth
                    value={ttsMode}
                    role="tablist"
                    aria-label="合成方式"
                    onChange={(_, nextMode) => {
                      if (!nextMode) return;
                      setTtsMode(nextMode);
                      markPreviewStale();
                    }}
                  >
                  {TTS_MODE_OPTIONS.map((option) => {
                    const providerStatus = providerStatusById.get(option.providerId) ?? (option.value === "edge-tts" ? EDGE_TTS_STATIC_STATUS : null);
                    const isChecking = option.value === "base" && providerStatusesLoading && !providerStatus;
                    const isDisabled = option.value === "base" && !providerStatus?.available;
                    const statusLabel = isChecking
                      ? "检测中"
                      : providerStatus?.status === "available"
                        ? "可用"
                        : providerStatus?.status === "disabled"
                          ? "未启用"
                          : providerStatus?.status === "unavailable"
                            ? "不可用"
                            : "待确认";
                    const statusTitle = option.value === "base" && qwenProviderReason ? qwenProviderReason : undefined;
                    return (
                      <ToggleButton
                        key={option.value}
                        value={option.value}
                        role="tab"
                        disabled={isDisabled}
                        aria-selected={ttsMode === option.value}
                        title={statusTitle}
                      >
                        <span className="tts-studio-mode-heading">
                          <span className="tts-studio-mode-label">{option.label}</span>
                          <span className={`tts-studio-provider-status ${providerStatus?.status || "checking"}`} title={statusTitle}>
                            {statusLabel}
                          </span>
                        </span>
                        <span className="tts-studio-mode-detail">{option.detail}</span>
                      </ToggleButton>
                    );
                  })}
                  </ToggleButtonGroup>
                  <p className="tts-studio-mode-description">
                    {TTS_MODE_OPTIONS.find((option) => option.value === ttsMode)?.description}
                  </p>
                </div>

              {ttsMode === "base" ? (
                <div className="tts-studio-mode-block">
                  <div className="tts-studio-clone-select">
                    <TextField
                      id="tts-studio-voice-profile"
                      className="field"
                      label="克隆音色"
                      fullWidth
                      size="small"
                      select
                      value={voiceProfileId}
                      disabled={voiceProfilesLoading || voiceProfiles.length === 0}
                      onChange={(event) => {
                        setVoiceProfileId(event.target.value);
                        markPreviewStale();
                      }}
                    >
                      {voiceProfiles.length === 0 ? (
                        <MenuItem value="">请先新增一个音色档案</MenuItem>
                      ) : (
                        voiceProfiles.map((profile) => (
                          <MenuItem key={profile.id} value={profile.id}>
                            {profile.name}
                          </MenuItem>
                        ))
                      )}
                    </TextField>

                    <Button type="button" variant="outlined" size="small" onClick={openCreateVoiceProfile}
                      startIcon={<Icon name="plus" size={15} />}>
                      新增音色
                    </Button>

                    {selectedVoiceProfile ? (
                      <div className="voice-summary tts-studio-selected-profile">
                        <div className="voice-summary-header">
                          <div className="voice-summary-main">
                            <strong>{selectedVoiceProfile.name}</strong>
                            <span>{selectedVoiceProfile.ref_text}</span>
                          </div>
                          <IconButton
                            type="button"
                            aria-label={`编辑音色档案：${selectedVoiceProfile.name}`}
                            title="编辑音色档案"
                            onClick={() => openEditVoiceProfile(selectedVoiceProfile)}
                            size="small"
                          >
                            <Icon name="edit" size={15} />
                          </IconButton>
                        </div>
                        <audio
                          className="audio-player"
                          controls
                          crossOrigin="use-credentials"
                          src={resolveBackendAssetUrl(selectedVoiceProfile.audio_url, backendBaseUrl)}
                        />
                      </div>
                    ) : (
                      <div className="audio-empty tts-studio-audio-empty">
                        从下方音色库选择一个共享档案，或先创建新的克隆音色。
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="tts-studio-mode-block tts-studio-edge-config">
                  <div className="tts-studio-edge-fields">
                    <TextField
                      className="field"
                      label="语言"
                      fullWidth
                      size="small"
                      value="中文"
                      slotProps={{ input: { readOnly: true } }}
                      sx={{ "& .MuiOutlinedInput-root": { backgroundColor: "var(--surface-muted)" } }}
                    />
                    <TextField
                      id="tts-studio-edge-voice"
                      className="field"
                      label="音色"
                      fullWidth
                      size="small"
                      select
                      value={edgeVoice}
                      disabled={edgeVoicesLoading || filteredEdgeVoices.length === 0}
                      onChange={(event) => { setEdgeVoice(event.target.value); markPreviewStale(); }}
                    >
                      {filteredEdgeVoices.length === 0 ? <MenuItem value="">{edgeVoicesLoading ? "加载中" : "暂无可用音色"}</MenuItem> : filteredEdgeVoices.map((voice) => <MenuItem key={voice.id} value={voice.id}>{voice.name || voice.id}{voice.description ? ` · ${voice.description}` : ""}</MenuItem>)}
                    </TextField>
                  </div>
                </div>
              )}
            </section>

            <section className="tts-studio-step tts-studio-step-generate" aria-labelledby="tts-studio-step-generate">
              <div className="tts-studio-step-header">
                <div className="control-section-heading">
                  <span>03</span>
                  <strong id="tts-studio-step-generate">生成语音</strong>
                </div>
                <div className="tts-studio-step-copy">
                  <p>确认文案和音色后先生成 1.0x 原速音频，调速在右侧结果区完成。</p>
                </div>
              </div>

              <Button className="tts-studio-generate-action" type="button" variant="contained" size="large" disabled={!canGenerate} onClick={handleGeneratePreview}
                startIcon={<Icon name={generating ? "loading" : "play"} size={16} />}>
                {generating ? "正在生成语音" : "生成语音"}
              </Button>
            </section>
          </div>

          <aside className="tts-studio-preview" aria-label="试听与交付">
            <div className="tts-studio-preview-heading">
              <Typography variant="kicker" component="span" className="section-kicker with-icon">
                <Icon name="audio" size={13} />
                Audio
              </Typography>
              <h3>试听与交付</h3>
              <p>原速音频、加速版本与下载入口统一保留在这里。</p>
            </div>

            <div className="tts-studio-preview-status" aria-live="polite">
              <div className="tts-studio-preview-status-copy">
                <span>当前任务</span>
                <strong>{previewTitle}</strong>
                <p>{previewDescription}</p>
              </div>
              <Chip
                size="small"
                icon={<Icon name={status === "previewing" ? "loading" : status === "completed" ? "check" : "waves"} size={14} />}
                label={statusLabel}
                sx={{
                  backgroundColor: statusChipColors[status]?.bg || "#f3f1e9",
                  color: statusChipColors[status]?.fg || "#68645b",
                  fontWeight: 600,
                  "& .vf-icon": { color: statusChipColors[status]?.fg || "#68645b" },
                }}
              />
            </div>

            <div className={`audio-preview-block ${preview ? "has-results" : "is-empty"}`}>
              {preview ? (
                <>
                  <div className="tts-studio-audio-results">
                    <article className="tts-studio-audio-result">
                      <div className="tts-studio-audio-result-header">
                        <div>
                          <strong className="tts-studio-audio-result-title">原速音频</strong>
                          <span className="tts-studio-audio-result-rate">1.0x</span>
                        </div>
                        <ProtectedDownloadButton
                          path={originalAudioUrl}
                          filename={originalAudioFilename}
                          backendBaseUrl={backendBaseUrl}
                          disabled={previewStale}
                          aria-label="下载原速音频"
                        >
                          <Icon name="download" size={15} />
                          下载
                        </ProtectedDownloadButton>
                      </div>
                      <ProtectedMedia
                        className="audio-player"
                        path={originalAudioUrl}
                        kind="audio"
                        backendBaseUrl={backendBaseUrl}
                        aria-label="原速音频播放器"
                      />
                    </article>

                    {adjustedAudioUrl ? (
                      <article className="tts-studio-audio-result is-adjusted">
                        <div className="tts-studio-audio-result-header">
                          <div>
                            <strong className="tts-studio-audio-result-title">调速音频</strong>
                            <span className="tts-studio-audio-result-rate">{adjustedSpeechRate?.toFixed(1) || "1.0"}x</span>
                          </div>
                          <ProtectedDownloadButton
                            path={adjustedAudioUrl}
                            filename={adjustedAudioFilename}
                            backendBaseUrl={backendBaseUrl}
                            disabled={previewStale}
                            aria-label="下载调速音频"
                          >
                            <Icon name="download" size={15} />
                            下载
                          </ProtectedDownloadButton>
                        </div>
                        <ProtectedMedia
                          className="audio-player"
                          path={adjustedAudioUrl}
                          kind="audio"
                          backendBaseUrl={backendBaseUrl}
                          aria-label="调速音频播放器"
                        />
                      </article>
                    ) : (
                      <div className="tts-studio-adjusted-empty">
                        <Icon name="refresh" size={15} />
                        选择语速后生成调速版，原速音频会继续保留。
                      </div>
                    )}
                  </div>

                  <div className="speed-control tts-studio-preview-speed">
                    <div className="speed-control-heading">
                      <div>
                        <span className="field-label">调速倍率</span>
                        <small>从 1.0x 原速开始，仅支持加速</small>
                      </div>
                      <strong>{speechRate.toFixed(1)}x</strong>
                    </div>
                    <Slider
                      min={1.0}
                      max={1.5}
                      step={0.1}
                      value={speechRate}
                      disabled={!preview || previewStale || generating || applyingSpeechRate}
                      aria-label="调速倍率"
                      marks
                      onChange={(_, value) => setSpeechRate(value)}
                    />
                  </div>

                  <div className="tts-studio-preview-actions">
                    <Button
                      type="button"
                      variant="outlined"
                      size="small"
                      disabled={previewStale || applyingSpeechRate || !hasPendingRate}
                      onClick={handleApplySpeechRate}
                      startIcon={<Icon name={applyingSpeechRate ? "loading" : "refresh"} size={15} />}
                    >
                      {applyingSpeechRate ? "正在生成调速版" : "生成调速版"}
                    </Button>
                  </div>
                </>
              ) : (
                <div className="empty-state tts-studio-empty-state">
                  <div className={`state-orb ${status}`} aria-hidden="true">
                    <Icon name={generating ? "loading" : "music"} size={28} />
                  </div>
                  <div className="tts-studio-empty-copy">
                    <h3>{generating ? "正在生成原速音频" : "暂无可试听音频"}</h3>
                    <p>
                      {generating
                        ? "生成完成后，播放器和下载入口会显示在这里。"
                        : "完成左侧文案与音色设置并生成语音后，即可在这里试听和下载。"}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </aside>
        </div>
      </section>

      <section className="workspace-panel tts-studio-library" aria-labelledby="tts-studio-library-title">
        <div className="panel-heading tts-studio-library-heading">
          <div>
            <Typography variant="kicker" component="span" className="section-kicker">Voice Library</Typography>
            <h2 id="tts-studio-library-title">共享克隆音色库</h2>
          </div>
          <Button type="button" variant="outlined" size="small" onClick={openCreateVoiceProfile}
            startIcon={<Icon name="plus" size={15} />}>
            新增音色
          </Button>
        </div>

        <p className="tts-studio-library-note">这里保留所有共享音色档案，用于快速切换、试听和维护已有克隆音色。</p>

        {voiceProfilesLoading ? (
          <div className="tts-studio-library-empty">
            <Icon name="loading" size={18} />
            正在加载音色档案
          </div>
        ) : voiceProfiles.length ? (
          <div className="tts-studio-profile-list">
            {voiceProfiles.map((profile) => (
              <article
                className={`tts-studio-profile-row ${ttsMode === "base" && voiceProfileId === profile.id ? "is-current" : ""}`}
                key={profile.id}
              >
                <div className="tts-studio-profile-copy">
                  <strong>{profile.name}</strong>
                  <span>{languages.find((item) => item.id === profile.language)?.label || profile.language}</span>
                  <p>{profile.ref_text}</p>
                </div>

                <audio
                  className="audio-player"
                  controls
                  crossOrigin="use-credentials"
                  src={resolveBackendAssetUrl(profile.audio_url, backendBaseUrl)}
                />

                <div className="tts-studio-profile-actions">
                  <Button
                    type="button"
                    variant="outlined"
                    size="small"
                    disabled={!qwenProviderAvailable}
                    title={qwenProviderAvailable ? "使用这个克隆音色" : qwenProviderReason || "本地音色克隆当前不可用"}
                    onClick={() => {
                      if (!qwenProviderAvailable) return;
                      setTtsMode("base");
                      setVoiceProfileId(profile.id);
                      markPreviewStale();
                    }}
                    startIcon={<Icon name="check" size={15} />}
                  >
                    使用音色
                  </Button>
                  <IconButton
                    type="button"
                    aria-label={`编辑音色：${profile.name}`}
                    title="编辑音色"
                    onClick={() => openEditVoiceProfile(profile)}
                    size="small"
                  >
                    <Icon name="edit" size={16} />
                  </IconButton>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="tts-studio-library-empty">
            <Icon name="audio" size={21} />
            <span>还没有可用的共享音色档案。</span>
          </div>
        )}
      </section>

      <Dialog
        open={Boolean(profileDialog)}
        onClose={closeVoiceProfileDialog}
        aria-labelledby="tts-voice-dialog-title"
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", pr: 1.5 }}>
          <div>
            <Typography variant="kicker" component="span" className="section-kicker">Voice Library</Typography>
            <h3 id="tts-voice-dialog-title">{isEditingVoiceProfile ? "编辑克隆音色" : "新增克隆音色"}</h3>
          </div>
          <IconButton type="button" aria-label="关闭音色档案弹窗" onClick={closeVoiceProfileDialog} size="small">
            <Icon name="x" size={17} />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          <div className="modal-body">
            <TextField
              id="tts-voice-profile-name"
              className="field"
              label="音色名称"
              fullWidth
              size="small"
              type="text"
              placeholder="例如：中年男声"
              value={profileName}
              onChange={(event) => setProfileName(event.target.value)}
            />

            <TextField
              id="tts-voice-profile-language"
              className="field"
              label="语言"
              fullWidth
              size="small"
              select
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
            >
              {languages.map((item) => (
                <MenuItem key={item.id} value={item.id}>
                  {item.label}
                </MenuItem>
              ))}
            </TextField>

            <span className="field-label">参考音频{isEditingVoiceProfile ? "" : "*"}</span>
            <label className={`upload-dropzone compact ${refAudioFile ? "is-filled" : ""}`}>
              <span className="upload-placeholder">
                <Icon name={refAudioFile ? "audio" : "upload"} size={22} />
                <strong>{refAudioFile ? refAudioFile.name : "上传参考音频"}</strong>
                <small>
                  {refAudioFile
                    ? formatFileSize(refAudioFile.size)
                    : isEditingVoiceProfile
                      ? "不上传则继续保留当前参考音频"
                      : "用于保存新的克隆音色"}
                </small>
              </span>
              <input ref={refAudioInputRef} type="file" accept="audio/*" onChange={handleReferenceAudioChange} />
            </label>

            {refAudioFile && (
              <div className="file-row">
                <span>{refAudioFile.name}</span>
                <Button variant="text" size="small" type="button" onClick={clearReferenceAudio}>
                  移除
                </Button>
              </div>
            )}

            {refAudioUrl ? (
              <audio className="audio-player" controls src={refAudioUrl} />
            ) : (
              isEditingVoiceProfile &&
              editingVoiceProfile && (
                <audio
                  className="audio-player"
                  controls
                  crossOrigin="use-credentials"
                  src={resolveBackendAssetUrl(editingVoiceProfile.audio_url, backendBaseUrl)}
                />
              )
            )}

            <TextField
              id="tts-voice-profile-ref-text"
              className="field"
              label="参考文本"
              fullWidth
              size="small"
              multiline
              rows={4}
              placeholder="写下参考音频中实际说出的内容"
              value={refText}
              onChange={(event) => setRefText(event.target.value)}
            />

            {profileError && <div className="form-alert failed">{profileError}</div>}

            {deleteConfirmation && (
              <div className="delete-confirm-panel" role="alertdialog" aria-labelledby="tts-voice-delete-title">
                <strong id="tts-voice-delete-title">确认删除这个共享音色？</strong>
                <span>删除后会移除参考音频和档案记录，无法恢复。</span>
                <div className="delete-confirm-actions">
                  <Button
                    type="button"
                    variant="outlined"
                    disabled={deletingProfile}
                    onClick={() => setDeleteConfirmation(false)}
                  >
                    取消
                  </Button>
                  <Button type="button" color="error" variant="contained" disabled={deletingProfile} onClick={handleDeleteVoiceProfile}
                    startIcon={<Icon name={deletingProfile ? "loading" : "trash"} size={16} />}>
                    {deletingProfile ? "正在删除" : "确认删除"}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </DialogContent>
        <DialogActions className={`modal-actions ${isEditingVoiceProfile ? "with-delete" : ""}`}>
          {isEditingVoiceProfile && (
            <Button
              type="button"
              color="error"
              disabled={savingProfile || deletingProfile}
              onClick={() => setDeleteConfirmation(true)}
              startIcon={<Icon name="trash" size={16} />}
            >
              删除
            </Button>
          )}
          <Button type="button" onClick={closeVoiceProfileDialog}>
            取消
          </Button>
          <Button
            type="button"
            variant="contained"
            disabled={
              savingProfile ||
              deletingProfile ||
              !profileName.trim() ||
              !refText.trim() ||
              (!isEditingVoiceProfile && !refAudioFile)
            }
            onClick={handleSaveVoiceProfile}
            startIcon={<Icon name={savingProfile ? "loading" : "save"} size={16} />}
          >
            {savingProfile ? "正在保存" : isEditingVoiceProfile ? "保存修改" : "保存音色"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
