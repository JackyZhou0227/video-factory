import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./Icon";
import { apiFetch, getBackendDisplayUrl, useBackendBaseUrl } from "../lib/backend";
import { maskApiKey } from "../lib/runninghubSettings";
import { changePassword } from "../lib/auth";

const DEFAULT_INSTANCE_TYPE = "plus";
const INSTANCE_OPTIONS = [
  { value: "", label: "24G 显存" },
  { value: "plus", label: "48G 显存" },
];

const EMPTY_RUNNINGHUB = {
  api_key_configured: false,
  api_key_masked: "",
  concurrent_limit: 1,
  instance_type: DEFAULT_INSTANCE_TYPE,
};

const EMPTY_LLM = {
  base_url: "https://api.openai.com/v1",
  model: "",
  api_key_configured: false,
  api_key_masked: "",
};

export default function Settings({ onLoggedOut }) {
  const backendBaseUrl = useBackendBaseUrl();
  const backendDisplayUrl = useMemo(() => getBackendDisplayUrl(backendBaseUrl), [backendBaseUrl]);
  const [loading, setLoading] = useState(true);
  const [savingRunningHub, setSavingRunningHub] = useState(false);
  const [savingLlm, setSavingLlm] = useState(false);
  const [testingLlm, setTestingLlm] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [runninghub, setRunninghub] = useState(EMPTY_RUNNINGHUB);
  const [runningHubKey, setRunningHubKey] = useState("");
  const [concurrentLimit, setConcurrentLimit] = useState(1);
  const [instanceType, setInstanceType] = useState(DEFAULT_INSTANCE_TYPE);
  const [llm, setLlm] = useState(EMPTY_LLM);
  const [llmBaseUrl, setLlmBaseUrl] = useState(EMPTY_LLM.base_url);
  const [llmModel, setLlmModel] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmFormVersion, setLlmFormVersion] = useState(0);
  const [testedLlmVersion, setTestedLlmVersion] = useState(null);
  const [llmSaved, setLlmSaved] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  const llmReady = Boolean(llmBaseUrl.trim() && llmModel.trim());
  const llmTestPassed = testedLlmVersion !== null && testedLlmVersion === llmFormVersion;

  const updateLlmField = useCallback((setter, value) => {
    setter(value);
    setLlmFormVersion((version) => version + 1);
    setTestedLlmVersion(null);
    setLlmSaved(false);
    setNotice("");
    setError("");
  }, []);

  const applySettings = useCallback((data) => {
    const nextRunninghub = { ...EMPTY_RUNNINGHUB, ...(data?.runninghub || {}) };
    const nextLlm = { ...EMPTY_LLM, ...(data?.llm || {}) };
    setRunninghub(nextRunninghub);
    setRunningHubKey("");
    setConcurrentLimit(nextRunninghub.concurrent_limit || 1);
    setInstanceType(nextRunninghub.instance_type);
    setLlm(nextLlm);
    setLlmBaseUrl(nextLlm.base_url || EMPTY_LLM.base_url);
    setLlmModel(nextLlm.model || "");
    setLlmApiKey("");
    setLlmFormVersion((version) => version + 1);
    setTestedLlmVersion(null);
    setLlmSaved(false);
  }, []);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await apiFetch("/api/settings", undefined, backendBaseUrl);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      applySettings(await response.json());
    } catch (err) {
      setError(err.message || "读取设置失败");
    } finally {
      setLoading(false);
    }
  }, [applySettings, backendBaseUrl]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const saveRunningHub = useCallback(async () => {
    setSavingRunningHub(true);
    setNotice("");
    setError("");
    const payload = { concurrent_limit: Number(concurrentLimit || 1), instance_type: instanceType };
    if (runningHubKey.trim()) payload.api_key = runningHubKey.trim();
    try {
      const response = await apiFetch(
        "/api/settings/runninghub",
        { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        backendBaseUrl
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      setRunninghub({ ...EMPTY_RUNNINGHUB, ...data });
      setRunningHubKey("");
      setNotice("RunningHub 设置已保存。");
    } catch (err) {
      setError(err.message || "保存 RunningHub 设置失败");
    } finally {
      setSavingRunningHub(false);
    }
  }, [backendBaseUrl, concurrentLimit, instanceType, runningHubKey]);

  const saveLlm = useCallback(async () => {
    if (!llmTestPassed) {
      setError("请先测试当前 LLM 配置，连接成功后再保存。");
      return;
    }
    setSavingLlm(true);
    setNotice("");
    setError("");
    const payload = { base_url: llmBaseUrl.trim(), model: llmModel.trim() };
    if (llmApiKey.trim()) payload.api_key = llmApiKey.trim();
    try {
      const response = await apiFetch(
        "/api/settings/llm",
        { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        backendBaseUrl
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      setLlm({ ...EMPTY_LLM, ...data });
      setLlmApiKey("");
      setLlmFormVersion((version) => version + 1);
      setTestedLlmVersion(null);
      setLlmSaved(true);
      setNotice("LLM 服务配置已保存。");
    } catch (err) {
      setError(err.message || "保存 LLM 服务配置失败");
    } finally {
      setSavingLlm(false);
    }
  }, [backendBaseUrl, llmApiKey, llmBaseUrl, llmModel, llmTestPassed]);

  const clearLlmKey = useCallback(async () => {
    setSavingLlm(true);
    setNotice("");
    setError("");
    try {
      const response = await apiFetch(
        "/api/settings/llm",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base_url: llmBaseUrl.trim(), model: llmModel.trim(), clear_api_key: true }),
        },
        backendBaseUrl
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      setLlm({ ...EMPTY_LLM, ...data });
      setLlmApiKey("");
      setLlmFormVersion((version) => version + 1);
      setTestedLlmVersion(null);
      setLlmSaved(true);
      setNotice("LLM API Key 已清除。");
    } catch (err) {
      setError(err.message || "清除 LLM API Key 失败");
    } finally {
      setSavingLlm(false);
    }
  }, [backendBaseUrl, llmBaseUrl, llmModel]);

  const testLlm = useCallback(async () => {
    const versionUnderTest = llmFormVersion;
    setTestingLlm(true);
    setTestedLlmVersion(null);
    setLlmSaved(false);
    setNotice("");
    setError("");
    const payload = { base_url: llmBaseUrl.trim(), model: llmModel.trim() };
    if (llmApiKey.trim()) payload.api_key = llmApiKey.trim();
    try {
      const response = await apiFetch(
        "/api/settings/llm/test",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        backendBaseUrl
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      setTestedLlmVersion(versionUnderTest);
      setNotice("LLM 连接测试成功，可以保存当前配置。");
    } catch (err) {
      setError(err.message || "LLM 连接测试失败");
    } finally {
      setTestingLlm(false);
    }
  }, [backendBaseUrl, llmApiKey, llmBaseUrl, llmFormVersion, llmModel]);

  const submitPasswordChange = useCallback(async (event) => {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致。");
      return;
    }
    setChangingPassword(true);
    setNotice("");
    setError("");
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setNotice("密码已修改，请重新登录。");
      window.setTimeout(() => onLoggedOut?.(), 500);
    } catch (err) {
      setError(err.message || "修改密码失败");
    } finally {
      setChangingPassword(false);
    }
  }, [confirmPassword, currentPassword, newPassword, onLoggedOut]);

  return (
    <section className="workspace-panel settings-panel" aria-label="设置工作区">
      <div className="settings-backend-bar">
        <div className="settings-backend-copy">
          <h3><Icon name="serverCog" size={18} />后端服务</h3>
          <p>当前页面连接到 <strong>{backendDisplayUrl}</strong></p>
        </div>
        <button className="secondary-action" type="button" onClick={loadSettings} disabled={loading}>
          <Icon name={loading ? "loading" : "refresh"} size={15} />刷新配置
        </button>
      </div>

      <div className="settings-service-list">
        <section className="settings-service-section" aria-labelledby="password-settings-title">
          <div className="settings-service-copy">
            <span className="section-kicker">Account security</span>
            <h3 id="password-settings-title"><Icon name="shield" size={19} />修改密码</h3>
            <p>修改后所有已登录设备都会退出，需要使用新密码重新登录。</p>
          </div>
          <form className="settings-form service-settings-form" onSubmit={submitPasswordChange}>
            <label className="field">
              <span className="field-label">当前密码</span>
              <input className="control" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required />
            </label>
            <label className="field">
              <span className="field-label">新密码</span>
              <input className="control" type="password" autoComplete="new-password" minLength="8" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required />
            </label>
            <label className="field">
              <span className="field-label">确认新密码</span>
              <input className="control" type="password" autoComplete="new-password" minLength="8" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required />
            </label>
            <div className="settings-actions"><button className="primary-action" type="submit" disabled={changingPassword}><Icon name={changingPassword ? "loading" : "save"} size={16} />{changingPassword ? "正在修改" : "修改密码"}</button></div>
          </form>
        </section>
        <section className="settings-service-section" aria-labelledby="runninghub-settings-title">
          <div className="settings-service-copy">
            <span className="section-kicker">RunningHub</span>
            <h3 id="runninghub-settings-title"><Icon name="cloud" size={19} />RunningHub 配置</h3>
            <p>保存当前用户的 RunningHub API Key，并配置任务并发和机器规格。</p>
            <dl className="settings-summary">
              <div><dt>API Key</dt><dd>{runningHubKey.trim() ? maskApiKey(runningHubKey) : runninghub.api_key_masked || "尚未配置"}</dd></div>
            </dl>
            <div className="runninghub-key-link-slot">
              <a
                className="runninghub-key-link"
                href="https://www.runninghub.cn/?inviteCode=kwqbktmi"
                rel="noreferrer"
                target="_blank"
              >
                <span className="runninghub-key-link-copy">
                  <strong>还没有 RunningHub API Key？</strong>
                  <small>前往 RunningHub 获取</small>
                </span>
                <Icon name="external" size={15} />
              </a>
            </div>
          </div>
          <div className="settings-form service-settings-form">
            <label className="field">
              <span className="field-label">API Key</span>
              <input className="control" type="password" autoComplete="off" value={runningHubKey} onChange={(event) => setRunningHubKey(event.target.value)} placeholder={runninghub.api_key_configured ? "已配置，留空则不修改" : "输入 RunningHub API Key"} />
            </label>
            <label className="field">
              <span className="field-label">并发任务数</span>
              <input className="control" type="number" min="1" max="10" value={concurrentLimit} onChange={(event) => setConcurrentLimit(Math.max(1, Math.min(10, Number(event.target.value) || 1)))} />
            </label>
            <label className="field">
              <span className="field-label">机器规格</span>
              <select className="control" value={instanceType} onChange={(event) => setInstanceType(event.target.value)}>
                {INSTANCE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <div className="settings-actions"><button className="primary-action" type="button" onClick={saveRunningHub} disabled={savingRunningHub}><Icon name={savingRunningHub ? "loading" : "save"} size={16} />{savingRunningHub ? "正在保存" : "保存"}</button></div>
          </div>
        </section>

        <section className="settings-service-section" aria-labelledby="llm-settings-title">
          <div className="settings-service-copy">
            <span className="section-kicker">LLM Service</span>
            <h3 id="llm-settings-title"><Icon name="sparkles" size={19} />LLM 服务配置</h3>
            <p>保存当前用户的接口地址、模型名称和 API Key，供项目内需要大语言模型的功能统一调用。接口需兼容 OpenAI Chat Completions 协议。</p>
            <dl className="settings-summary">
              <div><dt>API Key</dt><dd>{llmApiKey.trim() ? maskApiKey(llmApiKey) : llm.api_key_masked || "未配置或无需密钥"}</dd></div>
              <div><dt>状态</dt><dd>{testingLlm ? "正在测试" : llmTestPassed ? "测试通过" : llmSaved ? "已保存" : llmReady ? "等待测试" : "等待配置"}</dd></div>
            </dl>
          </div>
          <div className="settings-form service-settings-form">
            <label className="field">
              <span className="field-label">Base URL</span>
              <input className="control" type="url" value={llmBaseUrl} onChange={(event) => updateLlmField(setLlmBaseUrl, event.target.value)} placeholder="https://api.openai.com/v1" />
            </label>
            <label className="field">
              <span className="field-label">模型名称</span>
              <input className="control" value={llmModel} onChange={(event) => updateLlmField(setLlmModel, event.target.value)} placeholder="例如：gpt-4o-mini 或 deepseek-chat" />
            </label>
            <label className="field">
              <span className="field-label">API Key</span>
              <input className="control" type="password" autoComplete="off" value={llmApiKey} onChange={(event) => updateLlmField(setLlmApiKey, event.target.value)} placeholder={llm.api_key_configured ? "已配置，留空则不修改" : "本地无鉴权服务可留空"} />
            </label>
            <div className="settings-actions llm-settings-actions">
              <button className="secondary-action" type="button" onClick={testLlm} disabled={testingLlm || !llmReady}><Icon name={testingLlm ? "loading" : "lab"} size={16} />{testingLlm ? "正在测试" : llmTestPassed ? "重新测试" : "测试连接"}</button>
              {llm.api_key_configured ? <button className="text-button danger-text-button" type="button" onClick={clearLlmKey} disabled={savingLlm}>清除密钥</button> : null}
              <button className="primary-action" type="button" onClick={saveLlm} disabled={savingLlm || testingLlm || !llmReady || !llmTestPassed}><Icon name={savingLlm ? "loading" : "save"} size={16} />{savingLlm ? "正在保存" : "保存"}</button>
            </div>
          </div>
        </section>
      </div>

      {error ? <div className="form-alert failed">{error}</div> : null}
      {notice ? <div className="form-alert completed">{notice}</div> : null}
    </section>
  );
}
