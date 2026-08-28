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
  const titleId = `${idPrefix}-bgm-title`;
  const selectId = `${idPrefix}-bgm-select`;
  const deleteTitleId = `${idPrefix}-bgm-delete-title`;

  const loadBgmTracks = useCallback(async ({ signal } = {}) => {
    setBgmLoading(true);
    try {
      const data = await apiJson(
        "/api/template-production/bgm",
        signal ? { signal } : undefined,
        backendBaseUrl
      );
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
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const data = await apiJson(
        "/api/template-production/bgm",
        { method: "POST", body: form },
        backendBaseUrl
      );
      const track = data.bgm_track;
      setBgmTracks((current) => [...current, track]);
      onSelectionChange(track.id);
      showSuccess(`已上传背景音乐“${track.name}”。`);
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      setUploadingBgm(false);
    }
  }, [backendBaseUrl, onSelectionChange, showSuccess]);

  const confirmBgmDelete = useCallback(async () => {
    if (!pendingBgmDelete) return;
    const trackId = pendingBgmDelete.id;
    setDeletingBgmId(trackId);
    try {
      await apiJson(
        `/api/template-production/bgm/${encodeURIComponent(trackId)}`,
        { method: "DELETE" },
        backendBaseUrl
      );
      setBgmTracks((current) => current.filter((track) => track.id !== trackId));
      if (selectedBgmId === trackId) onSelectionChange("");
      showSuccess("背景音乐已删除。");
      setPendingBgmDelete(null);
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      setDeletingBgmId(null);
    }
  }, [backendBaseUrl, onSelectionChange, pendingBgmDelete, selectedBgmId, showSuccess]);

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
          <Button
            type="button"
            variant="outlined"
            size="small"
            onClick={() => bgmFileInputRef.current?.click()}
            disabled={disabled || uploadingBgm}
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
              onSelectionChange(event.target.value);
            }}
            disabled={disabled || uploadingBgm || bgmLoading}
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
              disabled={disabled || uploadingBgm || deletingBgmId === selectedBgmTrack.id}
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
            disabled={deletingBgmId === pendingBgmDelete?.id}
            startIcon={<Icon name={deletingBgmId === pendingBgmDelete?.id ? "loading" : "trash"} size={15} />}
          >
            确认删除
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
