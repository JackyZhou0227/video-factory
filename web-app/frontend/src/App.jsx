import { useMemo, useState } from "react";
import DigitalHuman from "./components/DigitalHuman";
import Settings from "./components/Settings";

const NAV_ITEMS = [
  {
    id: "digital-human",
    label: "数字人",
    description: "口播视频生成",
  },
  {
    id: "settings",
    label: "设置",
    description: "RunningHub 配置",
  },
];

const PAGE_META = {
  "digital-human": {
    eyebrow: "Video Factory",
    title: "数字人口播视频",
    description:
      "上传人物形象，输入口播文案或音频，一站式生成数字人口播视频。",
    badge: "本地工作台",
  },
  settings: {
    eyebrow: "Settings",
    title: "系统设置",
    description:
      "配置 RunningHub API Key，视频生成工作流会使用这里保存的云端凭据。",
    badge: "持久化配置",
  },
};

export default function App() {
  const [activePage, setActivePage] = useState("digital-human");
  const pageMeta = useMemo(() => PAGE_META[activePage], [activePage]);

  return (
    <div className="app-layout">
      <aside className="app-sidebar" aria-label="主导航">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">
            VF
          </div>
          <div>
            <strong>Video Factory</strong>
            <span>AI 视频工厂</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item ${activePage === item.id ? "is-active" : ""}`}
              onClick={() => setActivePage(item.id)}
              aria-current={activePage === item.id ? "page" : undefined}
            >
              <span className="nav-item-main">
                <strong>{item.label}</strong>
                <span>{item.description}</span>
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
          <div className="header-badge">
            <span className="badge-dot" />
            {pageMeta.badge}
          </div>
        </header>

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
