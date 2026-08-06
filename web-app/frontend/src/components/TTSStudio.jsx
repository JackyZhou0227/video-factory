import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";
import { apiFetch, resolveBackendAssetUrl, useBackendBaseUrl } from "../lib/backend";

const TTS_MODE_OPTIONS = [
  { value: "base", providerId: "qwen3_tts_base", label: "音色克隆", detail: "Qwen3-TTS Base · 本地" },
  { value: "edge-tts", providerId: "edge_tts", label: "预设音色", detail: "Edge-TTS · 云端" },
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

async function readApiError(response) {
  const payload = await response.json().catch(() => null);
  if (typeof payload?.detail === "string") return payload.detail;
  if (typeof payload?.message === "string") return payload.message;
  return `请求失败（HTTP ${response.status}）`;
}

export default function TTSStudio({ active = false }) {
  const backendBaseUrl = useBackendBaseUrl();
  const refAudioInputRef = useRef(null);
  const [text, setText] = useState("");
  const [ttsMode, setTtsMode] = useState("edge-tts");
  const [providerStatuses, setProviderStatuses] = useState([]);
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
  const [error, setError] = useState("");
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
    setError("");
  }, [preview]);

  const refreshVoiceProfiles = useCallback(async () => {
    setVoiceProfilesLoading(true);
    try {
      const response = await apiFetch("/api/tts-studio/voice-profiles", undefined, backendBaseUrl);
      if (!response.ok) throw new Error(await readApiError(response));
      const list = await response.json();
      const nextProfiles = Array.isArray(list) ? list : [];
      setVoiceProfiles(nextProfiles);
      setVoiceProfileId((current) => {
        if (current && nextProfiles.some((item) => item.id === current)) return current;
        return nextProfiles[0]?.id || "";
      });
    } catch (err) {
      setVoiceProfiles([]);
      setVoiceProfileId("");
      setError(err.message || "加载音色档案失败");
    } finally {
      setVoiceProfilesLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    if (!active) return undefined;
    let cancelled = false;
    setProviderStatusesLoading(true);
    setProviderStatusError("");
    apiFetch("/api/tts-studio/providers", undefined, backendBaseUrl)
      .then(async (response) => {
        if (!response.ok) throw new Error(await readApiError(response));
        return response.json();
      })
      .then((list) => {
        if (cancelled) return;
        setProviderStatuses(Array.isArray(list) ? list : []);
      })
      .catch((err) => {
        if (cancelled) return;
        setProviderStatuses([]);
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
    apiFetch("/api/tts-studio/edge-tts/voices", undefined, backendBaseUrl)
      .then(async (response) => {
        if (!response.ok) throw new Error(await readApiError(response));
        return response.json();
      })
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
    apiFetch("/api/tts-studio/languages", undefined, backendBaseUrl)
      .then(async (response) => {
        if (!response.ok) throw new Error(await readApiError(response));
        return response.json();
      })
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
      const response = await apiFetch(
        endpoint,
        { method: isEditingVoiceProfile ? "PUT" : "POST", body: formData },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await readApiError(response));
      const saved = await response.json();
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
      const response = await apiFetch(
        `/api/tts-studio/voice-profiles/${editingVoiceProfile.id}`,
        { method: "DELETE" },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await readApiError(response));
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
    setError("");
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

      const response = await apiFetch(endpoint, { method: "POST", body: formData }, backendBaseUrl);
      if (!response.ok) throw new Error(await readApiError(response));
      const generated = await response.json();
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
    } catch (err) {
      setError(err.message || "生成语音失败");
    } finally {
      setGenerating(false);
    }
  }, [backendBaseUrl, edgeLanguage, edgeVoice, language, text, ttsMode, voiceProfileId]);

  const handleApplySpeechRate = useCallback(async () => {
    if (!preview?.original_audio_url) return;
    setApplyingSpeechRate(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("audio_url", preview.original_audio_url);
      formData.append("speech_rate", String(speechRate));
      const response = await apiFetch(
        "/api/tts-studio/preview/speech-rate",
        { method: "POST", body: formData },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await readApiError(response));
      const updated = await response.json();
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
    } catch (err) {
      setError(err.message || "调整语速失败");
    } finally {
      setApplyingSpeechRate(false);
    }
  }, [backendBaseUrl, preview?.original_audio_url, speechRate]);

  const originalAudioUrl = preview?.original_audio_url || preview?.audio_url || "";
  const adjustedAudioUrl = preview?.adjusted_audio_url || preview?.processed_audio_url || "";
  const adjustedSpeechRate = adjustedAudioUrl ? Number(preview?.adjusted_speech_rate ?? preview?.speech_rate ?? 1) : null;
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
      <section className="workspace-panel tts-studio-panel" aria-labelledby="tts-studio-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">TTS Studio</span>
            <h2 id="tts-studio-title">独立语音合成</h2>
          </div>
          <span className={`status-pill ${status}`}>
            <Icon name={status === "previewing" ? "loading" : status === "completed" ? "check" : "waves"} size={14} />
            {statusLabel}
          </span>
        </div>

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

              <label className="field" htmlFor="tts-studio-text">
                <span className="field-label">合成文本</span>
                <textarea
                  id="tts-studio-text"
                  className="control textarea tts-studio-textarea"
                  rows={11}
                  placeholder="请输入需要生成的语音内容"
                  value={text}
                  onChange={(event) => {
                    setText(event.target.value);
                    markPreviewStale();
                  }}
                />
              </label>
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
                <div className="segmented-control tts-studio-mode-control" role="tablist" aria-label="合成方式">
                  {TTS_MODE_OPTIONS.map((option) => {
                    const providerStatus = providerStatusById.get(option.providerId);
                    const isChecking = providerStatusesLoading && !providerStatus;
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
                    return (
                      <button
                        className={`segment ${ttsMode === option.value ? "is-active" : ""}`}
                        disabled={isDisabled}
                        key={option.value}
                        type="button"
                        role="tab"
                        aria-selected={ttsMode === option.value}
                        onClick={() => {
                          setTtsMode(option.value);
                          markPreviewStale();
                        }}
                      >
                        <span className="tts-studio-mode-heading">
                          <span className="tts-studio-mode-label">{option.label}</span>
                          <span className={`tts-studio-provider-status ${providerStatus?.status || "checking"}`}>
                            {statusLabel}
                          </span>
                        </span>
                        <span className="tts-studio-mode-detail">{option.detail}</span>
                      </button>
                    );
                  })}
                </div>
                {qwenProviderReason && (
                  <p className="tts-studio-provider-note" role="status">
                    {qwenProviderReason}
                  </p>
                )}
              </div>

              {ttsMode === "base" ? (
                <div className="tts-studio-mode-block">
                  <div className="tts-studio-clone-select">
                    <label className="field" htmlFor="tts-studio-voice-profile">
                      <span className="field-label">克隆音色</span>
                      <select
                        id="tts-studio-voice-profile"
                        className="control"
                        value={voiceProfileId}
                        disabled={voiceProfilesLoading || voiceProfiles.length === 0}
                        onChange={(event) => {
                          setVoiceProfileId(event.target.value);
                          markPreviewStale();
                        }}
                      >
                        {voiceProfiles.length === 0 ? (
                          <option value="">请先新增一个音色档案</option>
                        ) : (
                          voiceProfiles.map((profile) => (
                            <option key={profile.id} value={profile.id}>
                              {profile.name}
                            </option>
                          ))
                        )}
                      </select>
                    </label>

                    <button className="secondary-action compact-action" type="button" onClick={openCreateVoiceProfile}>
                      <Icon name="plus" size={15} />
                      新增音色
                    </button>

                    {selectedVoiceProfile ? (
                      <div className="voice-summary tts-studio-selected-profile">
                        <div className="voice-summary-header">
                          <div className="voice-summary-main">
                            <strong>{selectedVoiceProfile.name}</strong>
                            <span>{selectedVoiceProfile.ref_text}</span>
                          </div>
                          <button
                            className="icon-button"
                            type="button"
                            aria-label={`编辑音色档案：${selectedVoiceProfile.name}`}
                            title="编辑音色档案"
                            onClick={() => openEditVoiceProfile(selectedVoiceProfile)}
                          >
                            <Icon name="edit" size={15} />
                          </button>
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
                    <div className="field">
                      <span className="field-label">语言</span>
                      <div className="control tts-studio-static-language">中文</div>
                    </div>
                    <label className="field" htmlFor="tts-studio-edge-voice">
                      <span className="field-label">音色</span>
                      <select id="tts-studio-edge-voice" className="control" value={edgeVoice} disabled={edgeVoicesLoading || filteredEdgeVoices.length === 0} onChange={(event) => { setEdgeVoice(event.target.value); markPreviewStale(); }}>
                        {filteredEdgeVoices.length === 0 ? <option value="">{edgeVoicesLoading ? "加载中" : "暂无可用音色"}</option> : filteredEdgeVoices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name || voice.id}{voice.description ? ` · ${voice.description}` : ""}</option>)}
                      </select>
                    </label>
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

              <button className="primary-action tts-studio-generate-action" type="button" disabled={!canGenerate} onClick={handleGeneratePreview}>
                <Icon name={generating ? "loading" : "play"} size={16} />
                {generating ? "正在生成语音" : "生成语音"}
              </button>

              {error && <div className="form-alert failed">{error}</div>}
            </section>
          </div>

          <aside className="tts-studio-preview" aria-label="试听与交付">
            <div className="tts-studio-preview-heading">
              <span className="section-kicker with-icon">
                <Icon name="audio" size={13} />
                Audio
              </span>
              <h3>试听与交付</h3>
              <p>原速音频、加速版本与下载入口统一保留在这里。</p>
            </div>

            <div className="tts-studio-preview-status" aria-live="polite">
              <div className="tts-studio-preview-status-copy">
                <span>当前任务</span>
                <strong>{previewTitle}</strong>
                <p>{previewDescription}</p>
              </div>
              <span className={`status-pill ${status}`}>
                <Icon name={status === "previewing" ? "loading" : status === "completed" ? "check" : "waves"} size={14} />
                {statusLabel}
              </span>
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
                        <a
                          className={`download-action compact-action ${previewStale ? "is-disabled" : ""}`}
                          href={resolveBackendAssetUrl(originalAudioUrl, backendBaseUrl)}
                          download
                          aria-label="下载原速音频"
                          aria-disabled={previewStale}
                          onClick={(event) => {
                            if (previewStale) event.preventDefault();
                          }}
                        >
                          <Icon name="download" size={15} />
                          下载
                        </a>
                      </div>
                      <audio className="audio-player" controls src={resolveBackendAssetUrl(originalAudioUrl, backendBaseUrl)} />
                    </article>

                    {adjustedAudioUrl ? (
                      <article className="tts-studio-audio-result is-adjusted">
                        <div className="tts-studio-audio-result-header">
                          <div>
                            <strong className="tts-studio-audio-result-title">调速音频</strong>
                            <span className="tts-studio-audio-result-rate">{adjustedSpeechRate?.toFixed(1) || "1.0"}x</span>
                          </div>
                          <a
                            className={`download-action compact-action ${previewStale ? "is-disabled" : ""}`}
                            href={resolveBackendAssetUrl(adjustedAudioUrl, backendBaseUrl)}
                            download
                            aria-label="下载调速音频"
                            aria-disabled={previewStale}
                            onClick={(event) => {
                              if (previewStale) event.preventDefault();
                            }}
                          >
                            <Icon name="download" size={15} />
                            下载
                          </a>
                        </div>
                        <audio className="audio-player" controls src={resolveBackendAssetUrl(adjustedAudioUrl, backendBaseUrl)} />
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
                    <input
                      className="speed-slider"
                      type="range"
                      min="1.0"
                      max="1.5"
                      step="0.1"
                      value={speechRate}
                      disabled={!preview || previewStale || generating || applyingSpeechRate}
                      aria-label="调速倍率"
                      onChange={(event) => setSpeechRate(Number(event.target.value))}
                    />
                  </div>

                  <div className="tts-studio-preview-actions">
                    <button
                      className="secondary-action compact-action"
                      type="button"
                      disabled={previewStale || applyingSpeechRate || !hasPendingRate}
                      onClick={handleApplySpeechRate}
                    >
                      <Icon name={applyingSpeechRate ? "loading" : "refresh"} size={15} />
                      {applyingSpeechRate ? "正在生成调速版" : "生成调速版"}
                    </button>
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
            <span className="section-kicker">Voice Library</span>
            <h2 id="tts-studio-library-title">共享克隆音色库</h2>
          </div>
          <button className="secondary-action compact-action" type="button" onClick={openCreateVoiceProfile}>
            <Icon name="plus" size={15} />
            新增音色
          </button>
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
                  <button
                    className="secondary-action compact-action"
                    type="button"
                    disabled={!qwenProviderAvailable}
                    title={qwenProviderAvailable ? "使用这个克隆音色" : qwenProviderReason || "本地音色克隆当前不可用"}
                    onClick={() => {
                      if (!qwenProviderAvailable) return;
                      setTtsMode("base");
                      setVoiceProfileId(profile.id);
                      markPreviewStale();
                    }}
                  >
                    <Icon name="check" size={15} />
                    使用音色
                  </button>
                  <button
                    className="icon-button"
                    type="button"
                    aria-label={`编辑音色：${profile.name}`}
                    title="编辑音色"
                    onClick={() => openEditVoiceProfile(profile)}
                  >
                    <Icon name="edit" size={16} />
                  </button>
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

      {profileDialog && (
        <div className="modal-backdrop" role="presentation">
          <section className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="tts-voice-dialog-title">
            <div className="modal-heading">
              <div>
                <span className="section-kicker">Voice Library</span>
                <h3 id="tts-voice-dialog-title">{isEditingVoiceProfile ? "编辑克隆音色" : "新增克隆音色"}</h3>
              </div>
              <button className="icon-button" type="button" aria-label="关闭音色档案弹窗" onClick={closeVoiceProfileDialog}>
                <Icon name="x" size={17} />
              </button>
            </div>

            <div className="modal-body">
              <label className="field" htmlFor="tts-voice-profile-name">
                <span className="field-label">音色名称</span>
                <input
                  id="tts-voice-profile-name"
                  className="control"
                  type="text"
                  placeholder="例如：中年男声"
                  value={profileName}
                  onChange={(event) => setProfileName(event.target.value)}
                />
              </label>

              <label className="field" htmlFor="tts-voice-profile-language">
                <span className="field-label">语言</span>
                <select
                  id="tts-voice-profile-language"
                  className="control"
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                >
                  {languages.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

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
                  <button className="text-button" type="button" onClick={clearReferenceAudio}>
                    移除
                  </button>
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

              <label className="field" htmlFor="tts-voice-profile-ref-text">
                <span className="field-label">参考文本*</span>
                <textarea
                  id="tts-voice-profile-ref-text"
                  className="control textarea"
                  rows={4}
                  placeholder="写下参考音频中实际说出的内容"
                  value={refText}
                  onChange={(event) => setRefText(event.target.value)}
                />
              </label>

              {profileError && <div className="form-alert failed">{profileError}</div>}

              {deleteConfirmation && (
                <div className="delete-confirm-panel" role="alertdialog" aria-labelledby="tts-voice-delete-title">
                  <strong id="tts-voice-delete-title">确认删除这个共享音色？</strong>
                  <span>删除后会移除参考音频和档案记录，无法恢复。</span>
                  <div className="delete-confirm-actions">
                    <button
                      className="secondary-action"
                      type="button"
                      disabled={deletingProfile}
                      onClick={() => setDeleteConfirmation(false)}
                    >
                      取消
                    </button>
                    <button className="danger-action" type="button" disabled={deletingProfile} onClick={handleDeleteVoiceProfile}>
                      <Icon name={deletingProfile ? "loading" : "trash"} size={16} />
                      {deletingProfile ? "正在删除" : "确认删除"}
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className={`modal-actions ${isEditingVoiceProfile ? "with-delete" : ""}`}>
              {isEditingVoiceProfile && (
                <button
                  className="danger-action"
                  type="button"
                  disabled={savingProfile || deletingProfile}
                  onClick={() => setDeleteConfirmation(true)}
                >
                  <Icon name="trash" size={16} />
                  删除
                </button>
              )}
              <button className="secondary-action" type="button" onClick={closeVoiceProfileDialog}>
                取消
              </button>
              <button
                className="primary-action"
                type="button"
                disabled={
                  savingProfile ||
                  deletingProfile ||
                  !profileName.trim() ||
                  !refText.trim() ||
                  (!isEditingVoiceProfile && !refAudioFile)
                }
                onClick={handleSaveVoiceProfile}
              >
                <Icon name={savingProfile ? "loading" : "save"} size={16} />
                {savingProfile ? "正在保存" : isEditingVoiceProfile ? "保存修改" : "保存音色"}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
