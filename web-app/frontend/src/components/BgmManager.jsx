import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Box from "@mui/material/Box";
import Icon from "./Icon";
import { useGlobalMessage } from "./GlobalMessageProvider";
import { ProtectedMedia } from "./ProtectedAsset";
import { apiJson, useBackendBaseUrl } from "../lib/backend";

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

export default function BgmManager({
  currentUserId,
  selectedBgmId,
  onSelectionChange,
  onSelectedTrackChange,
  onBusyChange,
  disabled = false,
  idPrefix = "shared",
}) {
  const backendBaseUrl = useBackendBaseUrl();
  const { showSuccess } = useGlobalMessage();
  const [bgmTracks, setBgmTracks] = useState([]);
  const [bgmLoading, setBgmLoading] = useState(true);
  const [uploadingBgm, setUploadingBgm] = useState(false);
  const [deletingBgmId, setDeletingBgmId] = useState(null);
  const [pendingBgmDelete, setPendingBgmDelete] = useState(null);
  const bgmFileInputRef = useRef(null);
  const lifecycleRef = useRef(null);
  const mutationRef = useRef(false);
  const busyCallbackRef = useRef(onBusyChange);
  const busy = bgmLoading || uploadingBgm || Boolean(deletingBgmId);
  const titleId = `${idPrefix}-bgm-title`;
  const selectId = `${idPrefix}-bgm-select`;
  const deleteTitleId = `${idPrefix}-bgm-delete-title`;

  useEffect(() => {
    busyCallbackRef.current = onBusyChange;
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  const loadBgmTracks = useCallback(async ({ signal } = {}) => {
    setBgmLoading(true);
    try {
      const data = await apiJson(
        "/api/template-production/bgm",
        signal ? { signal } : undefined,
        backendBaseUrl
      );
      if (signal?.aborted) return;
      setBgmTracks(Array.isArray(data.bgm_tracks) ? data.bgm_tracks : []);
    } catch (error) {
      if (error?.name === "AbortError") return;
      // 错误已由 apiJson 弹出全局提示
    } finally {
      if (!signal?.aborted) setBgmLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    lifecycleRef.current = controller;
    mutationRef.current = false;
    setBgmTracks([]);
    setUploadingBgm(false);
    setDeletingBgmId(null);
    setPendingBgmDelete(null);
    busyCallbackRef.current?.(true);
    loadBgmTracks({ signal: controller.signal });
    return () => {
      controller.abort();
      if (lifecycleRef.current === controller) lifecycleRef.current = null;
      mutationRef.current = false;
      busyCallbackRef.current?.(false);
    };
  }, [currentUserId, loadBgmTracks]);

  useEffect(() => {
    if (
      !disabled
      && !busy
      && selectedBgmId
      && !bgmTracks.some((track) => track.id === selectedBgmId)
    ) {
      onSelectionChange("");
    }
  }, [bgmTracks, busy, disabled, onSelectionChange, selectedBgmId]);

  const uploadBgm = useCallback(async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    const controller = lifecycleRef.current;
    if (!file || disabled || busy || mutationRef.current || !controller || controller.signal.aborted) return;
    const isCurrent = () => lifecycleRef.current === controller && !controller.signal.aborted;

    mutationRef.current = true;
    busyCallbackRef.current?.(true);
    setUploadingBgm(true);
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const data = await apiJson(
        "/api/template-production/bgm",
        { method: "POST", body: form, signal: controller.signal },
        backendBaseUrl
      );
      if (!isCurrent()) return;
      const track = data.bgm_track;
      setBgmTracks((current) => [...current, track]);
      onSelectionChange(track.id);
      showSuccess(`已上传背景音乐“${track.name}”。`);
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      if (isCurrent()) {
        mutationRef.current = false;
        setUploadingBgm(false);
      }
    }
  }, [backendBaseUrl, busy, disabled, onSelectionChange, showSuccess]);

  const confirmBgmDelete = useCallback(async () => {
    const controller = lifecycleRef.current;
    if (!pendingBgmDelete || disabled || busy || mutationRef.current || !controller || controller.signal.aborted) return;
    const isCurrent = () => lifecycleRef.current === controller && !controller.signal.aborted;
    const trackId = pendingBgmDelete.id;
    mutationRef.current = true;
    busyCallbackRef.current?.(true);
    setDeletingBgmId(trackId);
    try {
      await apiJson(
        `/api/template-production/bgm/${encodeURIComponent(trackId)}`,
        { method: "DELETE", signal: controller.signal },
        backendBaseUrl
      );
      if (!isCurrent()) return;
      setBgmTracks((current) => current.filter((track) => track.id !== trackId));
      if (selectedBgmId === trackId) onSelectionChange("");
      showSuccess("背景音乐已删除。");
      setPendingBgmDelete(null);
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      if (isCurrent()) {
        mutationRef.current = false;
        setDeletingBgmId(null);
      }
    }
  }, [backendBaseUrl, busy, disabled, onSelectionChange, pendingBgmDelete, selectedBgmId, showSuccess]);

  const selectedBgmTrack = useMemo(
    () => bgmTracks.find((track) => track.id === selectedBgmId) || null,
    [bgmTracks, selectedBgmId]
  );

  useEffect(() => {
    onSelectedTrackChange?.(selectedBgmTrack);
  }, [onSelectedTrackChange, selectedBgmTrack]);

  return (
    <>
      <section className="template-work-section" aria-labelledby={titleId}>
        <div className="template-section-heading with-actions">
          <span><Icon name="music" size={17} /></span>
          <div><strong id={titleId}>背景音乐</strong><small>可选；与模板量产共享曲库，上传后可反复使用</small></div>
          <Box
            component="input"
            ref={bgmFileInputRef}
            hidden
            type="file"
            accept="audio/*,.mp3,.wav,.aac,.m4a,.ogg,.flac"
            onChange={uploadBgm}
            disabled={disabled || busy}
          />
          <Button
            type="button"
            variant="outlined"
            size="small"
            onClick={() => bgmFileInputRef.current?.click()}
            disabled={disabled || busy}
            title="上传背景音乐"
            startIcon={<Icon name={uploadingBgm ? "loading" : "upload"} size={15} />}
          >
            {uploadingBgm ? "上传中" : "上传"}
          </Button>
        </div>
        <div className="bgm-control-row">
          <TextField
            id={selectId}
            className="bgm-select-field"
            label="选择背景音乐"
            fullWidth
            size="small"
            select
            value={selectedBgmId}
            onChange={(event) => {
              if (disabled || busy || mutationRef.current) return;
              onSelectionChange(event.target.value);
            }}
            disabled={disabled || busy}
          >
            <MenuItem value="">不使用背景音乐</MenuItem>
            {bgmTracks.map((track) => (
              <MenuItem key={track.id} value={track.id}>
                {track.name}（{formatDuration(track.duration)}）
              </MenuItem>
            ))}
          </TextField>
          {selectedBgmTrack ? (
            <IconButton
              type="button"
              title={`删除背景音乐“${selectedBgmTrack.name}”`}
              aria-label={`删除背景音乐“${selectedBgmTrack.name}”`}
              onClick={() => setPendingBgmDelete(selectedBgmTrack)}
              disabled={disabled || busy}
              size="small"
            >
              <Icon name={deletingBgmId === selectedBgmTrack.id ? "loading" : "trash"} size={15} />
            </IconButton>
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
      </section>

      <Dialog
        open={Boolean(pendingBgmDelete)}
        onClose={() => setPendingBgmDelete(null)}
        aria-labelledby={deleteTitleId}
      >
        <DialogTitle>
          <Typography variant="kicker" component="span" className="section-kicker">BGM</Typography>
          <h3 id={deleteTitleId}>确认删除背景音乐？</h3>
        </DialogTitle>
        <DialogContent>
          <p>“{pendingBgmDelete?.name}”将被永久删除，无法恢复。</p>
        </DialogContent>
        <DialogActions>
          <Button type="button" onClick={() => setPendingBgmDelete(null)}>取消</Button>
          <Button
            type="button"
            color="error"
            variant="contained"
            onClick={confirmBgmDelete}
            disabled={disabled || busy}
            startIcon={<Icon name={deletingBgmId === pendingBgmDelete?.id ? "loading" : "trash"} size={15} />}
          >
            确认删除
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
