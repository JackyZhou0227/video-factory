import { useState, useEffect, useRef, useCallback, useMemo } from "react";

const API = "/api";

const MODE_OPTIONS = [
  { value: "text", label: "本地模型生成语音" },
  { value: "audio", label: "直接上传音频" },
];

const TTS_MODE_OPTIONS = [
  { value: "customvoice", label: "CustomVoice" },
  { value: "base", label: "Base 语音克隆" },
];

const STEP_LABELS = {
  idle: "等待素材",
  previewing: "生成试听",
  ready: "语音已就绪",
  pending: "任务排队中",
  running: "正在生成视频",
  completed: "生成完成",
  failed: "生成失败",
};

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
    display_name: "薇薇安 Vivian",
    native_language: "Chinese",
    native_language_label: "中文",
    short_description: "明亮年轻女声，清晰有精神。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Serena",
    display_name: "赛琳娜 Serena",
    native_language: "Chinese",
    native_language_label: "中文",
    short_description: "温柔年轻女声，亲和舒缓。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Uncle_Fu",
    display_name: "傅叔 Uncle Fu",
    native_language: "Chinese",
    native_language_label: "中文",
    short_description: "低醇成熟男声，稳重可信。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Dylan",
    display_name: "迪伦 Dylan",
    native_language: "Chinese",
    native_language_label: "中文（北京口音）",
    short_description: "清朗北京男声，自然生活感。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Eric",
    display_name: "艾瑞克 Eric",
    native_language: "Chinese",
    native_language_label: "中文（四川口音）",
    short_description: "活泼成都男声，明亮略带方言感。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Ryan",
    display_name: "瑞安 Ryan",
    native_language: "English",
    native_language_label: "英语",
    short_description: "动感英文男声，节奏感强。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Aiden",
    display_name: "艾登 Aiden",
    native_language: "English",
    native_language_label: "英语（美式）",
    short_description: "阳光美式男声，清晰自然。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Ono_Anna",
    display_name: "小野安娜 Ono Anna",
    native_language: "Japanese",
    native_language_label: "日语",
    short_description: "轻盈日文女声，俏皮灵动。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
  {
    id: "Sohee",
    display_name: "昭熙 Sohee",
    native_language: "Korean",
    native_language_label: "韩语",
    short_description: "温暖韩文女声，情绪丰富。",
    supported_language_summary: "10 种语言",
    supported_language_labels: "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语",
  },
];

function pollTask(taskId, signal) {
  return fetch(`${API}/task/${taskId}`, { signal }).then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  });
}

function isReadableMessage(message) {
  return typeof message === "string" && message.trim() && !/[�]/.test(message);
}

function formatFileSize(size) {
  if (!size) return "";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function DigitalHuman() {
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
  const [ttsMode, setTtsMode] = useState("customvoice");
  const [instruct, setInstruct] = useState("");
  const [refAudioFile, setRefAudioFile] = useState(null);
  const [refAudioUrl, setRefAudioUrl] = useState(null);
  const [refText, setRefText] = useState("");
  const [voiceMenuOpen, setVoiceMenuOpen] = useState(false);
  const [languageMenuOpen, setLanguageMenuOpen] = useState(false);

  const [audioPreview, setAudioPreview] = useState(null);
  const [taskStatus, setTaskStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [statusMsg, setStatusMsg] = useState("");
  const [videoUrl, setVideoUrl] = useState(null);
  const [error, setError] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [generating, setGenerating] = useState(false);

  const pollRef = useRef(null);
  const imageInputRef = useRef(null);
  const audioInputRef = useRef(null);
  const refAudioInputRef = useRef(null);
  const voiceSelectRef = useRef(null);
  const languageSelectRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    fetch(`${API}/speakers`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((list) => {
        if (cancelled) return;
        const nextSpeakers = Array.isArray(list) && list.length > 0 ? list : DEFAULT_SPEAKERS;
        setSpeakers(nextSpeakers);
        setSpeaker((currentSpeaker) =>
          nextSpeakers.length > 0 && !nextSpeakers.find((item) => item.id === currentSpeaker)
            ? nextSpeakers[0].id
            : currentSpeaker
        );
      })
      .catch(() => {
        if (cancelled) return;
        setSpeakers(DEFAULT_SPEAKERS);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetch(`${API}/tts/languages`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((list) => {
        if (cancelled) return;
        const nextLanguages = Array.isArray(list) && list.length > 0 ? list : DEFAULT_LANGUAGES;
        setLanguages(nextLanguages);
        setLanguage((currentLanguage) =>
          nextLanguages.length > 0 && !nextLanguages.find((item) => item.id === currentLanguage)
            ? nextLanguages[0].id
            : currentLanguage
        );
      })
      .catch(() => {
        if (cancelled) return;
        setLanguages(DEFAULT_LANGUAGES);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
      if (imagePreview) URL.revokeObjectURL(imagePreview);
      if (audioLocalUrl) URL.revokeObjectURL(audioLocalUrl);
      if (refAudioUrl) URL.revokeObjectURL(refAudioUrl);
    };
  }, [audioLocalUrl, imagePreview, refAudioUrl]);

  useEffect(() => {
    if (!voiceMenuOpen && !languageMenuOpen) return;

    const handlePointerDown = (event) => {
      if (!voiceSelectRef.current?.contains(event.target)) {
        setVoiceMenuOpen(false);
      }
      if (!languageSelectRef.current?.contains(event.target)) {
        setLanguageMenuOpen(false);
      }
    };

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setVoiceMenuOpen(false);
        setLanguageMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [languageMenuOpen, voiceMenuOpen]);

  const resetVideoState = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    setTaskStatus("idle");
    setProgress(0);
    setStatusMsg("");
    setVideoUrl(null);
    setError(null);
    setGenerating(false);
  }, []);

  const resetAudioPreview = useCallback(() => {
    setAudioPreview(null);
    setVideoUrl(null);
    setProgress(0);
    setError(null);
    setStatusMsg("");
    setTaskStatus("idle");
  }, []);

  const handleRefAudioChange = useCallback((event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setRefAudioFile(file);
    setRefAudioUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return URL.createObjectURL(file);
    });
    setAudioPreview(null);
    resetVideoState();
  }, [resetVideoState]);

  const removeRefAudio = useCallback(() => {
    setRefAudioFile(null);
    setRefAudioUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (refAudioInputRef.current) refAudioInputRef.current.value = "";
    resetVideoState();
  }, [resetVideoState]);

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

  const handleAudioChange = useCallback(
    (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      setAudioFile(file);
      setAudioLocalUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return URL.createObjectURL(file);
      });
      setAudioPreview(null);
      setTaskStatus("ready");
      setVideoUrl(null);
      setError(null);
      setStatusMsg("上传音频已就绪，可以直接生成视频。");
    },
    []
  );

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
    setAudioLocalUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    if (audioInputRef.current) audioInputRef.current.value = "";
    resetVideoState();
  }, [resetVideoState]);

  const selectedSpeaker = useMemo(
    () => speakers.find((item) => item.id === speaker) ?? null,
    [speaker, speakers]
  );

  useEffect(() => {
    if (!selectedSpeaker) return;
    setLanguage(selectedSpeaker.native_language || "Chinese");
  }, [selectedSpeaker]);

  const canPreviewAudio = Boolean(
    mode === "text" && !previewing && text.trim() && language && (ttsMode === "customvoice" ? speaker : refAudioFile && refText.trim())
  );
  const hasConfirmedAudio = Boolean(
    mode === "text" ? audioPreview?.audio_url : audioFile
  );
  const canGenerateVideo = Boolean(!generating && imageFile && hasConfirmedAudio);

  const detailMessage = useMemo(() => {
    if (taskStatus === "failed") return error || "任务执行失败，请检查输入后重试。";
    if (taskStatus === "completed") return "视频已生成，可预览或下载。";
    if (isReadableMessage(statusMsg)) return statusMsg;
    if (taskStatus === "previewing") return "正在调用本地 Qwen3-TTS 生成试听音频。";
    if (taskStatus === "ready") return "试听音频已生成，确认无误后即可提交视频生成。";
    if (taskStatus === "running") return "正在把人物图和确认后的音频提交给 RunningHub。";
    return "先生成并试听语音，再确认生成数字人口播视频。";
  }, [error, statusMsg, taskStatus]);

  const handlePreviewAudio = useCallback(async () => {
    if (!canPreviewAudio) return;

    setPreviewing(true);
    setAudioPreview(null);
    setVideoUrl(null);
    setError(null);
    setTaskStatus("previewing");
    setStatusMsg("正在生成试听音频…");

    try {
      const formData = new FormData();
      formData.append("text", text.trim());
      formData.append("tts_mode", ttsMode);
      formData.append("speaker", speaker);
      formData.append("language", language);
      if (ttsMode === "customvoice" && instruct.trim()) formData.append("instruct", instruct.trim());
      if (ttsMode === "base") {
        formData.append("ref_audio", refAudioFile);
        formData.append("ref_text", refText.trim());
      }

      const response = await fetch(`${API}/tts/preview`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setAudioPreview(data);
      setTaskStatus("ready");
      setStatusMsg("试听音频已生成，请先播放确认。");
    } catch (err) {
      setTaskStatus("failed");
      setError(err.message);
    } finally {
      setPreviewing(false);
    }
  }, [canPreviewAudio, instruct, language, refAudioFile, refText, speaker, text, ttsMode]);

  const handleGenerateVideo = useCallback(async () => {
    if (!canGenerateVideo) return;

    setGenerating(true);
    setError(null);
    setVideoUrl(null);
    setProgress(0);
    setTaskStatus("pending");
    setStatusMsg("正在提交视频生成任务…");

    try {
      const formData = new FormData();
      formData.append("image", imageFile);

      if (mode === "text") {
        formData.append("mode", "preview");
        formData.append("audio_url", audioPreview.audio_url);
        formData.append("tts_mode", ttsMode);
        if (ttsMode === "base") {
          formData.append("ref_audio", refAudioFile);
          formData.append("ref_text", refText.trim());
        }
      } else {
        formData.append("mode", "audio");
        formData.append("audio", audioFile);
      }

      const response = await fetch(`${API}/generate-video`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const { task_id: taskId } = await response.json();
      setTaskStatus("running");
      setStatusMsg("任务已提交，等待 RunningHub 处理。");

      const controller = new AbortController();
      const poll = async () => {
        try {
          const data = await pollTask(taskId, controller.signal);
          setProgress(data.progress ?? 0);
          setStatusMsg(data.message ?? "");

          if (data.status === "completed") {
            setTaskStatus("completed");
            setVideoUrl(data.video_url ?? null);
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
  }, [audioFile, audioPreview, canGenerateVideo, imageFile, mode, refAudioFile, refText, ttsMode]);

  return (
    <>
      <section className="workspace-panel input-panel" aria-labelledby="input-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">输入</span>
            <h2 id="input-title">素材与语音</h2>
          </div>
          <span className="required-note">先试听，再生成视频</span>
        </div>

        <div className="form-stack">
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
                <span className="field-label">TTS 模式</span>
                <div className="segmented-control" role="tablist" aria-label="TTS 模式">
                  {TTS_MODE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`segment ${ttsMode === option.value ? "is-active" : ""}`}
                      onClick={() => {
                        setTtsMode(option.value);
                        setAudioPreview(null);
                        if (taskStatus === "ready") setTaskStatus("idle");
                      }}
                      role="tab"
                      aria-selected={ttsMode === option.value}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="field">
                <label className="field-label" htmlFor="script-text">
                  口播文案 *
                </label>
                <textarea
                  id="script-text"
                  className="control textarea"
                  rows={6}
                  placeholder="请输入口播文案内容"
                  value={text}
                  onChange={(event) => {
                    setText(event.target.value);
                    setAudioPreview(null);
                    if (taskStatus === "ready") setTaskStatus("idle");
                  }}
                />
              </div>

              {ttsMode === "customvoice" ? (
                <div className="voice-config">
                  <div className="tts-model-note">
                    本地 TTS 服务由 Qwen3-TTS CustomVoice 提供
                  </div>
                  <div className="voice-controls-grid">
                    <div className="field">
                      <div className="voice-header">
                        <label className="field-label" htmlFor="speaker">
                          音色
                        </label>
                      </div>
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
                            <span>
                              {selectedSpeaker?.short_description || "选择本地模型音色"}
                            </span>
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
                                  setAudioPreview(null);
                                  setVoiceMenuOpen(false);
                                  if (taskStatus === "ready") setTaskStatus("idle");
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
                      <div className="voice-header">
                        <label className="field-label" htmlFor="tts-language">
                          语言
                        </label>
                      </div>
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
                            {selectedSpeaker?.native_language === language ? "（音色推荐）" : ""}
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
                                  setAudioPreview(null);
                                  setLanguageMenuOpen(false);
                                  if (taskStatus === "ready") setTaskStatus("idle");
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
                        <span>已选择：{selectedSpeaker.short_description || selectedSpeaker.description}</span>
                      </div>
                      <div className="voice-summary-tags">
                        <span>推荐：{selectedSpeaker.native_language_label}</span>
                        <span>
                          支持：{selectedSpeaker.supported_language_summary || "10 种语言"}
                        </span>
                      </div>
                      <p>
                        支持语言包括：{selectedSpeaker.supported_language_labels || "中文、英语、日语、韩语、德语、法语、俄语、葡萄牙语、西班牙语、意大利语"}。
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="field-grid">
                  <div className="field">
                    <label className="field-label" htmlFor="ref-audio">
                      参考音频 *
                    </label>
                    <label className={`upload-dropzone compact ${refAudioFile ? "is-filled" : ""}`}>
                      {refAudioFile ? (
                        <span className="upload-placeholder">
                          <strong>{refAudioFile.name}</strong>
                          <small>{formatFileSize(refAudioFile.size)}</small>
                        </span>
                      ) : (
                        <span className="upload-placeholder">
                          <strong>上传参考音频</strong>
                          <small>用于 Base 语音克隆</small>
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
                  </div>

                  <div className="field">
                    <label className="field-label" htmlFor="ref-text">
                      参考文本 *
                    </label>
                    <textarea
                      id="ref-text"
                      className="control textarea"
                      rows={6}
                      placeholder="参考音频里实际说的话"
                      value={refText}
                      onChange={(event) => {
                        setRefText(event.target.value);
                        setAudioPreview(null);
                      }}
                    />
                  </div>
                </div>
              )}

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
                    setAudioPreview(null);
                  }}
                  disabled={ttsMode === "base"}
                />
              </div>

              <button
                className="secondary-action"
                type="button"
                disabled={!canPreviewAudio}
                onClick={handlePreviewAudio}
              >
                {previewing ? "正在生成试听音频" : "生成试听音频"}
              </button>
            </>
          ) : (
            <div className="field">
              <label className="field-label" htmlFor="audio-file">
                音频文件 *
              </label>
              <label className={`upload-dropzone compact ${audioFile ? "is-filled" : ""}`}>
                {audioFile ? (
                  <span className="upload-placeholder">
                    <strong>{audioFile.name}</strong>
                    <small>{formatFileSize(audioFile.size)}</small>
                  </span>
                ) : (
                  <span className="upload-placeholder">
                    <strong>选择音频</strong>
                    <small>MP3、WAV 或其他常见音频格式</small>
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
      </section>

      <section className="workspace-panel output-panel" aria-labelledby="output-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">输出</span>
            <h2 id="output-title">试听与生成</h2>
          </div>
          <span className={`status-pill ${taskStatus}`}>{STEP_LABELS[taskStatus]}</span>
        </div>

        <div className="preview-card">
          <div>
            <span className="section-kicker">Step 1</span>
            <h3>确认口播语音</h3>
            <p>
              使用本地模型生成的语音会先保存在本机，确认效果后才会和人物图一起提交到 RunningHub。
            </p>
          </div>
          {mode === "text" && audioPreview?.audio_url ? (
            <audio className="audio-player" src={audioPreview.audio_url} controls />
          ) : mode === "audio" && audioLocalUrl ? (
            <audio className="audio-player" src={audioLocalUrl} controls />
          ) : (
            <div className="audio-empty">还没有可试听的音频</div>
          )}
        </div>

        <button
          className="primary-action"
          type="button"
          disabled={!canGenerateVideo}
          onClick={handleGenerateVideo}
        >
          {generating ? "正在生成视频" : "确认语音，生成视频"}
        </button>

        <div className={`result-surface ${videoUrl ? "has-video" : ""}`}>
          {taskStatus === "completed" && videoUrl ? (
            <>
              <video className="result-video" src={videoUrl} controls />
              <a className="download-action" href={videoUrl} download>
                下载视频
              </a>
            </>
          ) : (
            <div className="empty-state">
              <div className={`state-orb ${taskStatus}`} aria-hidden="true">
                {taskStatus === "failed" ? "!" : taskStatus === "running" ? `${progress}%` : "VF"}
              </div>
              <h3>{STEP_LABELS[taskStatus]}</h3>
              <p>{detailMessage}</p>
            </div>
          )}
        </div>

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
      </section>
    </>
  );
}
