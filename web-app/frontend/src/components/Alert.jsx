import { useEffect, useState } from "react";
import MuiAlert from "@mui/material/Alert";

export default function Alert({ type = "info", children }) {
  const isError = type === "error";
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setVisible(false), 3600);
    return () => window.clearTimeout(timeoutId);
  }, []);

  if (!visible) return null;

  return (
    <MuiAlert
      severity={isError ? "error" : "success"}
      variant="outlined"
      role={isError ? "alert" : "status"}
      sx={{ gap: 1 }}
    >
      {children}
    </MuiAlert>
  );
}
