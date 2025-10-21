import { useEffect, useState } from "react";
import Button from "./Button";
import {
  applyTheme,
  getStoredTheme,
  getSystemTheme,
  storeTheme,
  subscribeToSystemTheme,
} from "../theme";

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => getStoredTheme() ?? getSystemTheme());

  useEffect(() => {
    applyTheme(theme);
    storeTheme(theme);
  }, [theme]);

  useEffect(() => {
    return subscribeToSystemTheme((systemTheme) => {
      if (!getStoredTheme()) {
        setTheme(systemTheme);
      }
    });
  }, []);

  const isDark = theme === "dark";
  const nextTheme = isDark ? "light" : "dark";
  const label = isDark ? "ライトモードに切り替え" : "ダークモードに切り替え";

  return (
    <Button
      variant="ghost"
      className="ui-theme-toggle"
      onClick={() => setTheme(nextTheme)}
      aria-pressed={isDark}
      aria-label={label}
    >
      <span aria-hidden>{isDark ? "🌙" : "☀️"}</span>
      <span>{isDark ? "ダーク" : "ライト"}</span>
    </Button>
  );
}
