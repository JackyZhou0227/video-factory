import { useEffect, useState } from "react";
import Icon from "./Icon";
import { apiFetch } from "../lib/backend";

function useProtectedAssetUrl(path, backendBaseUrl) {
  const [state, setState] = useState({ url: "", loading: Boolean(path), error: "" });

  useEffect(() => {
    if (!path) {
      setState({ url: "", loading: false, error: "" });
      return undefined;
    }

    const controller = new AbortController();
    let objectUrl = "";
    setState({ url: "", loading: true, error: "" });

    apiFetch(path, { signal: controller.signal }, backendBaseUrl)
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, loading: false, error: "" });
      })
      .catch((error) => {
        if (error?.name === "AbortError") return;
        setState({ url: "", loading: false, error: error?.message || "读取产物失败" });
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [backendBaseUrl, path]);

  return state;
}

export function ProtectedMedia({ path, kind, backendBaseUrl, alt = "", className = "", ...props }) {
  const { url, loading, error } = useProtectedAssetUrl(path, backendBaseUrl);

  if (loading) {
    return (
      <div className={`protected-asset-state ${className}`.trim()} role="status">
        <Icon name="loading" size={18} />
        正在读取产物
      </div>
    );
  }
  if (error || !url) {
    return (
      <div className={`protected-asset-state is-error ${className}`.trim()} role="status">
        <Icon name="alert" size={18} />
        {error || "产物不可用"}
      </div>
    );
  }

  if (kind === "audio") return <audio className={className} controls src={url} {...props} />;
  if (kind === "image") return <img className={className} src={url} alt={alt} {...props} />;
  return <video className={className} controls preload="metadata" src={url} {...props} />;
}

export function ProtectedDownloadButton({
  path,
  filename,
  backendBaseUrl,
  className = "",
  children,
  disabled = false,
  ...props
}) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");

  const handleDownload = async () => {
    if (!path || disabled || downloading) return;
    setDownloading(true);
    setError("");
    try {
      const response = await apiFetch(path, undefined, backendBaseUrl);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename || "artifact";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    } catch (downloadError) {
      setError(downloadError?.message || "下载失败");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <button
      {...props}
      className={`${className} ${error ? "has-download-error" : ""}`.trim()}
      type="button"
      disabled={disabled || downloading}
      onClick={handleDownload}
      title={error || props.title}
    >
      {downloading ? (
        <><Icon name="loading" size={14} />下载中</>
      ) : error ? (
        <><Icon name="alert" size={14} />重试</>
      ) : (
        children || <><Icon name="download" size={14} />下载</>
      )}
    </button>
  );
}
