import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./Icon";

const API = "/api";

const INSTANCE_OPTIONS = [
  { value: "", label: "默认规格", hint: "使用 RunningHub 默认机器规格" },
  { value: "plus", label: "48G 显存", hint: "适合更大的模型或更高分辨率任务" },
];

export default function Settings() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [maskedApiKey, setMaskedApiKey] = useState("");
  const [apiKeyConfigured, setApiKeyConfigured] = useState(false);
  const [concurrentLimit, setConcurrentLimit] = useState(1);
  const [instanceType, setInstanceType] = useState("");

  const selectedInstance = useMemo(
    () => INSTANCE_OPTIONS.find((option) => option.value === instanceType) ?? INSTANCE_OPTIONS[0],
    [instanceType]
  );

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/settings/runninghub`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setApiKey("");
      setMaskedApiKey(data.masked_api_key || "");
      setApiKeyConfigured(Boolean(data.api_key_configured));
      setConcurrentLimit(data.concurrent_limit || 1);
      setInstanceType(data.instance_type || "");
    } catch (err) {
      setError(err.message || "读取设置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError("");
    setNotice("");

    try {
      const payload = {
        concurrent_limit: Number(concurrentLimit),
        instance_type: instanceType,
      };
      if (apiKey.trim()) payload.api_key = apiKey.trim();

      const response = await fetch(`${API}/settings/runninghub`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${response.status}`);
      }

      const data = await response.json();
      setApiKey("");
      setMaskedApiKey(data.masked_api_key || "");
      setApiKeyConfigured(Boolean(data.api_key_configured));
      setConcurrentLimit(data.concurrent_limit || 1);
      setInstanceType(data.instance_type || "");
      setNotice("RunningHub 设置已保存。后续生成视频会使用新的配置。");
    } catch (err) {
      setError(err.message || "保存失败");
    } finally {
      setSaving(false);
    }
  }, [apiKey, concurrentLimit, instanceType]);

  return (
    <section className="workspace-panel settings-panel" aria-labelledby="settings-title">
      <div className="panel-heading settings-heading">
        <div>
          <span className="section-kicker">RunningHub</span>
          <h2 id="settings-title">云端工作流配置</h2>
        </div>
        <span className={`status-pill ${apiKeyConfigured ? "completed" : "failed"}`}>
          <Icon name={apiKeyConfigured ? "check" : "alert"} size={14} />
          {apiKeyConfigured ? "已配置" : "未配置"}
        </span>
      </div>

      <div className="settings-content">
        <div className="settings-copy">
          <h3>
            <Icon name="serverCog" size={18} />
            用于生成视频的 RunningHub API Key
          </h3>
          <p>
            当前数字人视频生成会调用 RunningHub 工作流。保存后，配置会写入
            <code>config.yaml</code>，后端提交任务时会读取这里的 key。
          </p>
          <div className="settings-current-key">
            <span>当前 Key</span>
            <strong>{maskedApiKey || "尚未配置"}</strong>
          </div>
        </div>

        <div className="settings-form">
          <div className="field">
            <label className="field-label" htmlFor="runninghub-api-key">
              RunningHub API Key
            </label>
            <input
              id="runninghub-api-key"
              className="control"
              type="password"
              placeholder={apiKeyConfigured ? "留空则保持当前 Key" : "请输入 RunningHub API Key"}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              disabled={loading || saving}
              autoComplete="off"
            />
          </div>

          <div className="field-grid">
            <div className="field">
              <label className="field-label" htmlFor="runninghub-concurrent-limit">
                并发限制
              </label>
              <input
                id="runninghub-concurrent-limit"
                className="control"
                type="number"
                min="1"
                max="10"
                value={concurrentLimit}
                onChange={(event) => setConcurrentLimit(event.target.value)}
                disabled={loading || saving}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="runninghub-instance-type">
                机器规格
              </label>
              <select
                id="runninghub-instance-type"
                className="control"
                value={instanceType}
                onChange={(event) => setInstanceType(event.target.value)}
                disabled={loading || saving}
              >
                {INSTANCE_OPTIONS.map((option) => (
                  <option key={option.value || "default"} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="settings-instance-note">
            <strong>
              <Icon name="sliders" size={15} />
              {selectedInstance.label}
            </strong>
            <span>{selectedInstance.hint}</span>
          </div>

          {error && <div className="form-alert failed">{error}</div>}
          {notice && <div className="form-alert completed">{notice}</div>}

          <div className="settings-actions">
            <button
              className="secondary-action"
              type="button"
              onClick={loadSettings}
              disabled={loading || saving}
            >
              <Icon name={loading ? "loading" : "refresh"} size={16} />
              重新读取
            </button>
            <button
              className="primary-action"
              type="button"
              onClick={handleSave}
              disabled={loading || saving}
            >
              <Icon name={saving ? "loading" : "save"} size={16} />
              {saving ? "正在保存" : "保存设置"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
