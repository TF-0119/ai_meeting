"""テスト用の簡易OpenAI互換スタブ。実サービスへのアクセスなしで応答を生成する。"""
import json
import re
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


class _Response:
    def __init__(self, content: str):
        self.choices = [_Choice(_Message(content))]


class _ChatCompletions:
    """Chat Completions API の最小互換実装。"""

    def create(self, *, model: str, messages: List[Dict[str, Any]], temperature: float, max_tokens: int):
        # 実際のAPIでは model/temperature/max_tokens を使うが、スタブでは読みやすい応答を返すことを優先する。
        content = self._generate(messages)
        return _Response(content)

    def _generate(self, messages: List[Dict[str, Any]]) -> str:
        system_prompt = messages[0].get("content", "") if messages else ""
        prompt = messages[-1].get("content", "") if messages else ""
        topic = self._extract_topic(messages)

        if "JSON" in system_prompt.upper() or "JSON" in prompt.upper():
            return self._json_payload(prompt)
        if "議事要約" in system_prompt:
            return self._summarize_bullets(prompt)
        if "自己検証アシスタント" in system_prompt:
            return self._self_check(prompt)
        if "編集者" in system_prompt and "指摘" in prompt:
            return self._rewrite_with_feedback(prompt)
        if "議論の編集者" in system_prompt:
            return self._final_summary(topic)
        if "モデレーター" in system_prompt and "scores" in prompt:
            return self._equilibrium_scores(prompt)
        if "これは『内面の思考』" in system_prompt:
            return self._inner_thought(topic, prompt)
        if "会議参加者" in system_prompt:
            return self._chat_reply(topic, prompt)
        return self._fallback(topic)

    def _extract_topic(self, messages: List[Dict[str, Any]]) -> str:
        for msg in reversed(messages):
            text = msg.get("content") or ""
            m = re.search(r"Topic:?\s*(.+)", text)
            if m:
                return m.group(1).strip().splitlines()[0]
            m = re.search(r"テーマ[再掲]*:?\s*(.+)", text)
            if m:
                return m.group(1).strip().splitlines()[0]
        return "議題"

    def _json_payload(self, prompt: str) -> str:
        # 候補者名を抽出
        names = re.findall(r"^([A-Za-z0-9_\-一-龥ぁ-んァ-ン]+):", prompt, flags=re.MULTILINE)
        if not names:
            names = ["Alice", "Bob"]
        scores = {
            name: {
                "flow": 0.6 + 0.05 * idx,
                "goal": 0.6,
                "quality": 0.55 + 0.05 * (idx % 2),
                "novelty": 0.5,
                "action": 0.55,
                "score": 0.6 + 0.05 * idx,
                "rationale": "短い好評価"
            }
            for idx, name in enumerate(names)
        }
        winner = names[0]
        payload = {"scores": scores, "winner": winner, "rationale": "均衡チェック"}
        return json.dumps(payload, ensure_ascii=False)

    def _summarize_bullets(self, prompt: str) -> str:
        lines = [l.strip() for l in prompt.splitlines() if l.strip()]
        items = []
        for line in lines[:5]:
            items.append(f"- {line[:60]}")
        if not items:
            items.append("- 論点整理なし")
        return "\n".join(items)

    def _self_check(self, prompt: str) -> str:
        return "- 追加のデータ確認が必要\n- 関係者への共有と期日の明記"

    def _rewrite_with_feedback(self, prompt: str) -> str:
        # 「元:」「指摘:」の形式から元テキストを抽出して短く整形
        m = re.search(r"元:\n([\s\S]+?)\n\n指摘:", prompt)
        base = m.group(1).strip() if m else "対応内容を整理する"
        return f"{base}。修正案を明確化する。"

    def _final_summary(self, topic: str) -> str:
        return (
            f"合意事項:\n- {topic}に向けた初期対応を進める\n"
            "残課題:\n- 詳細な要件整理が未完了\n"
            "直近アクション:\n- 担当者が次回ミーティングまでに選択肢を比較"
        )

    def _equilibrium_scores(self, prompt: str) -> str:
        names = re.findall(r"- ([^:]+):", prompt)
        if not names:
            names = ["Alice", "Bob"]
        data = {name: 0.6 for name in names}
        return json.dumps({"scores": data, "rationale": "均衡評価スタブ"}, ensure_ascii=False)

    def _inner_thought(self, topic: str, prompt: str) -> str:
        return f"{topic}の実行案を具体化し、関係者調整を提案する。"

    def _chat_reply(self, topic: str, prompt: str) -> str:
        lines = [l.strip() for l in prompt.splitlines() if l.strip()]
        hint = lines[-1][:40] if lines else "進め方を検討"
        return f"{topic}を前進させるため、{hint}。"

    def _fallback(self, topic: str) -> str:
        return f"{topic}に対して簡易な次の手を共有する。"


class OpenAI:
    """`backend.ai_meeting` が利用する OpenAI クライアントのスタブ。"""

    def __init__(self, *args, **kwargs):
        self.chat = type("_Chat", (), {"completions": _ChatCompletions()})()
