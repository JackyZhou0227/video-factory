import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./Icon";
import { apiFetch, getBackendDisplayUrl, useBackendBaseUrl } from "../lib/backend";
import { maskApiKey } from "../lib/runninghubSettings";

const INSTANCE_OPTIONS = [
  { value: "", label: "默认规格", hint: "使用 RunningHub 默认机器规格" },
  { value: "plus", label: "48G 显存", hint: "适合更大的模型或更高分辨率任务" },
];

const EMPTY_RUNNINGHUB_SETTINGS = {
  user: {
    id: "local-default",
    username: "local",
    display_name: "用户",
  },
  api_key_configured: false,
  api_key_masked: "",
  workflow_id: "",
  concurrent_limit: 1,
  instance_type: "",
};

function normalizeSettingsPayload(data) {
  return {
    ...EMPTY_RUNNINGHUB_SETTINGS,
    ...(data?.runninghub || data || {}),
  };
}

export default function Settings() {
  const backendBaseUrl = useBackendBaseUrl();
  const backendDisplayUrl = useMemo(() => getBackendDisplayUrl(backendBaseUrl), [backendBaseUrl]);

  const [notice, setNotice] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [loadingSettings, setLoadingSettings] = useState(true);
  const [savingSettings, setSavingSettings] = useState(false);
  const [storedSettings, setStoredSettings] = useState(EMPTY_RUNNINGHUB_SETTINGS);
  const [apiKey, setApiKey] = useState("");
  const [concurrentLimit, setConcurrentLimit] = useState(1);
  const [instanceType, setInstanceType] = useState("");

  const selectedInstance = useMemo(
    () => INSTANCE_OPTIONS.find((option) => option.value === instanceType) ?? INSTANCE_OPTIONS[0],
    [instanceType]
  );
  const apiKeyConfigured = Boolean(apiKey.trim()) || storedSettings.api_key_configured;
  const runningHubConfigured = apiKeyConfigured;

  const loadSettings = useCallback(async () => {
    setLoadingSettings(true);
    setSettingsError("");
    setNotice("");

    try {
      const response = await apiFetch("/api/settings", undefined, backendBaseUrl);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      const runninghub = normalizeSettingsPayload(data);
      setStoredSettings(runninghub);
      setApiKey("");
      setConcurrentLimit(runninghub.concurrent_limit || 1);
      setInstanceType(runninghub.instance_type || "");
    } catch (err) {
      setSettingsError(err.message || "读取设置失败");
    } finally {
      setLoadingSettings(false);
    }
  }, [backendBaseUrl]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleSaveRunningHub = useCallback(async () => {
    setSettingsError("");
    setNotice("");
    setSavingSettings(true);

    const payload = {
      concurrent_limit: Number(concurrentLimit || 1),
      instance_type: instanceType,
    };
    if (apiKey.trim()) payload.api_key = apiKey.trim();

    try {
      const response = await apiFetch(
        "/api/settings/runninghub",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        backendBaseUrl
      );
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || `HTTP ${response.status}`);
      }

      const runninghub = normalizeSettingsPayload(await response.json());
      setStoredSettings(runninghub);
      setApiKey("");
      setConcurrentLimit(runninghub.concurrent_limit || 1);
      setInstanceType(runninghub.instance_type || "");
      setNotice("RunningHub 设置已保存。");
    } catch (err) {
      setSettingsError(err.message || "保存设置失败");
    } finally {
      setSavingSettings(false);
    }
  }, [apiKey, backendBaseUrl, concurrentLimit, instanceType]);

  const visibleApiKey = apiKey.trim()
    ? maskApiKey(apiKey)
    : storedSettings.api_key_masked || "尚未配置";

  return (
    <section className="workspace-panel settings-panel" aria-labelledby="settings-title">
      <div className="panel-heading settings-heading">
        <div>
          <span className="section-kicker">RunningHub</span>
          <h2 id="settings-title">设置</h2>
        </div>
        <span className={`status-pill ${runningHubConfigured ? "completed" : "failed"}`}>
          <Icon name={runningHubConfigured ? "check" : "alert"} size={14} />
          {runningHubConfigured ? "已配置" : "未配置"}
        </span>
      </div>

      <div className="settings-content single-settings-content">
        <div className="settings-copy">
          <h3>
            <Icon name="serverCog" size={18} />
            当前用户的 RunningHub 配置
          </h3>
          <p>
            这些配置按用户保存在 <code>data/video_factory.db</code>，刷新页面、换浏览器或客户重启服务后都会保留。
            前端和后端同机部署，接口会自动连接到 <code>{backendDisplayUrl}</code>。
          </p>
          <div className="settings-current-key">
            <span>当前用户</span>
            <strong>{storedSettings.user?.display_name || "用户"} · {storedSettings.user?.id || "local-default"}</strong>
          </div>
          <div className="settings-current-key">
            <span>当前 Key</span>
            <strong>{visibleApiKey}</strong>
          </div>
          <div className="settings-current-key">
            <span>固定工作流 ID</span>
            <strong>{storedSettings.workflow_id || "系统内置"}</strong>
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
              placeholder={storedSettings.api_key_configured ? "已配置，留空则不修改" : "请输入 RunningHub API Key"}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
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

          {loadingSettings && <div className="form-alert completed">正在读取设置...</div>}
          {notice && <div className="form-alert completed">{notice}</div>}
          {settingsError && <div className="form-alert failed">{settingsError}</div>}

          <div className="settings-actions">
            <button className="secondary-action" type="button" onClick={loadSettings} disabled={loadingSettings || savingSettings}>
              <Icon name={loadingSettings ? "loading" : "refresh"} size={16} />
              重新读取
            </button>
            <button className="primary-action" type="button" onClick={handleSaveRunningHub} disabled={savingSettings}>
              <Icon name={savingSettings ? "loading" : "save"} size={16} />
              {savingSettings ? "正在保存" : "保存设置"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
