// frontend/src/services/presets.js
// 会議作成フォームのプリセットをローカルストレージへ保存・取得するユーティリティ。

const STORAGE_KEY = "ai-meeting:preset:v1";

function isBrowserStorageAvailable() {
  try {
    return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
  } catch (err) {
    return false;
  }
}

function safeParse(jsonText) {
  try {
    return JSON.parse(jsonText);
  } catch (err) {
    return null;
  }
}

export function loadHomePreset() {
  if (!isBrowserStorageAvailable()) return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  const data = safeParse(raw);
  if (!data || typeof data !== "object") return null;
  return data;
}

export function saveHomePreset(preset) {
  if (!isBrowserStorageAvailable()) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preset));
  } catch (err) {
    // 保存に失敗してもアプリの動作には影響させない
  }
}

export function clearHomePreset() {
  if (!isBrowserStorageAvailable()) return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch (err) {
    // noop
  }
}
