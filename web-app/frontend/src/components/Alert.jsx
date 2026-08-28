import { useEffect, useState } from "react";
import Icon from "./Icon";

export default function Alert({ type = "info", children }) {
  const isError = type === "error";
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => setVisible(false), 3600);
    return () => window.clearTimeout(timeoutId);
  }, []);

  if (!visible) return null;

  return (
    <div className={`app-alert ${isError ? "failed" : "completed"}`} role={isError ? "alert" : "status"}>
      <Icon name={isError ? "alert" : "check"} size={15} />
      <span>{children}</span>
    </div>
  );
}
