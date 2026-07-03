import { useEffect, useState } from "react";

export const RUNNINGHUB_SETTINGS_STORAGE_KEY = "videoFactory.runninghubSettings";
export const RUNNINGHUB_SETTINGS_EVENT = "video-factory-runninghub-settings-change";

export const DEFAULT_RUNNINGHUB_SETTINGS = {
  apiKey: "",
  workflowId: "",
  concurrentLimit: 1,
  instanceType: "",
};

function isBrowser() {
  return typeof window !== "undefined";
}

export function maskApiKey(apiKey) {
  const value = String(apiKey || "");
  if (!value) return "";
  if (value.length <= 8) return "*".repeat(value.length);
  return `${value.slice(0, 4)}${"*".repeat(Math.max(value.length - 8, 4))}${value.slice(-4)}`;
}

export function normalizeRunningHubSettings(settings) {
  const source = settings || {};
  const concurrentLimit = Number(source.concurrentLimit || 1);

  return {
    apiKey: String(source.apiKey || "").trim(),
    workflowId: String(source.workflowId || "").trim(),
    concurrentLimit: Number.isFinite(concurrentLimit)
      ? Math.min(Math.max(Math.round(concurrentLimit), 1), 10)
      : 1,
    instanceType: String(source.instanceType || "").trim(),
  };
}

export function getRunningHubSettings() {
  if (!isBrowser()) return DEFAULT_RUNNINGHUB_SETTINGS;

  try {
    const raw = window.localStorage.getItem(RUNNINGHUB_SETTINGS_STORAGE_KEY);
    if (!raw) return DEFAULT_RUNNINGHUB_SETTINGS;
    return normalizeRunningHubSettings(JSON.parse(raw));
  } catch {
    return DEFAULT_RUNNINGHUB_SETTINGS;
  }
}

export function saveRunningHubSettings(settings) {
  const normalized = normalizeRunningHubSettings(settings);
  if (!isBrowser()) return normalized;

  window.localStorage.setItem(RUNNINGHUB_SETTINGS_STORAGE_KEY, JSON.stringify(normalized));
  window.dispatchEvent(
    new CustomEvent(RUNNINGHUB_SETTINGS_EVENT, {
      detail: { settings: normalized },
    })
  );

  return normalized;
}

export function useRunningHubSettings() {
  const [settings, setSettings] = useState(() => getRunningHubSettings());

  useEffect(() => {
    const sync = () => setSettings(getRunningHubSettings());

    window.addEventListener(RUNNINGHUB_SETTINGS_EVENT, sync);
    window.addEventListener("storage", sync);

    return () => {
      window.removeEventListener(RUNNINGHUB_SETTINGS_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return settings;
}
