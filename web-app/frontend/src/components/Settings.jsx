import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./Icon";
import {
  getBackendDisplayUrl,
  normalizeBackendBaseUrl,
  saveBackendBaseUrl,
  useBackendBaseUrl,
} from "../lib/backend";
import {
  maskApiKey,
  saveRunningHubSettings,
  useRunningHubSettings,
} from "../lib/runninghubSettings";

const INSTANCE_OPTIONS = [
  { value: "", label: "默认规格", hint: "使用 RunningHub 默认机器规格" },
  { value: "plus", label: "48G 显存", hint: "适合更大的模型或更高分辨率任务" },
];

export default function Settings() {
  const backendBaseUrl = useBackendBaseUrl();
  const runningHubSettings = useRunningHubSettings();
  const [notice, setNotice] = useState("");
  const [backendUrlDraft, setBackendUrlDraft] = useState(backendBaseUrl);
  const [backendUrlError, setBackendUrlError] = useState("");
  const [apiKey, setApiKey] = useState(runningHubSettings.apiKey);
  const [workflowId, setWorkflowId] = useState(runningHubSettings.workflowId);
  const [concurrentLimit, setConcurrentLimit] = useState(runningHubSettings.concurrentLimit);
  const [instanceType, setInstanceType] = useState(runningHubSettings.instanceType);

  const selectedInstance = useMemo(
    () => INSTANCE_OPTIONS.find((option) => option.value === instanceType) ?? INSTANCE_OPTIONS[0],
    [instanceType]
  );
  const backendDisplayUrl = useMemo(() => getBackendDisplayUrl(backendBaseUrl), [backendBaseUrl]);
  const apiKeyConfigured = Boolean(runningHubSettings.apiKey);
  const workflowConfigured = Boolean(runningHubSettings.workflowId);
  const runningHubConfigured = apiKeyConfigured && workflowConfigured;

  useEffect(() => {
    setBackendUrlDraft(backendBaseUrl);
  }, [backendBaseUrl]);

  useEffect(() => {
    setApiKey(runningHubSettings.apiKey);
    setWorkflowId(runningHubSettings.workflowId);
    setConcurrentLimit(runningHubSettings.concurrentLimit);
    setInstanceType(runningHubSettings.instanceType);
  }, [runningHubSettings]);

  const handleSaveBackendUrl = useCallback(() => {
    setBackendUrlError("");
    setNotice("");

    try {
      const normalized = normalizeBackendBaseUrl(backendUrlDraft);
      const saved = saveBackendBaseUrl(normalized);
      setBackendUrlDraft(saved);
      setNotice(saved ? `后端地址已保存：${saved}` : "已切回当前前端同源后端。");
    } catch (err) {
      setBackendUrlError(err.message || "后端地址格式不正确");
    }
  }, [backendUrlDraft]);

  const handleSaveRunningHub = useCallback(() => {
    const saved = saveRunningHubSettings({
      apiKey,
      workflowId,
      concurrentLimit,
      instanceType,
    });

    setApiKey(saved.apiKey);
    setWorkflowId(saved.workflowId);
    setConcurrentLimit(saved.concurrentLimit);
    setInstanceType(saved.instanceType);
    setNotice("RunningHub 设置已保存在当前浏览器。后续生成视频会随请求发送这组配置。");
  }, [apiKey, concurrentLimit, instanceType, workflowId]);

  const handleReloadRunningHub = useCallback(() => {
    setApiKey(runningHubSettings.apiKey);
    setWorkflowId(runningHubSettings.workflowId);
    setConcurrentLimit(runningHubSettings.concurrentLimit);
    setInstanceType(runningHubSettings.instanceType);
    setNotice("已重新读取当前浏览器里的 RunningHub 设置。");
  }, [runningHubSettings]);

  return (
    <section className="workspace-panel settings-panel" aria-labelledby="settings-title">
      <div className="panel-heading settings-heading">
        <div>
          <span className="section-kicker">RunningHub</span>
          <h2 id="settings-title">本机设置</h2>
        </div>
        <span className={`status-pill ${runningHubConfigured ? "completed" : "failed"}`}>
          <Icon name={runningHubConfigured ? "check" : "alert"} size={14} />
          {runningHubConfigured ? "已配置" : "未配置"}
        </span>
      </div>

      <div className="settings-backend-bar">
        <div className="settings-backend-copy">
          <span className="section-kicker">Backend</span>
          <h3>
            <Icon name="serverCog" size={18} />
            后端服务地址
          </h3>
          <p>前端会把接口请求和生成文件预览都发送到这里。留空时使用当前前端同源地址。</p>
          <strong>{backendDisplayUrl}</strong>
        </div>

        <div className="settings-backend-form">
          <div className="field">
            <label className="field-label" htmlFor="backend-base-url">
              后端地址
            </label>
            <input
              id="backend-base-url"
              className="control"
              type="text"
              placeholder="例如 http://192.168.1.20:8001"
              value={backendUrlDraft}
              onChange={(event) => setBackendUrlDraft(event.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="settings-backend-actions">
            <button className="secondary-action" type="button" onClick={() => setBackendUrlDraft("")}>
              清空
            </button>
            <button className="primary-action" type="button" onClick={handleSaveBackendUrl}>
              <Icon name="save" size={16} />
              保存后端地址
            </button>
          </div>

          {backendUrlError && <div className="form-alert failed">{backendUrlError}</div>}
        </div>
      </div>

      <div className="settings-content">
        <div className="settings-copy">
          <h3>
            <Icon name="serverCog" size={18} />
            当前电脑的 RunningHub 配置
          </h3>
          <p>
            这些配置只保存在当前浏览器，不写入后端 <code>config.yaml</code>。生成视频时，前端会把它们随任务一起发送给后端。
          </p>
          <div className="settings-current-key">
            <span>当前 Key</span>
            <strong>{maskApiKey(runningHubSettings.apiKey) || "尚未配置"}</strong>
          </div>
          <div className="settings-current-key">
            <span>当前工作流 ID</span>
            <strong>{runningHubSettings.workflowId || "尚未配置"}</strong>
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
              placeholder="请输入 RunningHub API Key"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              autoComplete="off"
            />
          </div>

          <div className="field">
            <label className="field-label" htmlFor="runninghub-workflow-id">
              RunningHub 工作流 ID
            </label>
            <input
              id="runninghub-workflow-id"
              className="control"
              type="text"
              placeholder="请输入数字人工作流 ID"
              value={workflowId}
              onChange={(event) => setWorkflowId(event.target.value)}
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

          {notice && <div className="form-alert completed">{notice}</div>}

          <div className="settings-actions">
            <button className="secondary-action" type="button" onClick={handleReloadRunningHub}>
              <Icon name="refresh" size={16} />
              重新读取
            </button>
            <button className="primary-action" type="button" onClick={handleSaveRunningHub}>
              <Icon name="save" size={16} />
              保存设置
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
