import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import Snackbar from "@mui/material/Snackbar";
import MuiAlert from "@mui/material/Alert";
import { designTokens, statusChipColors } from "../theme";
import { setGlobalErrorHandler } from "../lib/backend";

const GlobalMessageContext = createContext({ showError: () => {}, showSuccess: () => {} });

export function useGlobalMessage() {
  return useContext(GlobalMessageContext);
}

const AUTO_HIDE_DURATION = 4000;

// 配色遵循 example/Claude 设计系统：浅色底 + 深色同系文字 + 细边框，不用纯色底白字
const SEVERITY_STYLES = {
  success: {
    bgcolor: statusChipColors.completed.bg,
    color: statusChipColors.completed.fg,
    border: "1px solid #d3dcc1", // success-200
  },
  error: {
    bgcolor: statusChipColors.failed.bg,
    color: statusChipColors.failed.fg,
    border: "1px solid #f3c4bf", // error-200
  },
};

export default function GlobalMessageProvider({ children }) {
  const [message, setMessage] = useState(null);
  const [open, setOpen] = useState(false);

  const show = useCallback((text, severity) => {
    if (!text) return;
    setMessage({ text: String(text), severity, key: Date.now() });
    setOpen(true);
  }, []);

  const showError = useCallback((text) => show(text, "error"), [show]);
  const showSuccess = useCallback((text) => show(text, "success"), [show]);

  useEffect(() => {
    // backend.js 不依赖 React：apiJson 遇到非 2xx 时通过这里弹出统一提示
    setGlobalErrorHandler((error) => showError(error?.message));
    return () => setGlobalErrorHandler(null);
  }, [showError]);

  const contextValue = useMemo(() => ({ showError, showSuccess }), [showError, showSuccess]);

  return (
    <GlobalMessageContext.Provider value={contextValue}>
      {children}
      <Snackbar
        key={message?.key}
        open={open}
        autoHideDuration={AUTO_HIDE_DURATION}
        onClose={(_event, reason) => {
          if (reason === "clickaway") return;
          setOpen(false);
        }}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <MuiAlert
          severity={message?.severity || "error"}
          sx={{
            width: "100%",
            alignItems: "center",
            borderRadius: "10px",
            px: 2,
            py: "10px",
            boxShadow: 3,
            ...(SEVERITY_STYLES[message?.severity] || SEVERITY_STYLES.error),
            "& .MuiAlert-icon": {
              color: "inherit",
              mt: "2px",
            },
            "& .MuiAlert-action": {
              color: "inherit",
            },
          }}
          onClose={() => setOpen(false)}
        >
          {message?.text}
        </MuiAlert>
      </Snackbar>
    </GlobalMessageContext.Provider>
  );
}
