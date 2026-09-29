import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import Icon from "./Icon";
import { ProtectedMedia } from "./ProtectedAsset";
import { apiJson, useBackendBaseUrl } from "../lib/backend";
import { DEFAULT_TTS_LANGUAGES } from "../lib/ttsLanguages";

function formatFileSize(size) {
  if (!size) return "";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function VoiceProfileLibrary({ languages = DEFAULT_TTS_LANGUAGES, onProfilesChange, unframed = false }) {
  const backendBaseUrl = useBackendBaseUrl();
  const refAudioInputRef = useRef(null);
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(null);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("Chinese");
  const [refText, setRefText] = useState("");
  const [refAudioFile, setRefAudioFile] = useState(null);
  const [refAudioUrl, setRefAudioUrl] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [previewProfile, setPreviewProfile] = useState(null);
  const editingProfile = useMemo(() => profiles.find((item) => item.id === dialog?.profileId) || null, [dialog, profiles]);
  const isEditing = dialog?.mode === "edit";

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await apiJson("/api/tts-studio/voice-profiles", { silentError: true }, backendBaseUrl);
      const next = Array.isArray(list) ? list : [];
      setProfiles(next);
      onProfilesChange?.(next);
    } catch {
      setProfiles([]);
      onProfilesChange?.([]);
    } finally {
      setLoading(false);
    }
  }, [backendBaseUrl, onProfilesChange]);

  useEffect(() => { refresh(); }, [refresh]);

  const clearAudio = useCallback(() => {
    setRefAudioFile(null);
    setRefAudioUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return "";
    });
    if (refAudioInputRef.current) refAudioInputRef.current.value = "";
  }, []);

  useEffect(() => () => { if (refAudioUrl) URL.revokeObjectURL(refAudioUrl); }, [refAudioUrl]);

  const closeDialog = useCallback(() => {
    clearAudio();
    setDialog(null);
    setError("");
    setConfirmDelete(false);
  }, [clearAudio]);

  const openCreate = useCallback(() => {
    clearAudio();
    setDialog({ mode: "create" });
    setName("");
    setLanguage(languages[0]?.id || "Chinese");
    setRefText("");
    setError("");
    setConfirmDelete(false);
  }, [clearAudio, languages]);

  const openEdit = useCallback((profile) => {
    clearAudio();
    setDialog({ mode: "edit", profileId: profile.id });
    setName(profile.name || "");
    setLanguage(profile.language || "Chinese");
    setRefText(profile.ref_text || "");
    setError("");
    setConfirmDelete(false);
  }, [clearAudio]);

  const onAudioChange = useCallback((event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setRefAudioFile(file);
    setRefAudioUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return URL.createObjectURL(file);
    });
  }, []);

  const save = useCallback(async () => {
    if (!name.trim() || !refText.trim() || (!isEditing && !refAudioFile)) return;
    setSaving(true);
    setError("");
    try {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("language", language);
      form.append("ref_text", refText.trim());
      if (refAudioFile) form.append("ref_audio", refAudioFile);
      const endpoint = isEditing ? `/api/tts-studio/voice-profiles/${editingProfile.id}` : "/api/tts-studio/voice-profiles";
      await apiJson(endpoint, { method: isEditing ? "PUT" : "POST", body: form, silentError: true }, backendBaseUrl);
      await refresh();
      closeDialog();
    } catch (err) {
      setError(err.message || "保存音色档案失败");
    } finally {
      setSaving(false);
    }
  }, [backendBaseUrl, closeDialog, editingProfile, isEditing, language, name, refAudioFile, refText, refresh]);

  const remove = useCallback(async () => {
    if (!editingProfile) return;
    setDeleting(true);
    try {
      await apiJson(`/api/tts-studio/voice-profiles/${editingProfile.id}`, { method: "DELETE", silentError: true }, backendBaseUrl);
      await refresh();
      closeDialog();
    } catch (err) {
      setError(err.message || "删除音色档案失败");
    } finally {
      setDeleting(false);
    }
  }, [backendBaseUrl, closeDialog, editingProfile, refresh]);

  return (
    <section className={unframed ? "profile-resource-component" : "workspace-panel profile-resource-panel"} aria-label="个人克隆音色库">
      <div className="panel-heading">
        <div>
          <p className="profile-resource-note">维护可在语音合成中反复使用的个人音色档案。</p>
          <p className="profile-resource-note profile-resource-helper">
            需要干净参考音频？{" "}
            <a href="https://www.qipaoyin.com/vocal-remover" target="_blank" rel="noreferrer">
              在线提取人声
            </a>
          </p>
        </div>
        <Button type="button" variant="outlined" size="small" onClick={openCreate} startIcon={<Icon name="plus" size={15} />}>新增音色</Button>
      </div>
      {loading ? <div className="profile-resource-empty"><Icon name="loading" size={18} />正在加载音色档案</div> : profiles.length ? (
        <div className="profile-voice-list">
          {profiles.map((profile) => (
            <article className="profile-voice-row" key={profile.id}>
              <div className="profile-voice-copy">
                <div className="profile-voice-title">
                  <strong>{profile.name}</strong>
                  <span>{languages.find((item) => item.id === profile.language)?.label || profile.language}</span>
                </div>
                <div className="profile-voice-reference">
                  <span>参考文本</span>
                  <p>{profile.ref_text}</p>
                </div>
              </div>
              <ProtectedMedia className="audio-player" path={profile.audio_url} kind="audio" backendBaseUrl={backendBaseUrl} aria-label={`${profile.name}参考音频`} />
              <div className="profile-voice-actions">
                <IconButton
                  type="button"
                  aria-label={`查看参考文本：${profile.name}`}
                  title="查看参考文本"
                  onClick={() => setPreviewProfile(profile)}
                  size="small"
                >
                  <Icon name="file" size={16} />
                </IconButton>
                <IconButton type="button" aria-label={`编辑音色：${profile.name}`} title="编辑音色" onClick={() => openEdit(profile)} size="small">
                  <Icon name="edit" size={16} />
                </IconButton>
              </div>
            </article>
          ))}
        </div>
      ) : <div className="profile-resource-empty"><Icon name="audio" size={21} />还没有可用的个人音色档案。</div>}

      <Dialog open={Boolean(previewProfile)} onClose={() => setPreviewProfile(null)} maxWidth="sm" fullWidth aria-labelledby="profile-reference-title">
        <DialogTitle className="form-dialog-title">
          <h3 id="profile-reference-title">参考文本</h3>
          <p>{previewProfile?.name}</p>
        </DialogTitle>
        <DialogContent className="form-dialog-content">
          <p className="profile-reference-text">{previewProfile?.ref_text}</p>
        </DialogContent>
        <DialogActions className="modal-actions">
          <Button type="button" onClick={() => setPreviewProfile(null)}>关闭</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(dialog)} onClose={closeDialog} aria-labelledby="profile-voice-dialog-title" maxWidth="sm" fullWidth>
        <DialogTitle className="form-dialog-title"><h3 id="profile-voice-dialog-title">{isEditing ? "编辑克隆音色" : "新增克隆音色"}</h3></DialogTitle>
        <DialogContent className="form-dialog-content">
          <div className="modal-body">
            <TextField className="field" label="音色名称" fullWidth size="small" value={name} onChange={(event) => setName(event.target.value)} />
            <TextField className="field" label="语言" fullWidth size="small" select value={language} onChange={(event) => setLanguage(event.target.value)}>{languages.map((item) => <MenuItem key={item.id} value={item.id}>{item.label}</MenuItem>)}</TextField>
            <div className="form-field-group"><span className="field-label">参考音频{isEditing ? "" : "*"}</span><label className={`upload-dropzone compact ${refAudioFile ? "is-filled" : ""}`}><span className="upload-placeholder"><Icon name={refAudioFile ? "audio" : "upload"} size={22} /><strong>{refAudioFile ? refAudioFile.name : "上传参考音频"}</strong><small>{refAudioFile ? formatFileSize(refAudioFile.size) : isEditing ? "不上传则保留当前参考音频" : "用于保存新的克隆音色"}</small></span><input ref={refAudioInputRef} type="file" accept="audio/*" onChange={onAudioChange} /></label>{refAudioUrl ? <audio className="audio-player" controls src={refAudioUrl} /> : isEditing && editingProfile ? <ProtectedMedia className="audio-player" path={editingProfile.audio_url} kind="audio" backendBaseUrl={backendBaseUrl} /> : null}</div>
            <TextField className="field" label="参考文本" fullWidth size="small" multiline rows={4} value={refText} onChange={(event) => setRefText(event.target.value)} />
            {error ? <div className="form-alert failed">{error}</div> : null}
            {confirmDelete ? <div className="delete-confirm-panel"><strong>确认删除这个个人音色？</strong><span>删除后会移除参考音频和档案记录，无法恢复。</span><div className="delete-confirm-actions"><Button type="button" variant="outlined" disabled={deleting} onClick={() => setConfirmDelete(false)}>取消</Button><Button type="button" color="error" variant="contained" disabled={deleting} onClick={remove} startIcon={<Icon name={deleting ? "loading" : "trash"} size={16} />}>确认删除</Button></div></div> : null}
          </div>
        </DialogContent>
        <DialogActions className="modal-actions with-delete">{isEditing ? <Button type="button" color="error" disabled={saving || deleting} onClick={() => setConfirmDelete(true)} startIcon={<Icon name="trash" size={16} />}>删除</Button> : null}<Button type="button" onClick={closeDialog}>取消</Button><Button type="button" variant="contained" disabled={saving || deleting || !name.trim() || !refText.trim() || (!isEditing && !refAudioFile)} onClick={save} startIcon={<Icon name={saving ? "loading" : "save"} size={16} />}>{saving ? "正在保存" : isEditing ? "保存修改" : "保存音色"}</Button></DialogActions>
      </Dialog>
    </section>
  );
}
