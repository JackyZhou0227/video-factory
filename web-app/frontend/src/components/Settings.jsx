import { useCallback, useEffect, useMemo, useState } from "react";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import IconButton from "@mui/material/IconButton";
import TextField from "@mui/material/TextField";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import Icon from "./Icon";
import { useGlobalMessage } from "./GlobalMessageProvider";
import { apiJson, getBackendDisplayUrl, useBackendBaseUrl } from "../lib/backend";
import { maskApiKey } from "../lib/runninghubSettings";

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

const RUNNINGHUB_GUIDE_IMAGES = [1, 2, 3].map((step) => `/runninghub-key-guide/${step}.jpg`);

export default function Settings() {
  const backendBaseUrl = useBackendBaseUrl();
  const [loading, setLoading] = useState(true);
  const [savingRunningHub, setSavingRunningHub] = useState(false);
  const [savingLlm, setSavingLlm] = useState(false);
  const [testingLlm, setTestingLlm] = useState(false);
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
  const [runningHubGuideOpen, setRunningHubGuideOpen] = useState(false);
  const llmReady = Boolean(llmBaseUrl.trim() && llmModel.trim());
  const llmTestPassed = testedLlmVersion !== null && testedLlmVersion === llmFormVersion;
  const { showError, showSuccess } = useGlobalMessage();

  const updateLlmField = useCallback((setter, value) => {
    setter(value);
    setLlmFormVersion((version) => version + 1);
    setTestedLlmVersion(null);
    setLlmSaved(false);
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
    try {
      applySettings(await apiJson("/api/settings", undefined, backendBaseUrl));
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      setLoading(false);
    }
  }, [applySettings, backendBaseUrl]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const saveRunningHub = useCallback(async () => {
    setSavingRunningHub(true);
    const payload = { concurrent_limit: Number(concurrentLimit || 1), instance_type: instanceType };
    if (runningHubKey.trim()) payload.api_key = runningHubKey.trim();
    try {
      const data = await apiJson(
        "/api/settings/runninghub",
        { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        backendBaseUrl
      );
      setRunninghub({ ...EMPTY_RUNNINGHUB, ...data });
      setRunningHubKey("");
      showSuccess("RunningHub 设置已保存。");
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      setSavingRunningHub(false);
    }
  }, [backendBaseUrl, concurrentLimit, instanceType, runningHubKey, showSuccess]);

  const saveLlm = useCallback(async () => {
    if (!llmTestPassed) {
      showError("请先测试当前 LLM 配置，连接成功后再保存。");
      return;
    }
    setSavingLlm(true);
    const payload = { base_url: llmBaseUrl.trim(), model: llmModel.trim() };
    if (llmApiKey.trim()) payload.api_key = llmApiKey.trim();
    try {
      const data = await apiJson(
        "/api/settings/llm",
        { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        backendBaseUrl
      );
      setLlm({ ...EMPTY_LLM, ...data });
      setLlmApiKey("");
      setLlmFormVersion((version) => version + 1);
      setTestedLlmVersion(null);
      setLlmSaved(true);
      showSuccess("LLM 服务配置已保存。");
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      setSavingLlm(false);
    }
  }, [backendBaseUrl, llmApiKey, llmBaseUrl, llmModel, llmTestPassed, showError, showSuccess]);

  const clearLlmKey = useCallback(async () => {
    setSavingLlm(true);
    try {
      const data = await apiJson(
        "/api/settings/llm",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base_url: llmBaseUrl.trim(), model: llmModel.trim(), clear_api_key: true }),
        },
        backendBaseUrl
      );
      setLlm({ ...EMPTY_LLM, ...data });
      setLlmApiKey("");
      setLlmFormVersion((version) => version + 1);
      setTestedLlmVersion(null);
      setLlmSaved(true);
      showSuccess("LLM API Key 已清除。");
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      setSavingLlm(false);
    }
  }, [backendBaseUrl, llmBaseUrl, llmModel, showSuccess]);

  const testLlm = useCallback(async () => {
    const versionUnderTest = llmFormVersion;
    setTestingLlm(true);
    setTestedLlmVersion(null);
    setLlmSaved(false);
    const payload = { base_url: llmBaseUrl.trim(), model: llmModel.trim() };
    if (llmApiKey.trim()) payload.api_key = llmApiKey.trim();
    try {
      await apiJson(
        "/api/settings/llm/test",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
        backendBaseUrl
      );
      setTestedLlmVersion(versionUnderTest);
      showSuccess("LLM 连接测试成功，可以保存当前配置。");
    } catch {
      // 错误已由 apiJson 弹出全局提示
    } finally {
      setTestingLlm(false);
    }
  }, [backendBaseUrl, llmApiKey, llmBaseUrl, llmFormVersion, llmModel, showSuccess]);

  return (
    <section className="workspace-panel settings-panel" aria-label="设置工作区">
      <div className="settings-service-list">
        <section className="settings-service-section" aria-labelledby="runninghub-settings-title">
          <div className="settings-service-copy">
            <h3 id="runninghub-settings-title"><Icon name="cloud" size={19} />RunningHub 配置</h3>
            <p>保存当前用户的 RunningHub API Key，并配置任务并发和机器规格。</p>
            <dl className="settings-summary">
              <div><dt>API Key</dt><dd>{runningHubKey.trim() ? maskApiKey(runningHubKey) : runninghub.api_key_masked || "尚未配置"}</dd></div>
            </dl>
            <div className="runninghub-key-link-slot">
              <div className="runninghub-key-actions">
                <Button
                  className="runninghub-key-link"
                  href="https://www.runninghub.cn/?inviteCode=kwqbktmi"
                  target="_blank"
                  rel="noreferrer"
                  variant="text"
                >
                  <span className="runninghub-key-link-copy"><strong>前往RunningHub</strong></span>
                  <Icon name="external" size={15} />
                </Button>
                <Button className="runninghub-key-link" type="button" variant="text" onClick={() => setRunningHubGuideOpen(true)}>
                  <span className="runninghub-key-link-copy"><strong>获取教程</strong></span>
                  <Icon name="book" size={15} />
                </Button>
              </div>
            </div>
          </div>
          <div className="settings-form service-settings-form">
            <TextField className="field" label="API Key" fullWidth size="small" type="password" autoComplete="off" value={runningHubKey} onChange={(event) => setRunningHubKey(event.target.value)} placeholder={runninghub.api_key_configured ? "已配置，留空则不修改" : "输入 RunningHub API Key"} />
            <TextField className="field" label="并发任务数" fullWidth size="small" type="number" slotProps={{ htmlInput: { min: 1, max: 10 } }} value={concurrentLimit} onChange={(event) => setConcurrentLimit(Math.max(1, Math.min(10, Number(event.target.value) || 1)))} />
            <TextField className="field" label="机器规格" fullWidth size="small" select value={instanceType} onChange={(event) => setInstanceType(event.target.value)}>
              {INSTANCE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </TextField>
            <div className="settings-actions"><Button type="button" variant="contained" onClick={saveRunningHub} disabled={savingRunningHub} startIcon={<Icon name={savingRunningHub ? "loading" : "save"} size={16} />}>{savingRunningHub ? "正在保存" : "保存"}</Button></div>
          </div>
        </section>

        <section className="settings-service-section" aria-labelledby="llm-settings-title">
          <div className="settings-service-copy">
            <h3 id="llm-settings-title"><Icon name="sparkles" size={19} />LLM 服务配置</h3>
            <p>保存当前用户的接口地址、模型名称和 API Key，供项目内需要大语言模型的功能统一调用。接口需兼容 OpenAI Chat Completions 协议。</p>
            <dl className="settings-summary">
              <div><dt>API Key</dt><dd>{llmApiKey.trim() ? maskApiKey(llmApiKey) : llm.api_key_masked || "未配置或无需密钥"}</dd></div>
              <div><dt>状态</dt><dd>{testingLlm ? "正在测试" : llmTestPassed ? "测试通过" : llmSaved ? "已保存" : llmReady ? "等待测试" : "等待配置"}</dd></div>
            </dl>
          </div>
          <div className="settings-form service-settings-form">
            <TextField className="field" label="Base URL" fullWidth size="small" type="url" value={llmBaseUrl} onChange={(event) => updateLlmField(setLlmBaseUrl, event.target.value)} placeholder="https://api.openai.com/v1" />
            <TextField className="field" label="模型名称" fullWidth size="small" value={llmModel} onChange={(event) => updateLlmField(setLlmModel, event.target.value)} placeholder="例如：gpt-4o-mini 或 deepseek-chat" />
            <TextField className="field" label="API Key" fullWidth size="small" type="password" autoComplete="off" value={llmApiKey} onChange={(event) => updateLlmField(setLlmApiKey, event.target.value)} placeholder={llm.api_key_configured ? "已配置，留空则不修改" : "本地无鉴权服务可留空"} />
            <div className="settings-actions llm-settings-actions">
              <Button type="button" variant="outlined" size="small" onClick={testLlm} disabled={testingLlm || !llmReady} startIcon={<Icon name={testingLlm ? "loading" : "lab"} size={16} />}>{testingLlm ? "正在测试" : llmTestPassed ? "重新测试" : "测试连接"}</Button>
              {llm.api_key_configured ? <Button type="button" color="error" size="small" onClick={clearLlmKey} disabled={savingLlm}>清除密钥</Button> : null}
              <Button type="button" variant="contained" onClick={saveLlm} disabled={savingLlm || testingLlm || !llmReady || !llmTestPassed} startIcon={<Icon name={savingLlm ? "loading" : "save"} size={16} />}>{savingLlm ? "正在保存" : "保存"}</Button>
            </div>
          </div>
        </section>
      </div>

      <Dialog
        open={runningHubGuideOpen}
        onClose={() => setRunningHubGuideOpen(false)}
        aria-labelledby="runninghub-guide-title"
        maxWidth="md"
      >
        <DialogTitle sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", pr: 1.5 }}>
          获取教程
          <IconButton onClick={() => setRunningHubGuideOpen(false)} aria-label="关闭" title="关闭" size="small">
            <Icon name="x" size={17} />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          <div className="runninghub-guide-images">
            {RUNNINGHUB_GUIDE_IMAGES.map((src) => <img key={src} src={src} alt="" />)}
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
