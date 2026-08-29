import { createTheme } from "@mui/material/styles";

/*
 * 视觉规范：example/Claude 设计系统（colors_and_type.css），全部取值不发明新值。
 * 亮色模式；UI 正文用 Poppins，标题用 Newsreader，阅读长文可用 Lora。
 */
const tokens = {
  background: "#faf9f5", // bg-100
  card: "#f5f4ef", // bg-200
  popover: "#ffffff", // bg-50
  muted: "#ede9de", // bg-300
  secondary: "#e9e6dc",
  foreground: "#3d3929", // text-800
  textMuted: "#6e6d68", // text-500
  textSoft: "#9b988c", // text-400
  border: "#dad9d4", // border-300
  primary: "#c96442", // brand-500 terra-cotta
  primaryDark: "#b0562f", // brand-600
  primarySoft: "#fbf2ed", // brand-50
  success: "#788c5d", // success-500
  successSoft: "#f0f3ea",
  error: "#d64545", // error-500
  errorSoft: "#fcecea",
  info: "#6a9bcc",
  infoSoft: "#e5edf4",
  sidebar: "#f5f4ee",
  sidebarAccent: "#e9e6dc",
};

export const designTokens = tokens;

export const statusChipColors = {
  running: { bg: tokens.infoSoft, fg: "#3d678c" },
  pending: { bg: tokens.muted, fg: tokens.textMuted },
  previewing: { bg: tokens.primarySoft, fg: tokens.primaryDark },
  ready: { bg: tokens.primarySoft, fg: tokens.primaryDark },
  completed: { bg: tokens.successSoft, fg: "#4f5d3a" },
  submitted: { bg: tokens.infoSoft, fg: "#3d678c" },
  failed: { bg: tokens.errorSoft, fg: "#962c2c" },
  cancelled: { bg: tokens.muted, fg: tokens.textSoft },
  partial_failed: { bg: tokens.errorSoft, fg: "#962c2c" },
  idle: { bg: tokens.muted, fg: tokens.textMuted },
};

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: tokens.primary, dark: tokens.primaryDark, contrastText: "#ffffff" },
    secondary: { main: tokens.secondary, contrastText: tokens.foreground },
    success: { main: tokens.success, contrastText: "#ffffff" },
    error: { main: tokens.error, contrastText: "#ffffff" },
    info: { main: tokens.info, contrastText: "#ffffff" },
    background: { default: tokens.background, paper: tokens.card },
    text: { primary: tokens.foreground, secondary: tokens.textMuted, disabled: tokens.textSoft },
    divider: tokens.border,
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: '"Poppins", "Inter", "Segoe UI", "Microsoft YaHei", system-ui, sans-serif',
    h1: { fontFamily: '"Newsreader", Georgia, ui-serif, serif', fontWeight: 500 },
    h2: { fontFamily: '"Newsreader", Georgia, ui-serif, serif', fontWeight: 500 },
    h3: { fontFamily: '"Newsreader", Georgia, ui-serif, serif', fontWeight: 500 },
    button: { textTransform: "none", fontWeight: 600 },
    // Claude 风格的英文小标题：页面级 eyebrow（品牌色）/ 区块级 kicker（次级灰）
    eyebrow: {
      fontSize: "11px",
      fontWeight: 600,
      letterSpacing: "0.12em",
      textTransform: "uppercase",
      color: tokens.primaryDark,
      lineHeight: 1.4,
    },
    kicker: {
      fontSize: "11px",
      fontWeight: 600,
      letterSpacing: "0.1em",
      textTransform: "uppercase",
      color: tokens.textSoft,
      lineHeight: 1.4,
    },
  },
  shadows: [
    "none",
    "0 1px 3px 0 rgba(0, 0, 0, 0.05)",
    "0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.1)",
    ...Array(22).fill("0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 4px 6px -1px rgba(0, 0, 0, 0.1)"),
  ],
  components: {
    MuiInputBase: {
      styleOverrides: {
        // 输入框的值是"被阅读的内容" → Lora（Claude 四字体角色之一）
        input: { fontFamily: "var(--font-serif)" },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        // 浮动标签与内容统一用 Lora
        root: { fontFamily: "var(--font-serif)" },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 8 },
        sizeSmall: { padding: "4px 12px", fontSize: 13 },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: tokens.popover,
          "& fieldset": { borderColor: tokens.border },
          "&:hover fieldset": { borderColor: tokens.primary },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 999, fontWeight: 600 },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: { borderRadius: 16, backgroundImage: "none" },
      },
    },
    MuiPaper: {
      styleOverrides: { root: { backgroundImage: "none" } },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { borderRadius: 999, backgroundColor: tokens.muted, height: 8 },
        bar: { borderRadius: 999 },
      },
    },
    MuiToggleButtonGroup: {
      styleOverrides: {
        root: { backgroundColor: tokens.popover, borderRadius: 8 },
      },
    },
    MuiTableContainer: {
      styleOverrides: {
        root: { backgroundColor: "transparent" },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottom: `1px solid ${tokens.border}`,
          borderRight: `1px solid ${tokens.border}`,
          textAlign: "center",
          color: tokens.textMuted,
          fontSize: 13,
          padding: "14px 16px",
        },
        head: {
          backgroundColor: tokens.muted,
          color: tokens.foreground,
          fontSize: 12,
          fontWeight: 700,
        },
        body: { verticalAlign: "middle" },
      },
    },
  },
});

export default theme;
