import Button from "@mui/material/Button";
import ButtonGroup from "@mui/material/ButtonGroup";
import TextField from "@mui/material/TextField";
import { useCallback, useMemo, useState } from "react";

// 空值时原生 date 输入会显示 yyyy/MM/dd 掩码，改为文本框显示「不限」占位
export function DateField({ label, name, value, onAccept, onChange, fullWidth = false, sx }) {
  const [editing, setEditing] = useState(false);
  const showDatePicker = editing || Boolean(value);
  const mergedSx = { ...(fullWidth ? {} : { width: 150 }), ...sx };
  const commonProps = {
    label,
    size: "small",
    name,
    fullWidth,
    sx: mergedSx,
  };

  if (!showDatePicker) {
    return (
      <TextField
        {...commonProps}
        type="text"
        placeholder="不限"
        value=""
        onFocus={() => setEditing(true)}
        onMouseDown={() => setEditing(true)}
        onClick={() => setEditing(true)}
      />
    );
  }

  return (
    <TextField
      {...commonProps}
      type="date"
      slotProps={{ inputLabel: { shrink: true } }}
      value={value}
      onChange={onChange}
      onBlur={() => {
        if (!value) setEditing(false);
        onAccept?.();
      }}
    />
  );
}

const DAY_SHORTCUTS = [
  { days: 7, label: "近7天" },
  { days: 30, label: "近30天" },
  { days: 90, label: "近90天" },
];

function fmt(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function matchesShortcut(from, to, days) {
  if (!from || !to) return false;
  const expectedFrom = fmt(new Date(Date.now() - (days - 1) * 86400000));
  return from === expectedFrom && to === fmt(new Date());
}

// 统计时间范围：日期选择器为主，快捷按钮只是快速填充
export default function StatsTimeRange({ from, to, onChange }) {
  const activeShortcut = useMemo(() => {
    if (!from && !to) return "all";
    for (const shortcut of DAY_SHORTCUTS) {
      if (matchesShortcut(from, to, shortcut.days)) return String(shortcut.days);
    }
    return "";
  }, [from, to]);

  const applyShortcut = useCallback((value) => {
    if (value === "all") {
      onChange({ from: "", to: "" });
      return;
    }
    const days = Number(value);
    onChange({ from: fmt(new Date(Date.now() - (days - 1) * 86400000)), to: fmt(new Date()) });
  }, [onChange]);

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 10, flexWrap: "wrap" }}>
      <DateField
        label="开始日期"
        value={from}
        onChange={(event) => onChange({ from: event.target.value, to })}
      />
      <DateField
        label="结束日期"
        value={to}
        onChange={(event) => onChange({ from, to: event.target.value })}
      />
      <ButtonGroup size="small" variant={activeShortcut ? "contained" : "outlined"} sx={{ mb: "1px" }}>
        {DAY_SHORTCUTS.map((shortcut) => (
          <Button
            key={shortcut.days}
            type="button"
            variant={activeShortcut === String(shortcut.days) ? "contained" : "outlined"}
            onClick={() => applyShortcut(String(shortcut.days))}
          >
            {shortcut.label}
          </Button>
        ))}
        <Button
          type="button"
          variant={activeShortcut === "all" ? "contained" : "outlined"}
          onClick={() => applyShortcut("all")}
        >
          全部
        </Button>
      </ButtonGroup>
    </div>
  );
}
