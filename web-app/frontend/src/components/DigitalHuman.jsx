import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import Icon from "./Icon";
import { apiFetch, resolveBackendAssetUrl, useBackendBaseUrl } from "../lib/backend";

const MODE_OPTIONS = [
  { value: "text", label: "本地模型生成语音" },
  { value: "audio", label: "直接上传音频" },
];

const TTS_MODE_OPTIONS = [
  { value: "base", label: "语音克隆" },
  { value: "customvoice", label: "预置音色" },
];

const SPEECH_RATE_OPTIONS = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5];

const STEP_LABELS = {
  idle: "等待素材",
  previewing: "生成试听",
  ready: "语音已就绪",
  pending: "任务排队中",
  running: "正在生成视频",
  completed: "生成完成",
  failed: "生成失败",
};

const VIDEO_STEP_LABELS = {
  idle: "等待素材",
  ready: "可生成视频",
  pending: "任务排队中",
  running: "正在生成视频",
  submitted: "任务已提交",
  completed: "视频已生成",
  failed: "生成失败",
};

const RUNNINGHUB_TASKS_URL = "https://www.runninghub.cn/bill-task";
const RUNNINGHUB_WORKS_URL = "https://www.runninghub.cn/user-center";

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

const DEFAULT_SPEAKERS = [
  {
    id: "Vivian",
    display_name: "Vivian",
    native_language: "Chinese",
    native_language_label: "中文",
    short_description: "明亮年轻女声，清晰有精神。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Serena",
    display_name: "Serena",
    native_language: "Chinese",
    native_language_label: "中文",
    short_description: "温柔年轻女声，亲和舒缓。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Uncle_Fu",
    display_name: "傅叔",
    native_language: "Chinese",
    native_language_label: "中文",
    short_description: "低醇成熟男声，稳重可信。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Dylan",
    display_name: "Dylan",
    native_language: "Chinese",
    native_language_label: "中文（北京口音）",
    short_description: "清朗北京男声，自然生活感。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Eric",
    display_name: "Eric",
    native_language: "Chinese",
    native_language_label: "中文（四川口音）",
    short_description: "活泼成都男声，明亮略带方言感。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Ryan",
    display_name: "Ryan",
    native_language: "English",
    native_language_label: "英语",
    short_description: "动感英文男声，节奏感强。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Aiden",
    display_name: "Aiden",
    native_language: "English",
    native_language_label: "英语（美式）",
    short_description: "阳光美式男声，清晰自然。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Ono_Anna",
    display_name: "Ono Anna",
    native_language: "Japanese",
    native_language_label: "日语",
    short_description: "轻盈日文女声，俏皮灵动。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Sohee",
    display_name: "Sohee",
    native_language: "Korean",
    native_language_label: "韩语",
    short_description: "温暖韩文女声，情绪丰富。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
];

function pollTask(taskId, signal, backendBaseUrl) {
  return apiFetch(`/api/task/${taskId}`, { signal }, backendBaseUrl).then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  });
}

function isReadableMessage(message) {
  return typeof message === "string" && message.trim() && !/[锟]/.test(message);
}

function formatFileSize(size) {
  if (!size) return "";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function DigitalHuman() {
  const backendBaseUrl = useBackendBaseUrl();
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);
  const [mode, setMode] = useState("text");
  const [text, setText] = useState("");
  const [audioFile, setAudioFile] = useState(null);
  const [audioLocalUrl, setAudioLocalUrl] = useState(null);
  const [speakers, setSpeakers] = useState(DEFAULT_SPEAKERS);
  const [speaker, setSpeaker] = useState("Uncle_Fu");
  const [languages, setLanguages] = useState(DEFAULT_LANGUAGES);
  const [language, setLanguage] = useState("Chinese");
  const [ttsMode, setTtsMode] = useState("base");
  const [speechRate, setSpeechRate] = useState(1.0);
  const [voiceProfiles, setVoiceProfiles] = useState([]);
  const [voiceProfilesLoading, setVoiceProfilesLoading] = useState(false);
  const [voiceProfileId, setVoiceProfileId] = useState("");
  const [voiceProfileName, setVoiceProfileName] = useState("");
  const [voiceProfileError, setVoiceProfileError] = useState("");
  const [voiceProfileNotice, setVoiceProfileNotice] = useState("");
  const [savingVoiceProfile, setSavingVoiceProfile] = useState(false);
  const [deletingVoiceProfile, setDeletingVoiceProfile] = useState(false);
  const [instruct, setInstruct] = useState("");
  const [refAudioFile, setRefAudioFile] = useState(null);
  const [refAudioUrl, setRefAudioUrl] = useState(null);
  const [refText, setRefText] = useState("");
  const [voiceProfileDialogOpen, setVoiceProfileDialogOpen] = useState(false);
  const [voiceProfileDialogMode, setVoiceProfileDialogMode] = useState("create");
  const [editingVoiceProfileId, setEditingVoiceProfileId] = useState("");
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [voiceMenuOpen, setVoiceMenuOpen] = useState(false);
  const [voiceProfileMenuOpen, setVoiceProfileMenuOpen] = useState(false);
  const [languageMenuOpen, setLanguageMenuOpen] = useState(false);

  const [audioPreview, setAudioPreview] = useState(null);
  const [audioPreviewStale, setAudioPreviewStale] = useState(false);
  const [taskStatus, setTaskStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const [videoUrl, setVideoUrl] = useState(null);
  const [runningHubResult, setRunningHubResult] = useState(null);
  const [error, setError] = useState(null);
  const [audioPreviewError, setAudioPreviewError] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [applyingSpeechRate, setApplyingSpeechRate] = useState(false);
  const [generating, setGenerating] = useState(false);

  const pollRef = useRef(null);
  const imageInputRef = useRef(null);
  const audioInputRef = useRef(null);
  const refAudioInputRef = useRef(null);
  const voiceSelectRef = useRef(null);
  const voiceProfileSelectRef = useRef(null);
  const languageSelectRef = useRef(null);
  const audioInputRevisionRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/speakers", undefined, backendBaseUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((list) => {
        if (cancelled) return;
        const nextSpeakers = Array.isArray(list) && list.length > 0 ? list : DEFAULT_SPEAKERS;
        setSpeakers(nextSpeakers);
        setSpeaker((current) =>
          nextSpeakers.some((item) => item.id === current) ? current : nextSpeakers[0].id
        );
      })
      .catch(() => {
        if (cancelled) return;
        setSpeakers(DEFAULT_SPEAKERS);
      });
    return () => {
      cancelled = true;
    };
  }, [backendBaseUrl]);

  useEffect(() => {
    let cancelled = false;
    setVoiceProfilesLoading(true);
    apiFetch("/api/voice-profiles", undefined, backendBaseUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((list) => {
        if (cancelled) return;
        const nextProfiles = Array.isArray(list) ? list : [];
        setVoiceProfiles(nextProfiles);
        setVoiceProfileId((current) => {
          if (current && nextProfiles.some((item) => item.id === current)) return current;
          return nextProfiles[0]?.id || "";
        });
      })
      .catch(() => {
        if (cancelled) return;
        setVoiceProfiles([]);
        setVoiceProfileId("");
      })
      .finally(() => {
        if (cancelled) return;
        setVoiceProfilesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [backendBaseUrl]);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/tts/languages", undefined, backendBaseUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((list) => {
        if (cancelled) return;
        const nextLanguages = Array.isArray(list) && list.length > 0 ? list : DEFAULT_LANGUAGES;
        setLanguages(nextLanguages);
        setLanguage((current) =>
          nextLanguages.some((item) => item.id === current) ? current : nextLanguages[0].id
        );
      })
      .catch(() => {
        if (cancelled) return;
        setLanguages(DEFAULT_LANGUAGES);
      });

    return () => {
      cancelled = true;
    };
  }, [backendBaseUrl]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
      if (imagePreview) URL.revokeObjectURL(imagePreview);
      if (audioLocalUrl) URL.revokeObjectURL(audioLocalUrl);
      if (refAudioUrl) URL.revokeObjectURL(refAudioUrl);
    };
  }, [audioLocalUrl, imagePreview, refAudioUrl]);

  useEffect(() => {
    if (!voiceMenuOpen && !voiceProfileMenuOpen && !languageMenuOpen) return;

    const handlePointerDown = (event) => {
      if (!voiceSelectRef.current?.contains(event.target)) setVoiceMenuOpen(false);
      if (!voiceProfileSelectRef.current?.contains(event.target)) setVoiceProfileMenuOpen(false);
      if (!languageSelectRef.current?.contains(event.target)) setLanguageMenuOpen(false);
    };

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setVoiceMenuOpen(false);
        setVoiceProfileMenuOpen(false);
        setLanguageMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [languageMenuOpen, voiceMenuOpen, voiceProfileMenuOpen]);

  const resetVideoState = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    setTaskStatus("idle");
    setProgress(0);
    setStatusMsg("");
    setVideoUrl(null);
    setRunningHubResult(null);
    setError(null);
    setGenerating(false);
  }, []);

  const resetAudioPreview = useCallback(() => {
    audioInputRevisionRef.current += 1;
    setAudioPreview(null);
    setAudioPreviewStale(false);
    setAudioPreviewError("");
    setApplyingSpeechRate(false);
    setVideoUrl(null);
    setRunningHubResult(null);
    setProgress(0);
    setError(null);
    setStatusMsg("");
    setTaskStatus("idle");
  }, []);

  const markAudioPreviewStale = useCallback(() => {
    audioInputRevisionRef.current += 1;
    setAudioPreviewStale((wasStale) => (audioPreview ? true : wasStale));
    setAudioPreviewError("");
    setVideoUrl(null);
    setRunningHubResult(null);
    setError(null);
    if (taskStatus === "ready") {
      setTaskStatus("idle");
      setStatusMsg("参数已变更，旧试听仍可播放，请重新生成试听后再生成视频。");
    }
  }, [audioPreview, taskStatus]);

  const updateSpeechRate = useCallback(
    (nextRate) => {
      setSpeechRate(nextRate);
    },
    []
  );

  const handleSpeechRateChange = useCallback(
    (event) => {
      updateSpeechRate(Number(event.currentTarget.value));
    },
    [updateSpeechRate]
  );

  const selectedSpeaker = useMemo(
    () => speakers.find((item) => item.id === speaker) ?? null,
    [speaker, speakers]
  );

  const selectedVoiceProfile = useMemo(
    () => voiceProfiles.find((item) => item.id === voiceProfileId) ?? null,
    [voiceProfileId, voiceProfiles]
  );

  const isEditingVoiceProfile = voiceProfileDialogMode === "edit";

  const editingVoiceProfile = useMemo(
    () => voiceProfiles.find((item) => item.id === editingVoiceProfileId) ?? null,
    [editingVoiceProfileId, voiceProfiles]
  );

  useEffect(() => {
    if (!selectedSpeaker || ttsMode !== "customvoice") return;
    setLanguage(selectedSpeaker.native_language || "Chinese");
  }, [selectedSpeaker, ttsMode]);

  useEffect(() => {
    if (!selectedVoiceProfile || ttsMode !== "base") return;
    setLanguage(selectedVoiceProfile.language || "Chinese");
  }, [selectedVoiceProfile, ttsMode]);

  const handleRefAudioChange = useCallback(
    (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      setRefAudioFile(file);
      setRefAudioUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return URL.createObjectURL(file);
      });
    },
    []
  );

  const removeRefAudio = useCallback(() => {
    setRefAudioFile(null);
    setRefAudioUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (refAudioInputRef.current) refAudioInputRef.current.value = "";
  }, []);

  const closeVoiceProfileDialog = useCallback(() => {
    setVoiceProfileDialogOpen(false);
    setVoiceProfileDialogMode("create");
    setEditingVoiceProfileId("");
    setVoiceProfileName("");
    setVoiceProfileError("");
    setDeleteConfirmOpen(false);
    setRefText("");
    removeRefAudio();
  }, [removeRefAudio]);

  const openCreateVoiceProfileDialog = useCallback(() => {
    setVoiceProfileDialogMode("create");
    setEditingVoiceProfileId("");
    setVoiceProfileName("");
    setRefText("");
    removeRefAudio();
    setVoiceProfileError("");
    setVoiceProfileNotice("");
    setDeleteConfirmOpen(false);
    setVoiceProfileDialogOpen(true);
  }, [removeRefAudio]);

  const openEditVoiceProfileDialog = useCallback(
    (profile) => {
      if (!profile) return;
      setVoiceProfileDialogMode("edit");
      setEditingVoiceProfileId(profile.id);
      setVoiceProfileName(profile.name || "");
      setRefText(profile.ref_text || "");
      setLanguage(profile.language || "Chinese");
      removeRefAudio();
      setVoiceProfileError("");
      setVoiceProfileNotice("");
      setDeleteConfirmOpen(false);
      setVoiceProfileDialogOpen(true);
    },
    [removeRefAudio]
  );

  const handleImageChange = useCallback(
    (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const nextPreview = URL.createObjectURL(file);
      setImageFile(file);
      setImagePreview((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return nextPreview;
      });
      resetVideoState();
    },
    [resetVideoState]
  );

  const handleAudioChange = useCallback((event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setAudioFile(file);
    setAudioLocalUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(file);
    });
    setAudioPreview(null);
    setAudioPreviewStale(false);
    setAudioPreviewError("");
    setTaskStatus("ready");
    setVideoUrl(null);
    setRunningHubResult(null);
    setError(null);
    setStatusMsg("上传音频已就绪，可以直接生成视频。");
  }, []);

  const removeImage = useCallback(() => {
    setImageFile(null);
    setImagePreview((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (imageInputRef.current) imageInputRef.current.value = "";
    resetVideoState();
  }, [resetVideoState]);

  const removeAudio = useCallback(() => {
    setAudioFile(null);
    setAudioPreview(null);
    setAudioPreviewStale(false);
    setAudioPreviewError("");
    setAudioLocalUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (audioInputRef.current) audioInputRef.current.value = "";
    resetVideoState();
  }, [resetVideoState]);

  const basePresetReady = Boolean(voiceProfileId && voiceProfiles.some((item) => item.id === voiceProfileId));

  const canPreviewAudio = Boolean(
    mode === "text" &&
      !previewing &&
      text.trim() &&
      language &&
      (ttsMode === "customvoice" ? speaker : basePresetReady)
  );
  const hasConfirmedAudio = Boolean(mode === "text" ? audioPreview?.audio_url && !audioPreviewStale : audioFile);
  const canGenerateVideo = Boolean(!generating && taskStatus !== "submitted" && imageFile && hasConfirmedAudio);

  const canSaveVoiceProfile = Boolean(
    ttsMode === "base" &&
      refText.trim() &&
      voiceProfileName.trim() &&
      !savingVoiceProfile &&
      (isEditingVoiceProfile ? editingVoiceProfileId : refAudioFile)
  );

  const pipelineItems = [
    {
      label: "素材",
      detail: imageFile ? imageFile.name : "等待人物形象",
      state: imageFile ? "completed" : "idle",
      icon: "image",
    },
    {
      label: "语音",
      detail: hasConfirmedAudio ? "已确认可用音频" : mode === "text" ? "先生成试听" : "等待上传音频",
      state: hasConfirmedAudio ? "completed" : taskStatus === "previewing" ? "running" : "idle",
      icon: "mic",
    },
    {
      label: "云端生成",
      detail: taskStatus === "submitted" ? "已提交 RunningHub" : taskStatus === "completed" ? "视频已生成" : taskStatus === "failed" ? "需要检查任务" : "RunningHub 队列",
      state: ["pending", "running"].includes(taskStatus) ? "running" : taskStatus,
      icon: "cloud",
    },
  ];

  const detailMessage = useMemo(() => {
    if (taskStatus === "failed") return error || "任务执行失败，请检查输入后重试。";
    if (taskStatus === "submitted") return statusMsg || "RunningHub 任务已提交成功，请到 RunningHub 查看进度和作品。";
    if (taskStatus === "completed") return "视频已生成，可预览或下载。";
    if (isReadableMessage(statusMsg)) return statusMsg;
    if (taskStatus === "previewing") return "正在调用本地 TTS 生成试听音频。";
    if (taskStatus === "ready") return "试听音频已生成，确认无误后即可提交视频生成。";
    if (taskStatus === "running") return "正在把人物图和确认后的音频提交给 RunningHub。";
    return "先生成并试听语音，再确认生成数字人视频。";
  }, [error, statusMsg, taskStatus]);

  const videoPanelStatus = useMemo(() => {
    if (taskStatus === "completed" && videoUrl) return "completed";
    if (taskStatus === "submitted") return "submitted";
    if (taskStatus === "pending" || taskStatus === "running") return taskStatus;
    if (taskStatus === "failed" && hasConfirmedAudio) return "failed";
    if (imageFile && hasConfirmedAudio) return "ready";
    return "idle";
  }, [hasConfirmedAudio, imageFile, taskStatus, videoUrl]);

  const videoPanelMessage = useMemo(() => {
    if (videoPanelStatus === "completed") return "视频已生成，可在右侧预览或下载。";
    if (videoPanelStatus === "submitted") return "任务已成功提交到 RunningHub。生成时间较长，请打开任务进度或我的作品查看结果。";
    if (videoPanelStatus === "failed") return error || "视频生成失败，请检查素材后重试。";
    if (videoPanelStatus === "pending" || videoPanelStatus === "running") return detailMessage;
    if (imageFile && hasConfirmedAudio) return "图片和口播语音都已就绪，可以提交生成视频。";
    if (imageFile) return "人物图片已就绪，请先在上方完成口播语音。";
    if (hasConfirmedAudio) return "口播语音已就绪，请补充人物图片后再生成视频。";
    return "先在上方完成图片和口播语音，底部只负责生成、预览和下载视频。";
  }, [detailMessage, error, hasConfirmedAudio, imageFile, videoPanelStatus]);

  const previewSpeechRate = Number(audioPreview?.speech_rate ?? 1.0);
  const originalPreviewUrl = resolveBackendAssetUrl(
    audioPreview?.original_audio_url || audioPreview?.audio_url || "",
    backendBaseUrl
  );
  const ratePreviewUrl =
    resolveBackendAssetUrl(audioPreview?.processed_audio_url || "", backendBaseUrl) ||
    (Math.abs(previewSpeechRate - 1.0) > 0.001
      ? resolveBackendAssetUrl(audioPreview?.audio_url || "", backendBaseUrl)
      : "");
  const hasRatePreview = Boolean(ratePreviewUrl && ratePreviewUrl !== originalPreviewUrl);

  const handleAudioPreviewLoadError = useCallback(
    (url) => {
      setAudioPreviewError(`试听音频已生成，但浏览器无法加载音频文件：${url}`);
    },
    []
  );

  const buildBaseVoiceForm = useCallback(
    (formData) => {
      formData.append("voice_profile_id", voiceProfileId);
    },
    [voiceProfileId]
  );

  const handlePreviewAudio = useCallback(async () => {
    if (!canPreviewAudio) return;

    const requestRevision = audioInputRevisionRef.current;
    setPreviewing(true);
    setAudioPreview(null);
    setAudioPreviewStale(false);
    setAudioPreviewError("");
    setVideoUrl(null);
    setRunningHubResult(null);
    setError(null);
    setTaskStatus("previewing");
    setStatusMsg("正在生成试听音频...");

    try {
      const formData = new FormData();
      formData.append("text", text.trim());
      formData.append("language", language);
      formData.append("speech_rate", "1.0");
      let previewEndpoint = "/api/tts/customvoice/preview";

      if (ttsMode === "customvoice") {
        formData.append("speaker", speaker);
        if (instruct.trim()) formData.append("instruct", instruct.trim());
      } else {
        previewEndpoint = "/api/tts/voice-clone/preview";
        buildBaseVoiceForm(formData);
      }

      const response = await apiFetch(previewEndpoint, { method: "POST", body: formData }, backendBaseUrl);
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const data = await response.json();
      if (!data?.audio_url) {
        throw new Error("后端没有返回试听音频地址，请检查 TTS 服务输出。");
      }

      const isCurrentPreview = audioInputRevisionRef.current === requestRevision;
      setAudioPreview(data);
      setSpeechRate(Number(data.speech_rate ?? 1.0));
      setAudioPreviewError("");
      setAudioPreviewStale(!isCurrentPreview);
      setTaskStatus(isCurrentPreview ? "ready" : "idle");
      setStatusMsg(
        isCurrentPreview
          ? "试听音频已生成，请先播放确认。"
          : "试听已生成，但参数已变更。旧试听仍可播放，请重新生成试听后再生成视频。"
      );
    } catch (err) {
      setTaskStatus("failed");
      const message = err.message || "生成试听音频失败";
      setError(message);
      setAudioPreviewError(message);
    } finally {
      setPreviewing(false);
    }
  }, [backendBaseUrl, buildBaseVoiceForm, canPreviewAudio, instruct, language, speaker, text, ttsMode]);

  const handleApplySpeechRate = useCallback(async () => {
    if (!audioPreview?.original_audio_url || applyingSpeechRate) return;

    setApplyingSpeechRate(true);
    setAudioPreviewError("");
    setError(null);

    try {
      const formData = new FormData();
      formData.append("audio_url", audioPreview.original_audio_url);
      formData.append("speech_rate", speechRate.toFixed(1));

      const response = await apiFetch("/api/tts/preview/speech-rate", {
        method: "POST",
        body: formData,
      }, backendBaseUrl);

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const data = await response.json();
      if (!data?.audio_url) {
        throw new Error("后端没有返回调速后的音频地址。");
      }

      setAudioPreview((current) => ({
        ...current,
        audio_url: data.audio_url,
        processed_audio_url: data.processed_audio_url,
        speech_rate: data.speech_rate,
      }));
      setAudioPreviewStale(false);
      setTaskStatus("ready");
      setStatusMsg("语速已应用，请播放确认。");
    } catch (err) {
      const message = err.message || "应用语速失败";
      setError(message);
      setAudioPreviewError(message);
    } finally {
      setApplyingSpeechRate(false);
    }
  }, [applyingSpeechRate, audioPreview, backendBaseUrl, speechRate]);

  const handleSaveVoiceProfile = useCallback(async () => {
    if (!canSaveVoiceProfile) return;

    setSavingVoiceProfile(true);
    setVoiceProfileError("");
    setVoiceProfileNotice("");

    try {
      const formData = new FormData();
      formData.append("name", voiceProfileName.trim());
      formData.append("language", language);
      formData.append("ref_text", refText.trim());
      if (refAudioFile) formData.append("ref_audio", refAudioFile);

      const endpoint = isEditingVoiceProfile
        ? `/api/voice-profiles/${editingVoiceProfileId}`
        : "/api/voice-profiles";

      const response = await apiFetch(endpoint, {
        method: isEditingVoiceProfile ? "PUT" : "POST",
        body: formData,
      }, backendBaseUrl);

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const savedProfile = await response.json();
      setVoiceProfiles((current) => [savedProfile, ...current.filter((item) => item.id !== savedProfile.id)]);
      setVoiceProfileId(savedProfile.id);
      setVoiceProfileNotice(
        isEditingVoiceProfile ? `已更新预设音色：${savedProfile.name}` : `已保存预设音色：${savedProfile.name}`
      );
      setLanguage(savedProfile.language || language || "Chinese");
      closeVoiceProfileDialog();
      markAudioPreviewStale();
    } catch (err) {
      setVoiceProfileError(err.message || "保存音色失败");
    } finally {
      setSavingVoiceProfile(false);
    }
  }, [
    backendBaseUrl,
    canSaveVoiceProfile,
    closeVoiceProfileDialog,
    editingVoiceProfileId,
    isEditingVoiceProfile,
    language,
    markAudioPreviewStale,
    refAudioFile,
    refText,
    voiceProfileName,
  ]);

  const handleDeleteVoiceProfile = useCallback(async () => {
    if (!isEditingVoiceProfile || !editingVoiceProfileId || deletingVoiceProfile) return;

    setDeletingVoiceProfile(true);
    setVoiceProfileError("");

    try {
      const response = await apiFetch(
        `/api/voice-profiles/${editingVoiceProfileId}`,
        { method: "DELETE" },
        backendBaseUrl
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const deletedId = editingVoiceProfileId;
      const nextProfiles = voiceProfiles.filter((item) => item.id !== deletedId);
      setVoiceProfiles(nextProfiles);
      setVoiceProfileId((current) => (current === deletedId ? nextProfiles[0]?.id || "" : current));
      setVoiceProfileNotice("已删除预设音色。");
      closeVoiceProfileDialog();
      markAudioPreviewStale();
    } catch (err) {
      setVoiceProfileError(err.message || "删除音色失败");
    } finally {
      setDeletingVoiceProfile(false);
    }
  }, [
    backendBaseUrl,
    closeVoiceProfileDialog,
    deletingVoiceProfile,
    editingVoiceProfileId,
    isEditingVoiceProfile,
    markAudioPreviewStale,
    voiceProfiles,
  ]);

  const handleGenerateVideo = useCallback(async () => {
    if (!canGenerateVideo) return;

    setGenerating(true);
    setError(null);
    setVideoUrl(null);
    setRunningHubResult(null);
    setProgress(0);
    setTaskStatus("pending");
    setStatusMsg("正在提交视频生成任务...");

    try {
      const formData = new FormData();
      formData.append("image", imageFile);

      if (mode === "text") {
        formData.append("mode", "preview");
        formData.append("audio_url", audioPreview.audio_url);
      } else {
        formData.append("mode", "audio");
        formData.append("audio", audioFile);
      }

      const response = await apiFetch("/api/generate-video", {
        method: "POST",
        body: formData,
      }, backendBaseUrl);

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const { task_id: taskId } = await response.json();
      setTaskStatus("running");
      setStatusMsg("正在上传素材并创建 RunningHub 任务...");

      const controller = new AbortController();
      const poll = async () => {
        try {
          const data = await pollTask(taskId, controller.signal, backendBaseUrl);
          setProgress(data.progress ?? 0);
          setStatusMsg(data.message ?? "");

          if (data.status === "submitted") {
            setTaskStatus("submitted");
            setRunningHubResult({
              taskId: data.runninghub_task_id ?? null,
              taskUrl: data.runninghub_task_url || RUNNINGHUB_TASKS_URL,
              worksUrl: data.runninghub_works_url || RUNNINGHUB_WORKS_URL,
            });
            setStatusMsg(data.message || "RunningHub 任务已提交成功。");
            setProgress(100);
            setGenerating(false);
            return;
          }

          if (data.status === "completed") {
            setTaskStatus("completed");
            setVideoUrl(data.video_url ?? null);
            setRunningHubResult(null);
            setStatusMsg("生成完成");
            setProgress(100);
            setGenerating(false);
            return;
          }

          if (data.status === "failed") {
            setTaskStatus("failed");
            setError(data.error ?? data.message ?? "未知错误");
            setStatusMsg("生成失败");
            setGenerating(false);
            return;
          }

          pollRef.current = setTimeout(poll, 3000);
        } catch (err) {
          if (err.name === "AbortError") return;
          setTaskStatus("failed");
          setError(err.message);
          setGenerating(false);
        }
      };

      pollRef.current = setTimeout(poll, 1200);
    } catch (err) {
      setTaskStatus("failed");
      setError(err.message);
      setGenerating(false);
    }
  }, [audioFile, audioPreview, backendBaseUrl, canGenerateVideo, imageFile, mode]);

  return (
    <>
      <section className="workspace-panel production-panel" aria-labelledby="production-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">制作</span>
            <h2 id="production-title">素材与口播</h2>
          </div>
          <span className="required-note">先试听，再生成视频</span>
        </div>

        <div className="pipeline-strip" aria-label="生产管线状态">
          {pipelineItems.map((item, index) => (
            <div key={item.label} className={`pipeline-step ${item.state}`}>
              <span className="pipeline-index">
                <Icon name={item.state === "completed" ? "check" : item.icon} size={14} />
                <span>{String(index + 1).padStart(2, "0")}</span>
              </span>
              <span className="pipeline-copy">
                <strong>{item.label}</strong>
                <span>{item.detail}</span>
              </span>
            </div>
          ))}
        </div>

        <div className="production-grid">
          <div className="workflow-card media-workflow">
            <div className="control-section-heading">
              <span>01</span>
              <strong>人物素材</strong>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="character-image">
                人物形象图片 *
              </label>
              <label className={`upload-dropzone ${imagePreview ? "is-filled" : ""}`}>
                {imagePreview ? (
                  <span className="image-preview-frame">
                    <img src={imagePreview} alt="人物形象预览" className="preview-img" />
                  </span>
                ) : (
                  <span className="upload-placeholder">
                    <Icon name="imageAdd" size={22} />
                    <strong>选择图片</strong>
                    <small>JPG、PNG 或 WebP</small>
                  </span>
                )}
                <input
                  ref={imageInputRef}
                  id="character-image"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={handleImageChange}
                />
              </label>
              {imageFile && (
                <div className="file-row">
                  <span>{imageFile.name}</span>
                  <button type="button" className="text-button" onClick={removeImage}>
                    移除
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="workflow-card script-workflow">
            <div className="control-section-heading">
              <span>02</span>
              <strong>口播内容</strong>
            </div>

            <div className="field">
              <span className="field-label">语音来源</span>
              <div className="segmented-control" role="tablist" aria-label="语音来源">
                {MODE_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={`segment ${mode === option.value ? "is-active" : ""}`}
                    onClick={() => {
                      setMode(option.value);
                      resetAudioPreview();
                    }}
                    role="tab"
                    aria-selected={mode === option.value}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            {mode === "text" ? (
              <>
                <div className="field">
                  <label className="field-label" htmlFor="script-text">
                    口播文案 *
                  </label>
                  <textarea
                    id="script-text"
                    className="control textarea script-textarea"
                    rows={10}
                    placeholder="请输入口播文案内容"
                    value={text}
                    onChange={(event) => {
                      setText(event.target.value);
                      markAudioPreviewStale();
                    }}
                  />
                </div>
              </>
            ) : (
              <div className="workflow-note">
                直接上传已经确认好的口播音频，后续会与人物图片一起生成数字人视频。
              </div>
            )}
          </div>

          <div className="workflow-card voice-workflow">
            <div className="control-section-heading">
              <span>03</span>
              <strong>语音设置</strong>
            </div>

            {mode === "text" ? (
              <>
                <div className="field">
                  <span className="field-label">TTS 模式</span>
                  <div className="segmented-control" role="tablist" aria-label="TTS 模式">
                    {TTS_MODE_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={`segment ${ttsMode === option.value ? "is-active" : ""}`}
                        onClick={() => {
                          setTtsMode(option.value);
                          markAudioPreviewStale();
                        }}
                        role="tab"
                        aria-selected={ttsMode === option.value}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>

                {ttsMode === "customvoice" ? (
                  <div className="voice-config">
                    <div className="tts-model-note">本地 TTS 服务由 Qwen3-TTS CustomVoice 提供</div>

                    <div className="voice-controls-grid">
                      <div className="field">
                        <label className="field-label" htmlFor="speaker">
                          音色
                        </label>
                        <div className="voice-select" ref={voiceSelectRef}>
                          <button
                            id="speaker"
                            className="voice-select-trigger"
                            type="button"
                            aria-haspopup="listbox"
                            aria-expanded={voiceMenuOpen}
                            onClick={() => setVoiceMenuOpen((open) => !open)}
                          >
                            <span className="voice-trigger-main">
                              <span className="voice-title-row">
                                <strong>{selectedSpeaker?.display_name || speaker}</strong>
                                <span className="voice-inline-meta">
                                  推荐 {selectedSpeaker?.native_language_label || "中文"}
                                </span>
                              </span>
                              <span>{selectedSpeaker?.short_description || "选择本地模型音色"}</span>
                            </span>
                            <span className="voice-select-arrow" aria-hidden="true" />
                          </button>

                          {voiceMenuOpen && (
                            <div className="voice-menu" role="listbox" aria-labelledby="speaker">
                              {speakers.map((item) => (
                                <button
                                  key={item.id}
                                  type="button"
                                  className={`voice-option ${speaker === item.id ? "is-selected" : ""}`}
                                  role="option"
                                  aria-selected={speaker === item.id}
                                  onClick={() => {
                                    setSpeaker(item.id);
                                    setLanguage(item.native_language || "Chinese");
                                    markAudioPreviewStale();
                                    setVoiceMenuOpen(false);
                                  }}
                                >
                                  <span className="voice-option-main">
                                    <span className="voice-title-row">
                                      <strong>{item.display_name || item.label}</strong>
                                      <span className="voice-inline-meta">
                                        推荐 {item.native_language_label}
                                      </span>
                                    </span>
                                    <span>{item.short_description || item.description}</span>
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="field">
                        <label className="field-label" htmlFor="tts-language">
                          语言
                        </label>
                        <div className="language-select" ref={languageSelectRef}>
                          <button
                            id="tts-language"
                            className="voice-select-trigger language-select-trigger"
                            type="button"
                            aria-haspopup="listbox"
                            aria-expanded={languageMenuOpen}
                            onClick={() => setLanguageMenuOpen((open) => !open)}
                          >
                            <span className="language-trigger-label">
                              {languages.find((item) => item.id === language)?.label || language}
                            </span>
                            <span className="voice-select-arrow" aria-hidden="true" />
                          </button>

                          {languageMenuOpen && (
                            <div className="voice-menu language-menu" role="listbox" aria-labelledby="tts-language">
                              {languages.map((item) => (
                                <button
                                  key={item.id}
                                  type="button"
                                  className={`voice-option language-option ${language === item.id ? "is-selected" : ""}`}
                                  role="option"
                                  aria-selected={language === item.id}
                                  onClick={() => {
                                    setLanguage(item.id);
                                    markAudioPreviewStale();
                                    setLanguageMenuOpen(false);
                                  }}
                                >
                                  <span className="language-option-main">
                                    <strong>{item.label}</strong>
                                    {selectedSpeaker?.native_language === item.id && (
                                      <span className="voice-inline-meta">音色推荐</span>
                                    )}
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    {selectedSpeaker && (
                      <div className="voice-summary">
                        <div className="voice-summary-main">
                          <strong>{selectedSpeaker.display_name}</strong>
                          <span>{selectedSpeaker.short_description || selectedSpeaker.description}</span>
                        </div>
                        <div className="voice-summary-tags">
                          <span>推荐 {selectedSpeaker.native_language_label}</span>
                          <span>{selectedSpeaker.supported_language_summary || "10 种语言"}</span>
                        </div>
                        <p>{selectedSpeaker.supported_language_labels || "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语"}</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="base-voice-panel">
                    <label className="field-label" htmlFor="voice-profile-select">
                      Base 音色档案
                    </label>
                    <div className="voice-select" ref={voiceProfileSelectRef}>
                      <button
                        id="voice-profile-select"
                        className="voice-select-trigger"
                        type="button"
                        aria-haspopup="listbox"
                        aria-expanded={voiceProfileMenuOpen}
                        disabled={voiceProfilesLoading}
                        onClick={() => setVoiceProfileMenuOpen((open) => !open)}
                      >
                        <span className="voice-trigger-main">
                          <span className="voice-title-row">
                            <strong>
                              {voiceProfilesLoading
                                ? "加载中..."
                                : selectedVoiceProfile?.name || "请选择一个预设音色"}
                            </strong>
                          </span>
                          <span>
                            {selectedVoiceProfile?.ref_text || "选择 Base 模型复用的本地音色档案"}
                          </span>
                        </span>
                        <span className="voice-select-arrow" aria-hidden="true" />
                      </button>

                      {voiceProfileMenuOpen && (
                        <div className="voice-menu" role="listbox" aria-labelledby="voice-profile-select">
                          {voiceProfiles.map((profile) => (
                              <button
                                key={profile.id}
                                type="button"
                                className={`voice-option ${voiceProfileId === profile.id ? "is-selected" : ""}`}
                                role="option"
                                aria-selected={voiceProfileId === profile.id}
                                onClick={() => {
                                  setVoiceProfileId(profile.id);
                                  markAudioPreviewStale();
                                  setVoiceProfileMenuOpen(false);
                                }}
                              >
                                <span className="voice-option-main">
                                  <span className="voice-title-row">
                                    <strong>{profile.name}</strong>
                                  </span>
                                  <span>{profile.ref_text || "已保存的 Base 音色档案"}</span>
                                </span>
                              </button>
                          ))}

                          <button
                            type="button"
                            className="voice-option voice-create-option"
                            role="option"
                            aria-selected={false}
                            onClick={() => {
                              setVoiceProfileMenuOpen(false);
                              openCreateVoiceProfileDialog();
                            }}
                          >
                            <span className="voice-option-main">
                              <span className="voice-title-row">
                                <strong>+ 新增音色</strong>
                              </span>
                              <span>上传参考音频并保存为新的本地档案</span>
                            </span>
                          </button>
                        </div>
                      )}
                    </div>

                    {selectedVoiceProfile && (
                      <div className="voice-summary voice-profile-preview">
                        <button
                          type="button"
                          className="icon-button voice-profile-edit-button"
                          aria-label={`编辑音色档案：${selectedVoiceProfile.name}`}
                          title="编辑音色档案"
                          onClick={() => openEditVoiceProfileDialog(selectedVoiceProfile)}
                        >
                          <Icon name="edit" size={16} />
                        </button>
                        <audio
                          className="audio-player"
                          src={resolveBackendAssetUrl(selectedVoiceProfile.audio_url, backendBaseUrl)}
                          controls
                        />
                      </div>
                    )}

                    {!voiceProfilesLoading && voiceProfiles.length === 0 && (
                      <div className="audio-empty">还没有预设音色，请在下拉菜单中新增一个。</div>
                    )}

                    {voiceProfileNotice && <div className="form-alert completed">{voiceProfileNotice}</div>}
                  </div>
                )}

                {voiceProfileDialogOpen && (
                  <div className="modal-backdrop" role="presentation">
                    <div className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="voice-profile-dialog-title">
                      <div className="modal-heading">
                        <div>
                          <span className="section-kicker">Base 音色</span>
                          <h3 id="voice-profile-dialog-title">
                            {isEditingVoiceProfile ? "编辑预设音色" : "新增预设音色"}
                          </h3>
                        </div>
                        <button
                          className="icon-button"
                          type="button"
                          aria-label="关闭音色档案弹窗"
                          onClick={closeVoiceProfileDialog}
                        >
                          <Icon name="x" size={17} />
                        </button>
                      </div>

                      <div className="modal-body">
                        <label className="field-label" htmlFor="voice-profile-name">
                          预设音色名称
                        </label>
                        <input
                          id="voice-profile-name"
                          className="control"
                          type="text"
                          placeholder="例如：中年中医"
                          value={voiceProfileName}
                          onChange={(event) => setVoiceProfileName(event.target.value)}
                        />

                        <label className="field-label" htmlFor="ref-audio">
                          {isEditingVoiceProfile ? "参考音频" : "参考音频 *"}
                        </label>
                        <label className={`upload-dropzone compact ${refAudioFile ? "is-filled" : ""}`}>
                          {refAudioFile ? (
                            <span className="upload-placeholder">
                              <Icon name="audio" size={22} />
                              <strong>{refAudioFile.name}</strong>
                              <small>{formatFileSize(refAudioFile.size)}</small>
                            </span>
                          ) : (
                            <span className="upload-placeholder">
                              <Icon name="upload" size={22} />
                              <strong>上传参考音频</strong>
                              <small>{isEditingVoiceProfile ? "不上传则保留当前参考音频" : "用于保存新的预设音色"}</small>
                            </span>
                          )}
                          <input
                            ref={refAudioInputRef}
                            id="ref-audio"
                            type="file"
                            accept="audio/*"
                            onChange={handleRefAudioChange}
                          />
                        </label>
                        {refAudioFile && (
                          <div className="file-row">
                            <span>{refAudioFile.name}</span>
                            <button type="button" className="text-button" onClick={removeRefAudio}>
                              移除
                            </button>
                          </div>
                        )}
                        {refAudioUrl && <audio className="audio-player" src={refAudioUrl} controls />}
                        {isEditingVoiceProfile && editingVoiceProfile && !refAudioFile && (
                          <audio
                            className="audio-player"
                            src={resolveBackendAssetUrl(editingVoiceProfile.audio_url, backendBaseUrl)}
                            controls
                          />
                        )}

                        <label className="field-label" htmlFor="ref-text">
                          参考文本 *
                        </label>
                        <textarea
                          id="ref-text"
                          className="control textarea"
                          rows={4}
                          placeholder="写下这段参考音频实际说的话"
                          value={refText}
                          onChange={(event) => setRefText(event.target.value)}
                        />

                        {voiceProfileError && <div className="form-alert failed">{voiceProfileError}</div>}
                        {deleteConfirmOpen && (
                          <div
                            className="delete-confirm-panel"
                            role="alertdialog"
                            aria-labelledby="voice-profile-delete-title"
                          >
                            <strong id="voice-profile-delete-title">确认删除这个音色档案？</strong>
                            <span>删除后会移除参考音频和档案记录，不能恢复。</span>
                            <div className="delete-confirm-actions">
                              <button
                                type="button"
                                className="secondary-action"
                                disabled={deletingVoiceProfile}
                                onClick={() => setDeleteConfirmOpen(false)}
                              >
                                取消
                              </button>
                              <button
                                type="button"
                                className="danger-action"
                                disabled={deletingVoiceProfile}
                                onClick={handleDeleteVoiceProfile}
                              >
                                <Icon name={deletingVoiceProfile ? "loading" : "trash"} size={16} />
                                {deletingVoiceProfile ? "正在删除" : "确认删除"}
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
                            disabled={savingVoiceProfile || deletingVoiceProfile}
                            onClick={() => setDeleteConfirmOpen(true)}
                          >
                            <Icon name="trash" size={16} />
                            删除
                          </button>
                        )}
                        <button
                          className="secondary-action"
                          type="button"
                          onClick={closeVoiceProfileDialog}
                        >
                          取消
                        </button>
                        <button
                          className="primary-action"
                          type="button"
                          disabled={!canSaveVoiceProfile}
                          onClick={handleSaveVoiceProfile}
                        >
                          <Icon name={savingVoiceProfile ? "loading" : "save"} size={16} />
                          {savingVoiceProfile ? "正在保存" : isEditingVoiceProfile ? "保存修改" : "保存音色"}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {ttsMode === "customvoice" && (
                  <div className="field">
                    <label className="field-label" htmlFor="voice-instruct">
                      语气指令
                    </label>
                    <input
                      id="voice-instruct"
                      className="control"
                      type="text"
                      placeholder="例如：语速稍快，语气自信"
                      value={instruct}
                      onChange={(event) => {
                        setInstruct(event.target.value);
                        markAudioPreviewStale();
                      }}
                    />
                  </div>
                )}
              </>
            ) : (
              <div className="workflow-note">
                直接上传音频时，不需要配置 TTS 音色。
              </div>
            )}
          </div>

          <div className="workflow-card audio-workflow">
            <div className="control-section-heading">
              <span>04</span>
              <strong>生成与试听</strong>
            </div>

            {mode === "text" ? (
              <>
                <button
                  className="secondary-action"
                  type="button"
                  disabled={!canPreviewAudio}
                  onClick={handlePreviewAudio}
                >
                  <Icon name={previewing ? "loading" : "play"} size={16} />
                  {previewing ? "正在生成试听音频" : "生成试听音频"}
                </button>

                <div className="audio-preview-block">
                  <div>
                    <span className="section-kicker with-icon">
                      <Icon name="mic" size={13} />
                      试听
                    </span>
                    <h3>确认口播语音</h3>
                    <p>确认效果后，再与人物图一起提交给 RunningHub。</p>
                  </div>
                  {audioPreview?.audio_url ? (
                    <>
                      <div className="speech-rate-panel">
                        <div className="speed-control">
                          <div className="speed-control-heading">
                            <label className="field-label" htmlFor="speech-rate">
                              调整语速
                            </label>
                            <strong>{speechRate.toFixed(1)}x</strong>
                          </div>
                          <input
                            id="speech-rate"
                            className="speed-slider"
                            type="range"
                            min={SPEECH_RATE_OPTIONS[0]}
                            max={SPEECH_RATE_OPTIONS[SPEECH_RATE_OPTIONS.length - 1]}
                            step="0.1"
                            value={speechRate}
                            onInput={handleSpeechRateChange}
                            onChange={handleSpeechRateChange}
                          />
                        </div>
                        <button
                          className="secondary-action"
                          type="button"
                          disabled={applyingSpeechRate || Math.abs(speechRate - previewSpeechRate) < 0.001}
                          onClick={handleApplySpeechRate}
                        >
                          <Icon name={applyingSpeechRate ? "loading" : "sliders"} size={16} />
                          {applyingSpeechRate ? "正在应用语速" : "应用语速"}
                        </button>
                      </div>
                      <div className={`audio-compare-grid ${hasRatePreview ? "has-variant" : ""}`}>
                        <div className="audio-preview-item">
                          <span>原始语音</span>
                          <audio
                            className="audio-player"
                            src={originalPreviewUrl}
                            controls
                            preload="metadata"
                            onError={() => handleAudioPreviewLoadError(originalPreviewUrl)}
                          />
                          <a className="audio-source-link" href={originalPreviewUrl} target="_blank" rel="noreferrer">
                            打开音频文件
                          </a>
                        </div>
                        {hasRatePreview && (
                          <div className="audio-preview-item is-selected">
                            <span>当前语速 {previewSpeechRate.toFixed(1)}x</span>
                            <audio
                              className="audio-player"
                              src={ratePreviewUrl}
                              controls
                              preload="metadata"
                              onError={() => handleAudioPreviewLoadError(ratePreviewUrl)}
                            />
                            <a className="audio-source-link" href={ratePreviewUrl} target="_blank" rel="noreferrer">
                              打开音频文件
                            </a>
                          </div>
                        )}
                      </div>
                      {audioPreviewError && <div className="form-alert failed">{audioPreviewError}</div>}
                      {audioPreviewStale && (
                        <div className="form-alert failed">
                          参数已变更，这段试听仅供参考。请重新生成试听后再生成视频。
                        </div>
                      )}
                    </>
                  ) : audioPreviewError ? (
                    <div className="form-alert failed">{audioPreviewError}</div>
                  ) : (
                    <div className="audio-empty">还没有可试听的音频</div>
                  )}
                </div>
              </>
            ) : (
              <div className="field">
                <label className="field-label" htmlFor="audio-file">
                  音频文件 *
                </label>
                <label className={`upload-dropzone compact ${audioFile ? "is-filled" : ""}`}>
                  {audioFile ? (
                    <span className="upload-placeholder">
                      <Icon name="audio" size={22} />
                      <strong>{audioFile.name}</strong>
                      <small>{formatFileSize(audioFile.size)}</small>
                    </span>
                  ) : (
                    <span className="upload-placeholder">
                      <Icon name="upload" size={22} />
                      <strong>选择音频</strong>
                      <small>MP3、WAV 或其他常见格式</small>
                    </span>
                  )}
                  <input
                    ref={audioInputRef}
                    id="audio-file"
                    type="file"
                    accept="audio/*"
                    onChange={handleAudioChange}
                  />
                </label>
                {audioFile && (
                  <>
                    <div className="file-row">
                      <span>{audioFile.name}</span>
                      <button type="button" className="text-button" onClick={removeAudio}>
                        移除
                      </button>
                    </div>
                    <audio className="audio-player" src={audioLocalUrl} controls />
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="workspace-panel output-panel" aria-labelledby="output-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">输出</span>
            <h2 id="output-title">生成数字人视频</h2>
          </div>
          <span className={`status-pill ${videoPanelStatus}`}>
            <Icon
              name={
                videoPanelStatus === "failed"
                  ? "alert"
                  : videoPanelStatus === "completed" || videoPanelStatus === "submitted"
                    ? "check"
                    : ["running", "pending"].includes(videoPanelStatus)
                      ? "loading"
                      : "gauge"
              }
              size={14}
            />
            {VIDEO_STEP_LABELS[videoPanelStatus]}
          </span>
        </div>

        <div className="video-workflow">
          <div className="video-status-card">
            <span className="section-kicker with-icon">
              <Icon name="cloud" size={13} />
              Video
            </span>
            <h3>提交生成任务</h3>
            <p>{videoPanelMessage}</p>

            <button
              className="primary-action"
              type="button"
              disabled={!canGenerateVideo}
              onClick={handleGenerateVideo}
            >
              <Icon name={generating ? "loading" : "wand"} size={16} />
              {taskStatus === "submitted" ? "任务已提交" : generating ? "正在生成视频" : "生成数字人视频"}
            </button>

            {(taskStatus === "running" || taskStatus === "pending") && (
              <div className="progress-area" aria-label="生成进度">
                <div className="progress-meta">
                  <span>{detailMessage}</span>
                  <strong>{progress}%</strong>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}
          </div>

          <div className={`result-surface ${videoUrl ? "has-video" : ""}`}>
            {taskStatus === "submitted" ? (
              <div className="submitted-state">
                <div className="state-orb submitted" aria-hidden="true">
                  <Icon name="check" size={28} />
                </div>
                <h3>RunningHub 任务已提交</h3>
                <p>{videoPanelMessage}</p>
                {runningHubResult?.taskId && (
                  <div className="runninghub-task-id">
                    <span>任务 ID</span>
                    <strong>{runningHubResult.taskId}</strong>
                  </div>
                )}
                <div className="runninghub-link-row">
                  <a className="download-action" href={runningHubResult?.taskUrl || RUNNINGHUB_TASKS_URL} target="_blank" rel="noreferrer">
                    <Icon name="external" size={16} />
                    查看任务进度
                  </a>
                  <a className="secondary-link-action" href={runningHubResult?.worksUrl || RUNNINGHUB_WORKS_URL} target="_blank" rel="noreferrer">
                    <Icon name="external" size={16} />
                    查看我的作品
                  </a>
                </div>
              </div>
            ) : taskStatus === "completed" && videoUrl ? (
              <>
                <video className="result-video" src={resolveBackendAssetUrl(videoUrl, backendBaseUrl)} controls />
                <a className="download-action" href={resolveBackendAssetUrl(videoUrl, backendBaseUrl)} download>
                  <Icon name="download" size={16} />
                  下载视频
                </a>
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
                <p>{videoPanelMessage}</p>
              </div>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
