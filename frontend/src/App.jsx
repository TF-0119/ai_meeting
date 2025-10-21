import React, { useEffect, useMemo, useState } from "react";
import { Routes, Route, NavLink, Navigate, useLocation } from "react-router-dom";
import Home from "./pages/Home.jsx";
import Meeting from "./pages/Meeting.jsx";
import Result from "./pages/Result.jsx";
import Ongoing from "./pages/Ongoing.jsx";
import ResultsList from "./pages/ResultsList.jsx";
import Settings from "./pages/Settings.jsx";
import { getHealth } from "./services/api.js";
import { loadHomePreset } from "./services/presets.js";
import ThemeToggle from "./components/ThemeToggle.jsx";

const NAV_TABS = [
  { to: "/ongoing", label: "進行中" },
  { to: "/results", label: "結果一覧" },
  { to: "/settings", label: "設定" },
];

function NavigationLinks({ onNavigate }) {
  return (
    <div className="navigation">
      <NavLink
        to="/meetings/new"
        className={({ isActive }) => `nav-primary-link${isActive ? " is-active" : ""}`}
        onClick={onNavigate}
      >
        新規会議
      </NavLink>
      <nav className="nav-tabs" aria-label="会議ナビゲーション">
        {NAV_TABS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `nav-tab${isActive ? " is-active" : ""}`}
            onClick={onNavigate}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function StatusIndicator({ health, backendPreference, openaiConfigured }) {
  const variant = health.status === "loading" ? "loading" : health.ok ? "ok" : "error";
  const backendLabel = backendPreference === "openai" ? "OpenAI" : "Ollama";
  const apiKeyLabel = openaiConfigured ? "API Key 設定済" : "API Key 未設定";
  let text = "接続確認中...";

  if (variant === "ok") {
    text = `${backendLabel} / ${apiKeyLabel}`;
  } else if (variant === "error") {
    text = health.message || "バックエンドに接続できません";
  }

  return (
    <div className="nav-status" role="status" aria-live="polite">
      <span className={`status-dot status-${variant}`} aria-hidden="true" />
      <span className="status-text">{text}</span>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [healthState, setHealthState] = useState({ status: "loading", ok: false, message: "" });
  const [backendPreference, setBackendPreference] = useState("ollama");
  const openaiConfigured = useMemo(() => Boolean(import.meta.env.VITE_OPENAI_API_KEY), []);

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    let active = true;
    (async () => {
      const result = await getHealth();
      if (!active) return;
      setHealthState(result);
    })();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const updatePreference = () => {
      const preset = loadHomePreset();
      const backend = preset?.form?.backend;
      if (backend === "openai" || backend === "ollama") {
        setBackendPreference(backend);
      }
    };

    updatePreference();

    if (typeof window !== "undefined") {
      window.addEventListener("focus", updatePreference);
      const intervalId = window.setInterval(updatePreference, 10000);
      return () => {
        window.removeEventListener("focus", updatePreference);
        window.clearInterval(intervalId);
      };
    }
    return undefined;
  }, []);

  return (
    <div className="app">
      <header className={`app-header${menuOpen ? " is-open" : ""}`}>
        <div className="header-inner">
          <div className="brand-area">
            <button
              type="button"
              className="nav-toggle"
              aria-label={menuOpen ? "ナビゲーションを閉じる" : "ナビゲーションを開く"}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((prev) => !prev)}
            >
              <span className="nav-toggle-bar" aria-hidden="true" />
              <span className="nav-toggle-bar" aria-hidden="true" />
              <span className="nav-toggle-bar" aria-hidden="true" />
            </button>
            <span className="brand-title">AI Meeting</span>
          </div>
          <div className="nav-inline">
            <NavigationLinks onNavigate={() => setMenuOpen(false)} />
          </div>
          <div className="header-actions">
            <ThemeToggle />
            <StatusIndicator
              health={healthState}
              backendPreference={backendPreference}
              openaiConfigured={openaiConfigured}
            />
          </div>
        </div>
        <div className="nav-drawer">
          <div className="nav-drawer-content">
            <NavigationLinks onNavigate={() => setMenuOpen(false)} />
          </div>
        </div>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/meetings/new" replace />} />
          <Route path="/meetings/new" element={<Home />} />
          <Route path="/ongoing" element={<Ongoing />} />
          <Route path="/results" element={<ResultsList />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/meeting/:id" element={<Meeting />} />
          <Route path="/result/:id" element={<Result />} />
        </Routes>
      </main>
    </div>
  );
}
