import { useCallback, useEffect, useMemo, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Icon from "./Icon";
import { useGlobalMessage } from "./GlobalMessageProvider";
import { apiJson, useBackendBaseUrl } from "../lib/backend";


function makeId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export default function SubtitleReplacementManager({ currentUserId = "", onStatusChange }) {
  const backendBaseUrl = useBackendBaseUrl();
  const { showSuccess } = useGlobalMessage();
  const [replacements, setReplacements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [savingIds, setSavingIds] = useState(() => new Set());
  const [dirtyIds, setDirtyIds] = useState(() => new Set());
  const [savedIds, setSavedIds] = useState(() => new Set());
  const [pendingDelete, setPendingDelete] = useState(null);

  const issues = useMemo(() => {
    const nextIssues = [];
    const seenSources = new Set();
    replacements.forEach((item, index) => {
      const source = item.source.trim();
      const replacement = item.replacement.trim();
      if (!source || !replacement) {
        nextIssues.push(`第 ${index + 1} 条字幕替换需要填写原词和替换词`);
      } else if (source === replacement) {
        nextIssues.push(`第 ${index + 1} 条字幕替换的原词和替换词不能相同`);
      } else if (seenSources.has(source)) {
        nextIssues.push(`字幕原词“${source}”重复添加`);
      }
      if (source) seenSources.add(source);
    });
    return nextIssues;
  }, [replacements]);

  const hasUnsaved = dirtyIds.size > 0;

  useEffect(() => {
    onStatusChange?.({ issues, hasUnsaved, loading, error });
  }, [error, hasUnsaved, issues, loading, onStatusChange]);

  const loadReplacements = useCallback(async ({ signal } = {}) => {
    setLoading(true);
    setError("");
    try {
      const data = await apiJson(
        "/api/template-production/subtitle-replacements",
        signal ? { signal, silentError: true } : { silentError: true },
        backendBaseUrl
      );
      setReplacements(Array.isArray(data.replacements) ? data.replacements : []);
      setDirtyIds(new Set());
      setSavedIds(new Set());
    } catch (loadError) {
      if (loadError?.name !== "AbortError") {
        setError(loadError.message || "读取个人敏感词替换失败");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    const controller = new AbortController();
    loadReplacements({ signal: controller.signal });
    return () => controller.abort();
  }, [currentUserId, loadReplacements]);

  const addReplacement = useCallback(() => {
    const id = makeId();
    setReplacements((current) => {
      return [...current, { id, source: "", replacement: "" }];
    });
  }, []);

  const updateReplacement = useCallback((id, field, value) => {
    setReplacements((current) => current.map((item) => (
      item.id === id ? { ...item, [field]: value } : item
    )));
    setDirtyIds((current) => new Set(current).add(id));
    setSavedIds((current) => {
      const next = new Set(current);
      next.delete(id);
      return next;
    });
  }, []);

  const saveReplacement = useCallback(async (id) => {
    const item = replacements.find((replacement) => replacement.id === id);
    if (!item) return;
    const source = item.source.trim();
    const replacement = item.replacement.trim();
    if (!source || !replacement || source === replacement) return;

    setSavingIds((current) => new Set(current).add(id));
    setError("");
    try {
      const isDraft = typeof id === "string";
      const data = await apiJson(
        isDraft
          ? "/api/template-production/subtitle-replacements"
          : `/api/template-production/subtitle-replacements/${id}`,
        {
          method: isDraft ? "POST" : "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source, replacement }),
          silentError: true,
        },
        backendBaseUrl
      );
      setReplacements((current) => current.map((currentItem) => (
        currentItem.id === id ? data.replacement : currentItem
      )));
      setDirtyIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSavedIds((current) => new Set(current).add(data.replacement.id));
      showSuccess("个人敏感词替换已保存。");
    } catch (saveError) {
      setError(saveError.message || "保存个人敏感词替换失败");
    } finally {
      setSavingIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }, [backendBaseUrl, replacements, showSuccess]);

  const removeReplacement = useCallback(async (id) => {
    if (typeof id === "string") {
      setReplacements((current) => current.filter((item) => item.id !== id));
      setDirtyIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSavedIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      showSuccess("个人敏感词替换已删除。");
      return true;
    }

    setSavingIds((current) => new Set(current).add(id));
    setError("");
    try {
      await apiJson(
        `/api/template-production/subtitle-replacements/${id}`,
        { method: "DELETE", silentError: true },
        backendBaseUrl
      );
      setReplacements((current) => current.filter((item) => item.id !== id));
      setDirtyIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSavedIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      showSuccess("个人敏感词替换已删除。");
      return true;
    } catch (removeError) {
      setError(removeError.message || "删除当前用户的敏感词替换失败");
      return false;
    } finally {
      setSavingIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }, [backendBaseUrl, showSuccess]);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const deleted = await removeReplacement(pendingDelete.id);
    if (deleted) setPendingDelete(null);
  }, [pendingDelete, removeReplacement]);

  return (
    <>
      <div className="subtitle-replacement-editor">
        <div className="subtitle-replacement-heading">
          <div>
            <strong>个人敏感词替换</strong>
            <small>配音保留原词，最终字幕按个人规则替换</small>
          </div>
          {replacements.length ? (
            <Button
              className="subtitle-replacement-add"
              type="button"
              variant="outlined"
              size="small"
              onClick={addReplacement}
              startIcon={<Icon name="plus" size={14} />}
            >
              添加
            </Button>
          ) : null}
        </div>
        {replacements.length ? (
          <div className="subtitle-replacement-list">
            {replacements.map((item, index) => {
              const isSaving = savingIds.has(item.id);
              const isDirty = dirtyIds.has(item.id);
              const isSaved = savedIds.has(item.id);
              const source = item.source.trim();
              const replacement = item.replacement.trim();
              const duplicateSource = replacements.some((other) => (
                other.id !== item.id && other.source.trim() === source && Boolean(source)
              ));
              const canSave = isDirty && Boolean(source) && Boolean(replacement)
                && source !== replacement && !duplicateSource;
              return (
                <div className="subtitle-replacement-card" key={item.id}>
                  <TextField
                    className="subtitle-replacement-source"
                    label="需要替换的词"
                    fullWidth
                    size="small"
                    value={item.source}
                    slotProps={{ htmlInput: { maxLength: 80 } }}
                    placeholder="例如：医生"
                    aria-label={`第 ${index + 1} 条需要替换的词`}
                    onChange={(event) => updateReplacement(item.id, "source", event.target.value)}
                    disabled={isSaving}
                  />
                  <span className="subtitle-replacement-arrow" aria-hidden="true">
                    <Icon name="arrowRight" size={16} />
                  </span>
                  <TextField
                    className="subtitle-replacement-target"
                    label="字幕替换成"
                    fullWidth
                    size="small"
                    value={item.replacement}
                    slotProps={{ htmlInput: { maxLength: 80 } }}
                    placeholder="例如：yi生"
                    aria-label={`第 ${index + 1} 条字幕替换词`}
                    onChange={(event) => updateReplacement(item.id, "replacement", event.target.value)}
                    disabled={isSaving}
                  />
                  <Button
                    className="subtitle-replacement-save"
                    type="button"
                    variant="contained"
                    size="small"
                    title="保存此条个人敏感词替换"
                    onClick={() => saveReplacement(item.id)}
                    disabled={!canSave || isSaving}
                    startIcon={<Icon name={isSaving ? "loading" : isSaved ? "check" : "save"} size={14} />}
                  >
                    {isSaving ? "保存中" : isSaved ? "已保存" : "保存"}
                  </Button>
                  <IconButton
                    type="button"
                    title={`删除第 ${index + 1} 条字幕替换`}
                    aria-label={`删除第 ${index + 1} 条字幕替换`}
                    onClick={() => setPendingDelete(item)}
                    disabled={isSaving}
                    size="small"
                  >
                    <Icon name="trash" size={15} />
                  </IconButton>
                </div>
              );
            })}
          </div>
        ) : (
          <Button className="subtitle-replacement-add-card" type="button" variant="outlined" onClick={addReplacement} startIcon={<Icon name="plus" size={18} />}>
            <span><strong>添加替换规则</strong><small>原词用于配音，替换词仅显示在字幕中</small></span>
          </Button>
        )}
        {issues.length ? (
          <div className="subtitle-replacement-issue"><Icon name="alert" size={14} />{issues[0]}</div>
        ) : null}
        {loading ? (
          <div className="subtitle-replacement-issue"><Icon name="loading" size={14} />正在加载个人规则</div>
        ) : null}
        {error ? (
          <div className="subtitle-replacement-issue"><Icon name="alert" size={14} />{error}</div>
        ) : null}
      </div>

      <Dialog
        open={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        aria-labelledby="subtitle-replacement-delete-title"
      >
        <DialogTitle>
          <Typography variant="kicker" component="span" className="section-kicker">Global Rule</Typography>
          <h3 id="subtitle-replacement-delete-title">确认删除敏感词替换？</h3>
        </DialogTitle>
        <DialogContent>
          <p>“{pendingDelete?.source}”将不再替换为“{pendingDelete?.replacement}”。</p>
          <small>此变更会影响所有用户后续创建的视频任务，已创建的任务不受影响。</small>
        </DialogContent>
        <DialogActions>
          <Button type="button" onClick={() => setPendingDelete(null)}>取消</Button>
          <Button type="button" color="error" variant="contained" onClick={confirmDelete} startIcon={<Icon name="trash" size={15} />}>确认删除</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
