import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";
import { ProtectedMedia } from "./ProtectedAsset";
import { apiFetch, useBackendBaseUrl } from "../lib/backend";

function formatFileSize(size) {
  const value = Number(size) || 0;
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDuration(seconds) {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(value / 60);
  return `${minutes}:${String(value % 60).padStart(2, "0")}`;
}

async function responseError(response, fallback) {
  const data = await response.json().catch(() => ({}));
  return data.detail || data.message || fallback || `HTTP ${response.status}`;
}

export default function BgmManager({
  currentUserId,
  selectedBgmId,
  onSelectionChange,
  disabled = false,
  idPrefix = "shared",
}) {
  const backendBaseUrl = useBackendBaseUrl();
  const [bgmTracks, setBgmTracks] = useState([]);
  const [bgmLoading, setBgmLoading] = useState(true);
  const [bgmError, setBgmError] = useState("");
  const [bgmNotice, setBgmNotice] = useState("");
  const [uploadingBgm, setUploadingBgm] = useState(false);
  const [deletingBgmId, setDeletingBgmId] = useState(null);
  const [pendingBgmDelete, setPendingBgmDelete] = useState(null);
  const bgmFileInputRef = useRef(null);
  const titleId = `${idPrefix}-bgm-title`;
  const selectId = `${idPrefix}-bgm-select`;
  const deleteTitleId = `${idPrefix}-bgm-delete-title`;

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
      setBgmTracks(Array.isArray(data.bgm_tracks) ? data.bgm_tracks : []);
    } catch (error) {
      if (error?.name !== "AbortError") {
        setBgmError(error.message || "读取背景音乐列表失败");
      }
    } finally {
      if (!signal?.aborted) setBgmLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    loadBgmTracks({ signal: controller.signal });
    return () => controller.abort();
  }, [currentUserId, loadBgmTracks]);

  useEffect(() => {
    if (
      !bgmLoading
      && selectedBgmId
      && !bgmTracks.some((track) => track.id === selectedBgmId)
    ) {
      onSelectionChange("");
    }
  }, [bgmLoading, bgmTracks, onSelectionChange, selectedBgmId]);

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
      onSelectionChange(track.id);
      setBgmNotice(`已上传背景音乐“${track.name}”。`);
    } catch (error) {
      setBgmError(error.message || "上传背景音乐失败");
    } finally {
      setUploadingBgm(false);
    }
  }, [backendBaseUrl, onSelectionChange]);

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
      if (selectedBgmId === trackId) onSelectionChange("");
      setBgmNotice("背景音乐已删除。");
      setPendingBgmDelete(null);
    } catch (error) {
      setBgmError(error.message || "删除背景音乐失败");
    } finally {
      setDeletingBgmId(null);
    }
  }, [backendBaseUrl, onSelectionChange, pendingBgmDelete, selectedBgmId]);

  const selectedBgmTrack = useMemo(
    () => bgmTracks.find((track) => track.id === selectedBgmId) || null,
    [bgmTracks, selectedBgmId]
  );

  return (
    <>
      <section className="template-work-section" aria-labelledby={titleId}>
        <div className="template-section-heading with-actions">
          <span><Icon name="music" size={17} /></span>
          <div><strong id={titleId}>背景音乐</strong><small>可选；与模板量产共享曲库，上传后可反复使用</small></div>
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
            disabled={disabled || uploadingBgm}
            title="上传背景音乐"
          >
            <Icon name={uploadingBgm ? "loading" : "upload"} size={15} />
            {uploadingBgm ? "上传中" : "上传"}
          </button>
        </div>
        <div className="bgm-control-row">
          <label className="field bgm-select-field" htmlFor={selectId}>
            <span className="field-label">选择背景音乐</span>
            <select
              id={selectId}
              className="control"
              value={selectedBgmId}
              onChange={(event) => {
                onSelectionChange(event.target.value);
                setBgmNotice("");
                setBgmError("");
              }}
              disabled={disabled || uploadingBgm || bgmLoading}
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
              onClick={() => setPendingBgmDelete(selectedBgmTrack)}
              disabled={disabled || uploadingBgm || deletingBgmId === selectedBgmTrack.id}
            >
              <Icon name={deletingBgmId === selectedBgmTrack.id ? "loading" : "trash"} size={15} />
            </button>
          ) : null}
        </div>
        {selectedBgmTrack ? (
          <div className="bgm-preview">
            <ProtectedMedia
              path={selectedBgmTrack.preview_url}
              kind="audio"
              backendBaseUrl={backendBaseUrl}
              preload="metadata"
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

      {pendingBgmDelete ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal-panel"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={deleteTitleId}
          >
            <div className="modal-heading">
              <div>
                <span className="section-kicker">BGM</span>
                <h3 id={deleteTitleId}>确认删除背景音乐？</h3>
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
                disabled={deletingBgmId === pendingBgmDelete.id}
              >
                <Icon name={deletingBgmId === pendingBgmDelete.id ? "loading" : "trash"} size={15} />
                确认删除
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
