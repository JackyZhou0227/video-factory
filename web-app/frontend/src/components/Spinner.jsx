import { LoaderCircle } from "lucide-react";

export default function Spinner({ size = 16, strokeWidth = 1.8, className = "", label, ...props }) {
  return (
    <LoaderCircle
      aria-hidden={label ? undefined : "true"}
      aria-label={label}
      className={`vf-icon vf-spinner ${className}`.trim()}
      focusable="false"
      size={size}
      strokeWidth={strokeWidth}
      {...props}
    />
  );
}
