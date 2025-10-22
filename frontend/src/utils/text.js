// frontend/src/utils/text.js

/**
 * 話者名などからイニシャルを生成するヘルパー。
 * @param {string|null|undefined} name 入力名。
 * @returns {string} 2文字以内のイニシャル。生成できなければ "?"。
 */
export function createInitials(name) {
  if (!name || typeof name !== "string") return "?";
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const tokens = trimmed.split(/\s+/u).filter(Boolean);
  if (tokens.length === 0) return trimmed.charAt(0).toUpperCase();
  const letters = tokens.length === 1
    ? [tokens[0].charAt(0)]
    : [tokens[0].charAt(0), tokens[tokens.length - 1].charAt(0)];
  const joined = letters.join("").trim();
  if (!joined) return trimmed.charAt(0).toUpperCase();
  return joined.toUpperCase().slice(0, 2);
}

export default {
  createInitials,
};
