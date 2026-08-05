import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./components/Icon";
import DigitalHuman from "./components/DigitalHuman";
import PosterVideo from "./components/PosterVideo";
import TemplateProduction from "./components/TemplateProduction";
import TTSStudio from "./components/TTSStudio";
import Settings from "./components/Settings";
import UserManagement from "./components/UserManagement";
import { getCurrentUser, login, logout, register } from "./lib/auth";

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
    id: "settings",
    label: "设置",
    description: "服务与模型配置",
    icon: "settings",
  },
  {
    id: "users",
    label: "用户管理",
    description: "账号与密码",
    icon: "shield",
    adminOnly: true,
  },
];

const PAGE_META = {
  "digital-human": {
    eyebrow: "Video Factory",
    title: "数字人口播视频",
    description: "上传人物图片与已生成的口播音频，提交 RunningHub 生成数字人口播视频。",
    badge: "本地工作台",
    badgeIcon: "monitorCog",
  },
  "tts-studio": {
    eyebrow: "TTS Studio",
    title: "独立语音合成",
    description: "使用共享克隆音色库或 edge-tts 在线音色生成语音，试听并下载音频文件。",
    badge: "本地音频生成",
    badgeIcon: "waves",
  },
  "poster-video": {
    eyebrow: "Poster Video",
    title: "大字报视频",
    description: "批量上传视频素材，统一转成 9:16 竖屏并叠加可编辑的大字报文字模板。",
    badge: "本地批处理",
    badgeIcon: "wand",
  },
  "template-production": {
    eyebrow: "Template Production",
    title: "模板量产",
    description: "按固定业务模板组织素材与文案，使用 Edge-TTS 和 FFmpeg 批量生成短视频。",
    badge: "本地批量生成",
    badgeIcon: "template",
  },
  settings: {
    eyebrow: "Settings",
    title: "系统设置",
    description: "管理当前用户的 RunningHub 和 LLM 服务配置。",
    badge: "配置",
    badgeIcon: "serverCog",
  },
  users: {
    eyebrow: "Admin",
    title: "用户管理",
    description: "查看账号列表，并为忘记密码的用户重置登录密码。",
    badge: "管理员",
    badgeIcon: "shield",
  },
};

function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const isRegister = mode === "register";
  const title = isRegister ? "注册账号" : "登录账号";
  const actionLabel = isRegister ? "注册并登录" : "登录";

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
          ? await register(username.trim(), password, displayName)
          : await login(username.trim(), password);
        onAuthenticated(data.user);
      } catch (err) {
        setError(err.message || `${actionLabel}失败`);
      } finally {
        setSubmitting(false);
      }
    },
    [actionLabel, displayName, isRegister, onAuthenticated, password, passwordConfirm, username]
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
            <p className="eyebrow">Video Factory</p>
            <h1 id="auth-title">{title}</h1>
          </div>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="field" htmlFor="auth-username">
            <span className="field-label">用户名</span>
            <input
              id="auth-username"
              className="control"
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              placeholder="3-32 位英文、数字或下划线"
              required
            />
          </label>

          {isRegister && (
            <label className="field" htmlFor="auth-display-name">
              <span className="field-label">显示名称</span>
              <input
                id="auth-display-name"
                className="control"
                type="text"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                autoComplete="name"
                placeholder="可选"
              />
            </label>
          )}

          <label className="field" htmlFor="auth-password">
            <span className="field-label">密码</span>
            <input
              id="auth-password"
              className="control"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={isRegister ? "new-password" : "current-password"}
              placeholder="至少 8 位"
              required
            />
          </label>

          {isRegister && (
            <label className="field" htmlFor="auth-password-confirm">
              <span className="field-label">确认密码</span>
              <input
                id="auth-password-confirm"
                className="control"
                type="password"
                value={passwordConfirm}
                onChange={(event) => setPasswordConfirm(event.target.value)}
                autoComplete="new-password"
                placeholder="再次输入密码"
                required
              />
            </label>
          )}

          {error && <div className="form-alert failed">{error}</div>}

          <button className="primary-action auth-submit" type="submit" disabled={submitting}>
            <Icon name={submitting ? "loading" : isRegister ? "check" : "lock"} size={16} />
            {submitting ? "处理中..." : actionLabel}
          </button>
        </form>

        <button className="text-button auth-switch" type="button" onClick={switchMode}>
          {isRegister ? "已有账号，去登录" : "还没有账号，创建一个"}
        </button>
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
  const [activePage, setActivePage] = useState("digital-human");
  const [authChecking, setAuthChecking] = useState(true);
  const [currentUser, setCurrentUser] = useState(null);
  const [authError, setAuthError] = useState("");
  const visibleNavItems = useMemo(
    () => NAV_ITEMS.filter((item) => !item.adminOnly || currentUser?.is_admin),
    [currentUser]
  );
  const pageMeta = useMemo(() => PAGE_META[activePage], [activePage]);
  const handlePageChange = useCallback((pageId) => {
    setActivePage(pageId);
    window.scrollTo({ top: 0, left: 0 });
  }, []);

  useEffect(() => {
    let cancelled = false;

    getCurrentUser()
      .then((data) => {
        if (cancelled) return;
        setCurrentUser(data.authenticated ? data.user : null);
      })
      .catch((err) => {
        if (cancelled) return;
        setAuthError(err.message || "登录状态验证失败");
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

  const handleLogout = useCallback(async () => {
    setAuthError("");
    try {
      await logout();
    } catch (err) {
      setAuthError(err.message || "退出登录失败");
    } finally {
      setCurrentUser(null);
      setActivePage("digital-human");
    }
  }, []);

  if (authChecking) return <LoadingScreen />;

  if (!currentUser) {
    return (
      <>
        <AuthScreen onAuthenticated={setCurrentUser} />
        {authError && <div className="auth-floating-error">{authError}</div>}
      </>
    );
  }

  return (
    <div className="app-layout">
      <aside className="app-sidebar" aria-label="主导航">
        <nav className="sidebar-nav">
          {visibleNavItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${activePage === item.id ? "is-active" : ""}`}
              onClick={() => handlePageChange(item.id)}
              aria-current={activePage === item.id ? "page" : undefined}
            >
              <span className="nav-icon">
                <Icon name={item.icon} size={24} />
              </span>
              <span className="nav-item-main">
                <strong>{item.label}</strong>
              </span>
            </button>
          ))}
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
            <span className={`sidebar-role ${currentUser.is_admin ? "admin" : ""}`}>
              <Icon name={currentUser.is_admin ? "shield" : "user"} size={14} />
              {currentUser.is_admin ? "管理员" : "普通账号"}
            </span>
            <button className="sidebar-logout" type="button" onClick={handleLogout}>
              <Icon name="logout" size={15} />
              退出
            </button>
          </div>
        </div>
      </aside>

      <main className="app-shell">
        <header className="app-header">
          <div>
            <p className="eyebrow">{pageMeta.eyebrow}</p>
            <h1>{pageMeta.title}</h1>
            <p className="app-description">{pageMeta.description}</p>
          </div>
          <div className="header-actions">
            <div className="header-badge">
              <Icon name={pageMeta.badgeIcon} size={15} />
              {pageMeta.badge}
            </div>
          </div>
        </header>

        {authError && <div className="form-alert failed auth-page-error">{authError}</div>}

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
          <div className={`settings-main page-panel ${activePage === "settings" ? "is-active" : ""}`}>
            <Settings />
          </div>
          <div className={`settings-main page-panel ${activePage === "users" ? "is-active" : ""}`}>
            <UserManagement currentUser={currentUser} />
          </div>
        </div>
      </main>
    </div>
  );
}
