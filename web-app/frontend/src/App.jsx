import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import Icon from "./components/Icon";
import DigitalHuman from "./components/DigitalHuman";
import PosterVideo from "./components/PosterVideo";
import SmartEditing from "./components/SmartEditing";
import TemplateProduction from "./components/TemplateProduction";
import TTSStudio from "./components/TTSStudio";
import TaskCenter from "./components/TaskCenter";
import Settings from "./components/Settings";
import UserManagement from "./components/UserManagement";
import DataDashboard from "./components/DataDashboard";
import UserProfile from "./components/UserProfile";
import SmartSkillHeaderCard from "./components/SmartSkillHeaderCard";
import { useGlobalMessage } from "./components/GlobalMessageProvider";
import { getCurrentUser, listPublicOrganizations, login, logout, register } from "./lib/auth";
import { PAGE_NAMES, PROJECT_NAME } from "./lib/pageNames";

// 角色等级：超管(2) > 组织管理员(1) > 普通成员(0)
const ROLE_LEVELS = { admin: 2, org_admin: 1, user: 0 };

function roleLevel(user) {
  return ROLE_LEVELS[user?.role] ?? 0;
}

const NAV_ITEMS = [
  {
    id: "digital-human",
    label: "数字人",
    description: "口播视频生成",
    icon: "digitalHuman",
  },
  {
    id: "tts-studio",
    label: "语音合成",
    description: "独立 TTS 工作台",
    icon: "mic",
  },
  {
    id: "poster-video",
    label: "大字报视频",
    description: "批量竖屏叠字",
    icon: "type",
  },
  {
    id: "template-production",
    label: "模板量产",
    description: "AI 文案与批量成片",
    icon: "template",
  },
  {
    id: "smart-editing",
    label: "智能剪辑",
    description: "关键词素材自动拼接",
    icon: "smartEdit",
  },
  {
    id: "task-center",
    label: "任务中心",
    description: "生成记录与产物管理",
    icon: "history",
  },
  {
    id: "dashboard",
    label: "数据看板",
    description: "组织与成员用量统计",
    icon: "gauge",
    minRole: 1,
  },
  {
    id: "settings",
    label: "设置",
    description: "服务与模型配置",
    icon: "settings",
  },
  {
    id: "profile",
    label: "个人资料",
    description: "账号与安全设置",
    icon: "user",
  },
  {
    id: "users",
    label: "用户管理",
    description: "账号与密码",
    icon: "shield",
    minRole: 1,
  },
];

const PAGE_META = {
  "digital-human": {
    eyebrow: PAGE_NAMES.digitalHuman,
    title: "数字人口播视频",
    description: "上传人物图片与已生成的口播音频，提交 RunningHub 生成数字人口播视频。",
  },
  "tts-studio": {
    eyebrow: PAGE_NAMES.ttsStudio,
    title: "独立语音合成",
    description: "使用共享克隆音色库或 edge-tts 在线音色生成语音，试听并下载音频文件。",
  },
  "poster-video": {
    eyebrow: PAGE_NAMES.posterVideo,
    title: "大字报视频",
    description: "批量上传视频素材，统一转成 9:16 竖屏并叠加可编辑的大字报文字模板。",
  },
  "template-production": {
    eyebrow: PAGE_NAMES.templateProduction,
    title: "模板量产",
    description: "按固定业务模板组织素材与文案，使用 Edge-TTS 和 FFmpeg 批量生成短视频。",
  },
  "smart-editing": {
    eyebrow: PAGE_NAMES.smartEditing,
    title: "智能剪辑",
    description: "粘贴文案和 Agent 生成的有序关键词，为每个关键词上传素材后自动轮询拼接成片。",
  },
  "task-center": {
    eyebrow: PAGE_NAMES.taskCenter,
    title: "任务中心",
    description: "统一查看生成任务状态、产物预览和安全下载入口。",
  },
  settings: {
    eyebrow: PAGE_NAMES.settings,
    title: "设置",
    description: "管理当前用户的 RunningHub 和 LLM 服务配置。",
  },
  profile: {
    eyebrow: "Account",
    title: "个人资料",
    description: "管理显示名称和账号安全设置。",
  },
  dashboard: {
    eyebrow: "Dashboard",
    title: "数据看板",
    description: "按时间、组织和成员维度查看任务量与产物量统计。",
  },
  users: {
    eyebrow: PAGE_NAMES.userManagement,
    title: "用户管理",
    description: "查看用户列表，管理用户账号角色与登录密码。",
  },
};

const DEFAULT_PAGE = "digital-human";

function pageFromPathname(pathname) {
  const id = pathname.replace(/^\/+|\/+$/g, "");
  if (id === "organizations") return "users"; // 组织管理已并入用户管理页
  return PAGE_META[id] ? id : null;
}

function AuthScreen({ registrationEnabled, onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [orgId, setOrgId] = useState("");
  const [organizations, setOrganizations] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const { showSuccess } = useGlobalMessage();

  const isRegister = mode === "register";
  const title = isRegister ? "注册账号" : "登录账号";
  const actionLabel = isRegister ? "提交注册申请" : "登录";

  useEffect(() => {
    if (!isRegister || organizations.length > 0) return;
    listPublicOrganizations()
      .then((data) => setOrganizations(data.organizations || []))
      .catch(() => setOrganizations([]));
  }, [isRegister, organizations.length]);

  const handleSubmit = useCallback(
    async (event) => {
      event.preventDefault();
      setError("");

      if (isRegister && password !== passwordConfirm) {
        setError("两次输入的密码不一致");
        return;
      }

      setSubmitting(true);
      try {
        const data = isRegister
          ? await register(username.trim(), password, displayName, orgId)
          : await login(username.trim(), password);
        if (isRegister && data.pending) {
          showSuccess("注册申请已提交，等待组织管理员审批，批准后即可登录。");
          setMode("login");
          setUsername("");
          setPassword("");
          setPasswordConfirm("");
          setDisplayName("");
          setOrgId("");
        } else {
          onAuthenticated(data.user);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setSubmitting(false);
      }
    },
    [displayName, isRegister, onAuthenticated, orgId, password, passwordConfirm, showSuccess, username]
  );

  const switchMode = useCallback(() => {
    setMode((current) => (current === "login" ? "register" : "login"));
    setError("");
    setPassword("");
    setPasswordConfirm("");
  }, []);

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand">
          <div className="auth-logo">
            <Icon name="digitalHuman" size={32} />
          </div>
          <div>
            <Typography variant="eyebrow" component="p" className="eyebrow">{PROJECT_NAME}</Typography>
            <h1 id="auth-title">{title}</h1>
          </div>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <TextField
            id="auth-username"
            label="用户名"
            fullWidth
            size="small"
            type="text"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            placeholder="3-32 位英文、数字或下划线"
            required
          />

          {isRegister && (
            <TextField
              id="auth-display-name"
              label="显示名称"
              fullWidth
              size="small"
              type="text"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              autoComplete="name"
              placeholder="可选"
            />
          )}

          {isRegister && (
            <div className="field">
              <span className="field-label">所属组织</span>
              <TextField
                id="auth-org"
                fullWidth
                size="small"
                select
                value={orgId}
                onChange={(event) => setOrgId(event.target.value)}
                required
              >
                {organizations.map((org) => (
                  <MenuItem key={org.id} value={org.id}>{org.name}</MenuItem>
                ))}
              </TextField>
              <p className="field-help">
                {organizations.length === 0 ? "暂无可选组织，请联系管理员" : "注册后等待组织管理员审批"}
              </p>
            </div>
          )}

          <TextField
            id="auth-password"
            label="密码"
            fullWidth
            size="small"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={isRegister ? "new-password" : "current-password"}
            placeholder="至少 8 位"
            required
          />

          {isRegister && (
            <TextField
              id="auth-password-confirm"
              label="确认密码"
              fullWidth
              size="small"
              type="password"
              value={passwordConfirm}
              onChange={(event) => setPasswordConfirm(event.target.value)}
              autoComplete="new-password"
              placeholder="再次输入密码"
              required
            />
          )}

          {error && <div className="form-alert failed">{error}</div>}

          <Button
            className="auth-submit"
            type="submit"
            variant="contained"
            color="primary"
            disabled={submitting}
            startIcon={<Icon name={submitting ? "loading" : isRegister ? "check" : "lock"} size={16} />}
          >
            {submitting ? "处理中..." : actionLabel}
          </Button>
        </form>

        {registrationEnabled && (
          <Button className="auth-switch" type="button" variant="text" onClick={switchMode}>
            {isRegister ? "已有账号，去登录" : "还没有账号，申请注册"}
          </Button>
        )}
        {!isRegister && <p className="auth-help-text">忘记密码请联系管理员重置。</p>}
      </section>
    </main>
  );
}
function LoadingScreen() {
  return (
    <main className="auth-shell">
      <section className="auth-panel compact">
        <div className="auth-logo">
          <Icon name="loading" size={28} />
        </div>
        <p className="auth-loading-text">正在验证登录状态...</p>
      </section>
    </main>
  );
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const routePage = pageFromPathname(location.pathname);
  const activePage = routePage || DEFAULT_PAGE;
  const [authChecking, setAuthChecking] = useState(true);
  const [currentUser, setCurrentUser] = useState(null);
  const [registrationEnabled, setRegistrationEnabled] = useState(false);
  const [authError, setAuthError] = useState("");
  const currentRoleLevel = roleLevel(currentUser);
  const visibleNavItems = useMemo(
    () => NAV_ITEMS.filter((item) => !item.minRole || currentRoleLevel >= item.minRole),
    [currentRoleLevel]
  );
  const pageMeta = useMemo(() => PAGE_META[activePage], [activePage]);
  const handlePageChange = useCallback(
    (pageId) => {
      navigate(`/${pageId}`);
      window.scrollTo({ top: 0, left: 0 });
    },
    [navigate]
  );

  useEffect(() => {
    let cancelled = false;

    getCurrentUser()
      .then((data) => {
        if (cancelled) return;
        setCurrentUser(data.authenticated ? data.user : null);
        setRegistrationEnabled(Boolean(data.registration_enabled));
      })
      .catch((err) => {
        if (cancelled) return;
        setAuthError(err.message);
        setCurrentUser(null);
      })
      .finally(() => {
        if (cancelled) return;
        setAuthChecking(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (authChecking || !currentUser) return;
    // URL 不指向有效页面、或指向无权限页面时，纠正到默认页（保留刷新/直达能力）
    const guardedPage = routePage && NAV_ITEMS.find((item) => item.id === routePage);
    if (routePage && (!guardedPage?.minRole || currentRoleLevel >= guardedPage.minRole)) return;
    navigate(`/${DEFAULT_PAGE}`, { replace: true });
  }, [authChecking, currentRoleLevel, currentUser, navigate, routePage]);

  const handleLogout = useCallback(async () => {
    try {
      await logout();
    } catch {
      // 错误已由全局提示展示
    } finally {
      setCurrentUser(null);
      navigate(`/${DEFAULT_PAGE}`, { replace: true });
    }
  }, [navigate]);

  if (authChecking) return <LoadingScreen />;

  if (!currentUser) {
    return (
      <>
        <AuthScreen registrationEnabled={registrationEnabled} onAuthenticated={setCurrentUser} />
        {authError && <div className="auth-floating-error">{authError}</div>}
      </>
    );
  }

  return (
    <div className="app-layout">
      <aside className="app-sidebar" aria-label="主导航">
        <nav className="sidebar-nav">
          <List disablePadding sx={{ display: "grid", gap: "4px" }}>
            {visibleNavItems.map((item) => (
              <ListItemButton
                key={item.id}
                className={`nav-item ${activePage === item.id ? "is-active" : ""}`}
                onClick={() => handlePageChange(item.id)}
                aria-current={activePage === item.id ? "page" : undefined}
                sx={{
                  minHeight: 44,
                  alignItems: "center",
                  py: "6px",
                  px: "12px",
                  gap: "10px",
                }}
              >
                <span className="nav-icon">
                  <Icon name={item.icon} size={20} />
                </span>
                <span className="nav-item-main">
                  <strong>{item.label}</strong>
                </span>
              </ListItemButton>
            ))}
          </List>
        </nav>

        <div className="sidebar-account" aria-label="当前账号">
          <div className="sidebar-account-main">
            <span className="sidebar-account-kicker">当前账号</span>
            <strong title={currentUser.display_name || currentUser.username}>
              {currentUser.display_name || currentUser.username}
            </strong>
            <span title={currentUser.username}>@{currentUser.username}</span>
          </div>
          <div className="sidebar-account-actions">
            <span className={`sidebar-role ${currentRoleLevel > 0 ? "admin" : ""}`}>
              <Icon name={currentRoleLevel > 0 ? "shield" : "user"} size={14} />
              {currentUser.is_admin ? "超级管理员" : currentUser.is_org_admin ? "组织管理员" : "普通账号"}
            </span>
            <Button
              className="sidebar-logout"
              type="button"
              variant="text"
              size="small"
              onClick={handleLogout}
              startIcon={<Icon name="logout" size={15} />}
            >
              退出
            </Button>
          </div>
        </div>
      </aside>

      <main className="app-shell">
        <header className="app-header">
          <div>
            <Typography variant="eyebrow" component="p" className="eyebrow">{pageMeta.eyebrow}</Typography>
            <h1>{pageMeta.title}</h1>
            <p className="app-description">{pageMeta.description}</p>
          </div>
          {activePage === "smart-editing" ? <SmartSkillHeaderCard /> : null}
        </header>

        <div className="page-stack">
          <div className={`app-main page-panel ${activePage === "digital-human" ? "is-active" : ""}`}>
            <DigitalHuman onOpenTtsStudio={() => handlePageChange("tts-studio")} />
          </div>
          <div className={`app-main page-panel ${activePage === "tts-studio" ? "is-active" : ""}`}>
            <TTSStudio active={activePage === "tts-studio"} />
          </div>
          <div className={`app-main page-panel ${activePage === "poster-video" ? "is-active" : ""}`}>
            <PosterVideo />
          </div>
          <div className={`app-main page-panel ${activePage === "template-production" ? "is-active" : ""}`}>
            <TemplateProduction currentUser={currentUser} />
          </div>
          <div className={`app-main page-panel ${activePage === "smart-editing" ? "is-active" : ""}`}>
            <SmartEditing currentUser={currentUser} />
          </div>
          <div className={`app-main page-panel ${activePage === "task-center" ? "is-active" : ""}`}>
            <TaskCenter active={activePage === "task-center"} />
          </div>
          <div className={`settings-main page-panel ${activePage === "settings" ? "is-active" : ""}`}>
            <Settings />
          </div>
          <div className={`settings-main page-panel ${activePage === "profile" ? "is-active" : ""}`}>
            <UserProfile currentUser={currentUser} onUserUpdated={setCurrentUser} onLoggedOut={handleLogout} />
          </div>
          <div className={`settings-main page-panel ${activePage === "users" ? "is-active" : ""}`}>
            <UserManagement currentUser={currentUser} />
          </div>
          <div className={`settings-main page-panel ${activePage === "dashboard" ? "is-active" : ""}`}>
            <DataDashboard currentUser={currentUser} />
          </div>
        </div>
      </main>
    </div>
  );
}
