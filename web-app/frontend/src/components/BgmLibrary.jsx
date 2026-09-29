import { useCallback, useEffect, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
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
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

export default function BgmLibrary({ currentUserId }) {
  const backendBaseUrl = useBackendBaseUrl();
  const { showSuccess } = useGlobalMessage();
  const fileInputRef = useRef(null);
  const lifecycleRef = useRef(null);
  const mutationRef = useRef(false);
  const [tracks, setTracks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);

  const refresh = useCallback(async ({ signal } = {}) => {
    setLoading(true);
    try {
      const data = await apiJson(
        "/api/template-production/bgm",
        signal ? { signal } : undefined,
        backendBaseUrl
      );
      if (!signal?.aborted) setTracks(Array.isArray(data.bgm_tracks) ? data.bgm_tracks : []);
    } catch (error) {
      if (error?.name !== "AbortError") setTracks([]);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    lifecycleRef.current = controller;
    mutationRef.current = false;
    setTracks([]);
    setUploading(false);
    setDeletingId(null);
    setPendingDelete(null);
    refresh({ signal: controller.signal });
    return () => {
      controller.abort();
      if (lifecycleRef.current === controller) lifecycleRef.current = null;
      mutationRef.current = false;
    };
  }, [currentUserId, refresh]);

  const upload = useCallback(async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    const controller = lifecycleRef.current;
    if (!file || !controller || controller.signal.aborted || mutationRef.current) return;
    const isCurrent = () => lifecycleRef.current === controller && !controller.signal.aborted;

    mutationRef.current = true;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file, file.name);
      const data = await apiJson(
        "/api/template-production/bgm",
        { method: "POST", body: form, signal: controller.signal },
        backendBaseUrl
      );
      if (!isCurrent()) return;
      setTracks((current) => [...current, data.bgm_track]);
      showSuccess(`已上传背景音乐“${data.bgm_track.name}”。`);
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      if (isCurrent()) {
        mutationRef.current = false;
        setUploading(false);
      }
    }
  }, [backendBaseUrl, showSuccess]);

  const confirmDelete = useCallback(async () => {
    const controller = lifecycleRef.current;
    if (!pendingDelete || !controller || controller.signal.aborted || mutationRef.current) return;
    const isCurrent = () => lifecycleRef.current === controller && !controller.signal.aborted;

    mutationRef.current = true;
    setDeletingId(pendingDelete.id);
    try {
      await apiJson(
        `/api/template-production/bgm/${encodeURIComponent(pendingDelete.id)}`,
        { method: "DELETE", signal: controller.signal },
        backendBaseUrl
      );
      if (!isCurrent()) return;
      setTracks((current) => current.filter((track) => track.id !== pendingDelete.id));
      setPendingDelete(null);
      showSuccess("背景音乐已删除。");
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      if (isCurrent()) {
        mutationRef.current = false;
        setDeletingId(null);
      }
    }
  }, [backendBaseUrl, pendingDelete, showSuccess]);

  return (
    <>
      <section className="bgm-library-page" aria-label="个人背景音乐库">
        <div className="bgm-library-heading">
          <div>
            <p>上传后可在视频生成工作台中反复使用。</p>
          </div>
          <Box
            component="input"
            ref={fileInputRef}
            hidden
            type="file"
            accept="audio/*,.mp3,.wav,.aac,.m4a,.ogg,.flac"
            onChange={upload}
            disabled={loading || uploading || Boolean(deletingId)}
          />
          <Button
            type="button"
            variant="outlined"
            size="small"
            onClick={() => fileInputRef.current?.click()}
            disabled={loading || uploading || Boolean(deletingId)}
            startIcon={<Icon name={uploading ? "loading" : "upload"} size={15} />}
          >
            {uploading ? "上传中" : "上传背景音乐"}
          </Button>
        </div>

        <TableContainer className="bgm-library-table-wrap">
          <Table size="small" aria-label="个人背景音乐库">
            <TableHead>
              <TableRow>
                <TableCell>名称</TableCell>
                <TableCell>时长</TableCell>
                <TableCell>大小</TableCell>
                <TableCell>试听</TableCell>
                <TableCell align="right">操作</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <div className="bgm-library-state"><Icon name="loading" size={17} />正在加载背景音乐</div>
                  </TableCell>
                </TableRow>
              ) : tracks.length ? (
                tracks.map((track) => (
                  <TableRow key={track.id}>
                    <TableCell className="bgm-library-name">
                      <strong title={track.name}>{track.name}</strong>
                    </TableCell>
                    <TableCell className="bgm-library-meta">{formatDuration(track.duration)}</TableCell>
                    <TableCell className="bgm-library-meta">{formatFileSize(track.file_size)}</TableCell>
                    <TableCell>
                      <ProtectedMedia
                        className="bgm-library-audio"
                        path={track.preview_url}
                        kind="audio"
                        backendBaseUrl={backendBaseUrl}
                        preload="metadata"
                        aria-label={`试听${track.name}`}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <IconButton
                        type="button"
                        size="small"
                        title={`删除背景音乐“${track.name}”`}
                        aria-label={`删除背景音乐“${track.name}”`}
                        onClick={() => setPendingDelete(track)}
                        disabled={loading || uploading || Boolean(deletingId)}
                      >
                        <Icon name={deletingId === track.id ? "loading" : "trash"} size={16} />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={5}>
                    <div className="bgm-library-state"><Icon name="music" size={19} />还没有个人背景音乐，先上传一首吧。</div>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </section>

      <Dialog
        open={Boolean(pendingDelete)}
        onClose={() => !deletingId && setPendingDelete(null)}
        aria-labelledby="bgm-library-delete-title"
      >
        <DialogTitle>
          <h3 id="bgm-library-delete-title">确认删除背景音乐？</h3>
        </DialogTitle>
        <DialogContent>
          <p>“{pendingDelete?.name}”将被永久删除，无法恢复。</p>
        </DialogContent>
        <DialogActions>
          <Button type="button" onClick={() => setPendingDelete(null)} disabled={Boolean(deletingId)}>取消</Button>
          <Button
            type="button"
            color="error"
            variant="contained"
            onClick={confirmDelete}
            disabled={Boolean(deletingId)}
            startIcon={<Icon name={deletingId ? "loading" : "trash"} size={15} />}
          >
            {deletingId ? "删除中" : "确认删除"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
