import { useCallback, useEffect, useMemo, useState } from "react";
import Icon from "./components/Icon";
import DigitalHuman from "./components/DigitalHuman";
import Settings from "./components/Settings";
import { getCurrentUser, login, logout, register } from "./lib/auth";

const NAV_ITEMS = [
  {
    id: "digital-human",
    label: "数字人",
    description: "口播视频生成",
    icon: "digitalHuman",
  },
  {
    id: "settings",
    label: "设置",
    description: "RunningHub 配置",
    icon: "settings",
  },
];

const PAGE_META = {
  "digital-human": {
    eyebrow: "Video Factory",
    title: "数字人口播视频",
    description: "上传人物形象，输入口播文案或音频，一站式生成数字人口播视频。",
    badge: "本地工作台",
    badgeIcon: "monitorCog",
  },
  settings: {
    eyebrow: "Settings",
    title: "系统设置",
    description: "配置当前用户的 RunningHub API Key，数字人工作流由系统固定。",
    badge: "本机配置",
    badgeIcon: "serverCog",
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
  const title = isRegister ? "注册本机账号" : "登录本机账号";
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
  const pageMeta = useMemo(() => PAGE_META[activePage], [activePage]);

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
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${activePage === item.id ? "is-active" : ""}`}
              onClick={() => setActivePage(item.id)}
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
            <div className="user-chip">
              <Icon name="user" size={15} />
              <span>{currentUser.display_name || currentUser.username}</span>
            </div>
            <button className="icon-button" type="button" aria-label="退出登录" onClick={handleLogout}>
              <Icon name="logout" size={17} />
            </button>
          </div>
        </header>

        {authError && <div className="form-alert failed auth-page-error">{authError}</div>}

        <div className="page-stack">
          <div className={`app-main page-panel ${activePage === "digital-human" ? "is-active" : ""}`}>
            <DigitalHuman />
          </div>
          <div className={`settings-main page-panel ${activePage === "settings" ? "is-active" : ""}`}>
            <Settings />
          </div>
        </div>
      </main>
    </div>
  );
}
