import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./Icon";
import { apiFetch, useBackendBaseUrl } from "../lib/backend";


function makeId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

async function responseError(response, fallback) {
  const data = await response.json().catch(() => ({}));
  return data.detail || data.message || fallback || `HTTP ${response.status}`;
}

export default function SubtitleReplacementManager({ currentUserId = "", onStatusChange }) {
  const backendBaseUrl = useBackendBaseUrl();
  const [replacements, setReplacements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
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
    setNotice("");
    try {
      const response = await apiFetch(
        "/api/template-production/subtitle-replacements",
        signal ? { signal } : undefined,
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "读取个人敏感词替换失败"));
      const data = await response.json();
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
    setNotice("");
    setError("");
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
    setNotice("");
    setError("");
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
      const response = await apiFetch(
        isDraft
          ? "/api/template-production/subtitle-replacements"
          : `/api/template-production/subtitle-replacements/${id}`,
        {
          method: isDraft ? "POST" : "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source, replacement }),
        },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "保存个人敏感词替换失败"));
      const data = await response.json();
      setReplacements((current) => current.map((currentItem) => (
        currentItem.id === id ? data.replacement : currentItem
      )));
      setDirtyIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      setSavedIds((current) => new Set(current).add(data.replacement.id));
      setNotice("个人敏感词替换已保存。");
    } catch (saveError) {
      setError(saveError.message || "保存个人敏感词替换失败");
    } finally {
      setSavingIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }, [backendBaseUrl, replacements]);

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
      setNotice("个人敏感词替换已删除。");
      return true;
    }

    setSavingIds((current) => new Set(current).add(id));
    setError("");
    try {
      const response = await apiFetch(
        `/api/template-production/subtitle-replacements/${id}`,
        { method: "DELETE" },
        backendBaseUrl
      );
      if (!response.ok) throw new Error(await responseError(response, "删除个人敏感词替换失败"));
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
      setNotice("个人敏感词替换已删除。");
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
  }, [backendBaseUrl]);

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
            <button
              className="secondary-action subtitle-replacement-add"
              type="button"
              onClick={addReplacement}
            >
              <Icon name="plus" size={14} />添加
            </button>
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
                  <label className="field subtitle-replacement-source">
                    <span className="field-label">需要替换的词</span>
                    <input
                      className="control"
                      value={item.source}
                      maxLength={80}
                      placeholder="例如：医生"
                      aria-label={`第 ${index + 1} 条需要替换的词`}
                      onChange={(event) => updateReplacement(item.id, "source", event.target.value)}
                      disabled={isSaving}
                    />
                  </label>
                  <span className="subtitle-replacement-arrow" aria-hidden="true">
                    <Icon name="arrowRight" size={16} />
                  </span>
                  <label className="field subtitle-replacement-target">
                    <span className="field-label">字幕替换成</span>
                    <input
                      className="control"
                      value={item.replacement}
                      maxLength={80}
                      placeholder="例如：yi生"
                      aria-label={`第 ${index + 1} 条字幕替换词`}
                      onChange={(event) => updateReplacement(item.id, "replacement", event.target.value)}
                      disabled={isSaving}
                    />
                  </label>
                  <button
                    className="primary-action subtitle-replacement-save"
                    type="button"
                    title="保存此条个人敏感词替换"
                    onClick={() => saveReplacement(item.id)}
                    disabled={!canSave || isSaving}
                  >
                    <Icon name={isSaving ? "loading" : isSaved ? "check" : "save"} size={14} />
                    {isSaving ? "保存中" : isSaved ? "已保存" : "保存"}
                  </button>
                  <button
                    className="subtitle-replacement-remove"
                    type="button"
                    title={`删除第 ${index + 1} 条字幕替换`}
                    aria-label={`删除第 ${index + 1} 条字幕替换`}
                    onClick={() => setPendingDelete(item)}
                    disabled={isSaving}
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <button className="subtitle-replacement-add-card" type="button" onClick={addReplacement}>
            <Icon name="plus" size={18} />
            <span><strong>添加替换规则</strong><small>原词用于配音，替换词仅显示在字幕中</small></span>
          </button>
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
        {notice ? (
          <div className="subtitle-replacement-notice"><Icon name="check" size={14} />{notice}</div>
        ) : null}
      </div>

      {pendingDelete ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal-panel"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="subtitle-replacement-delete-title"
          >
            <div className="modal-heading">
              <div>
                <span className="section-kicker">Global Rule</span>
                <h3 id="subtitle-replacement-delete-title">确认删除敏感词替换？</h3>
              </div>
            </div>
            <div className="modal-body">
              <p>“{pendingDelete.source}”将不再替换为“{pendingDelete.replacement}”。</p>
              <small>此变更会影响所有用户后续创建的视频任务，已创建的任务不受影响。</small>
            </div>
            <div className="delete-confirm-actions">
              <button className="secondary-action" type="button" onClick={() => setPendingDelete(null)}>
                取消
              </button>
              <button className="danger-action" type="button" onClick={confirmDelete}>
                <Icon name="trash" size={15} />确认删除
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
