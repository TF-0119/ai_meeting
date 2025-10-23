from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from backend.settings import settings
from backend.defaults import DEFAULT_AGENT_STRING, DEFAULT_AGENT_NAMES
from pathlib import Path
from typing import Optional, Dict, List, Union, Any, Tuple
from urllib.parse import urlparse, quote
from uuid import uuid4
import psutil
import httpx, sys, os
import subprocess, shlex, re, time, threading
import json

app = FastAPI(title="Local LLM Gateway")

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
app.mount("/logs", StaticFiles(directory=str(LOGS_DIR)), name="logs")

_TIMESTAMP_PREFIX_RE = re.compile(r"^([0-9]{8}-[0-9]{6})")

# ローカルのフロントエンドだけ許可（公開しない前提）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.get(f"{settings.OLLAMA_URL}/api/tags")
        r.raise_for_status()
    return {"ok": True}

@app.get("/models")
async def models():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{settings.OLLAMA_URL}/api/tags")
        r.raise_for_status()
        return r.json()

# プロセス管理用のレジストリ（メモリ保持）
_processes_lock = threading.Lock()
_processes: Dict[str, dict] = {}  # id -> {pid, cmd, outdir, started_at, topic, backend}


def _derive_log_id(raw_outdir: Any) -> Optional[str]:
    """outdir から logs/ 配下の相対パスを抽出し URL 用の文字列へ整形する。"""

    if not raw_outdir:
        return None

    try:
        out_path = Path(raw_outdir)
    except (TypeError, ValueError):
        return None

    try:
        logs_root_resolved = LOGS_DIR.resolve()
    except OSError:
        logs_root_resolved = LOGS_DIR

    try:
        out_resolved = out_path.resolve()
    except OSError:
        out_resolved = out_path

    relative: Optional[Path] = None
    for candidate, base in ((out_resolved, logs_root_resolved), (out_path, LOGS_DIR)):
        try:
            relative = candidate.relative_to(base)
        except ValueError:
            continue
        else:
            break

    if relative is None or not relative.parts:
        fallback = out_path.name or str(out_path).strip()
        if not fallback or fallback in {".", ".."}:
            return None
        return quote(fallback, safe="~@-_.")

    cleaned_parts = []
    for part in relative.parts:
        if part in ("", ".", ".."):
            continue
        cleaned_parts.append(quote(part, safe="~@-_."))

    if not cleaned_parts:
        return None

    return "/".join(cleaned_parts)

def _slugify(s: str, max_len: int = 60) -> str:
    """フォルダ名に使えるよう軽くサニタイズ"""
    s = s.strip()
    s = re.sub(r"[^\w\s\-\._]", "", s, flags=re.UNICODE)  # 記号除去
    s = re.sub(r"\s+", "_", s)
    return s[:max_len] or "topic"

def _first_non_none(*values: Any) -> Any:
    """None 以外かつ実質的な値を先頭から返すユーティリティ。"""

    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            return stripped
        return value
    return None


def _ensure_int(value: Any, field_name: str, *, minimum: int = 0, maximum: Optional[int] = None) -> int:
    """値が整数かつ指定レンジに収まるか検証し、問題なければ int を返す。"""

    try:
        number = int(value)
    except (TypeError, ValueError) as exc:  # noqa: PERF203 - 詳細なエラーを優先
        raise HTTPException(status_code=400, detail=f"{field_name} は整数で指定してください。") from exc

    if number < minimum:
        raise HTTPException(status_code=400, detail=f"{field_name} は {minimum} 以上で指定してください。")
    if maximum is not None and number > maximum:
        raise HTTPException(status_code=400, detail=f"{field_name} は {maximum} 以下で指定してください。")
    return number


def _ensure_int_string(value: Any, field_name: str, *, minimum: int = 0, maximum: Optional[int] = None) -> str:
    """_ensure_int のラッパー。CLI 渡し用に文字列へ変換する。"""

    return str(_ensure_int(value, field_name, minimum=minimum, maximum=maximum))


def _create_unique_outdir(base: Path) -> Path:
    """既存と衝突しない outdir を作成して返す。"""

    candidate = base
    counter = 1

    while True:
        try:
            candidate.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            if counter <= 99:
                candidate = base.parent / f"{base.name}-{counter:02d}"
                counter += 1
            else:
                candidate = base.parent / f"{base.name}-{uuid4().hex[:8]}"
                counter = 1
        else:
            return candidate.resolve()


class StartMeetingLLMOptions(BaseModel):
    """LLMに関するオプションのサブモデル。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    llm_backend: Optional[str] = Field(default=None, alias="llmBackend")
    backend: Optional[str] = None
    ollama_model: Optional[str] = Field(default=None, alias="ollamaModel")
    openai_model: Optional[str] = Field(default=None, alias="openaiModel")
    model: Optional[str] = None


PhaseTurnLimitType = Optional[
    Union[
        int,
        str,
        List[Union[int, str]],
        Dict[str, Union[int, str]],
    ]
]


class StartMeetingFlowOptions(BaseModel):
    """フェーズ制御に関するオプション。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    phase_turn_limit: PhaseTurnLimitType = Field(default=None, alias="phaseTurnLimit")
    phase_goal: Optional[Union[str, List[str], Dict[str, str]]] = Field(
        default=None, alias="phaseGoal"
    )
    max_phases: Optional[int] = Field(default=None, alias="maxPhases")


class StartMeetingChatOptions(BaseModel):
    """チャット（短文応答）関連のオプション。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    chat_mode: Optional[bool] = Field(default=None, alias="chatMode")
    chat_max_sentences: Optional[int] = Field(default=None, alias="chatMaxSentences")
    chat_max_chars: Optional[int] = Field(default=None, alias="chatMaxChars")
    chat_window: Optional[int] = Field(default=None, alias="chatWindow")


class StartMeetingMemoryOptions(BaseModel):
    """エージェントメモリ関連のオプション。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    agent_memory_limit: Optional[int] = Field(default=None, alias="agentMemoryLimit")
    agent_memory_window: Optional[int] = Field(default=None, alias="agentMemoryWindow")


class StartMeetingOptions(BaseModel):
    """階層化された各種オプション。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    llm: Optional[StartMeetingLLMOptions] = None
    flow: Optional[StartMeetingFlowOptions] = None
    chat: Optional[StartMeetingChatOptions] = None
    memory: Optional[StartMeetingMemoryOptions] = None
    llm_backend: Optional[str] = Field(default=None, alias="llmBackend")
    backend: Optional[str] = None
    model: Optional[str] = None


def _phase_turn_limit_tokens(value: PhaseTurnLimitType) -> List[str]:
    """phase_turn_limit を CLI トークン列へ変換する。"""

    if value is None:
        return []

    tokens: List[str] = []

    if isinstance(value, dict):
        for key, raw in value.items():
            if raw is None:
                continue
            name = str(key).strip()
            if not name:
                raise HTTPException(status_code=400, detail="phaseTurnLimit のキーが空です。")
            tokens.append(f"{name}={_ensure_int_string(raw, 'phaseTurnLimit', minimum=0)}")
        return tokens

    if isinstance(value, (list, tuple, set)):
        for item in value:
            tokens.extend(_phase_turn_limit_tokens(item))
        return tokens

    if isinstance(value, int):
        tokens.append(_ensure_int_string(value, "phaseTurnLimit", minimum=0))
        return tokens

    if isinstance(value, str):
        token = value.strip()
        if not token:
            return []
        if "=" in token:
            key, raw = token.split("=", 1)
            key = key.strip()
            if not key:
                raise HTTPException(status_code=400, detail="phaseTurnLimit のキーが空です。")
            tokens.append(f"{key}={_ensure_int_string(raw, 'phaseTurnLimit', minimum=0)}")
        else:
            tokens.append(_ensure_int_string(token, "phaseTurnLimit", minimum=0))
        return tokens

    raise HTTPException(status_code=400, detail="phaseTurnLimit の形式が不正です。")


def _phase_goal_tokens(value: Optional[Union[str, List[str], Dict[str, str]]]) -> List[str]:
    """phase_goal を CLI トークン列へ変換する。"""

    if value is None:
        return []

    tokens: List[str] = []

    if isinstance(value, dict):
        for key, raw in value.items():
            if raw is None:
                continue
            key_str = str(key).strip()
            text = str(raw).strip()
            if not key_str or not text:
                continue
            tokens.append(f"{key_str}={text}")
        return tokens

    if isinstance(value, (list, tuple, set)):
        for item in value:
            tokens.extend(_phase_goal_tokens(item))
        return tokens

    text = str(value).strip()
    if text:
        tokens.append(text)
    return tokens


def _build_cli_command(
    body: "StartMeetingIn",
    outdir: Path,
    normalized_ollama_url: str,
) -> tuple[List[str], str]:
    """StartMeetingIn から CLI コマンドリストとバックエンド種別を生成する。"""

    agents = shlex.split(body.agents)
    if not agents:
        raise HTTPException(status_code=400, detail="agents must not be empty")

    validated_agents: List[str] = []
    for token in agents:
        if token is None:
            continue
        value = token.strip()
        if not value:
            raise HTTPException(status_code=400, detail="agent names must not be empty")
        name_part = value.split("=", 1)[0].strip()
        if not name_part:
            raise HTTPException(status_code=400, detail="agent names must not be empty")
        validated_agents.append(value)

    agents = validated_agents

    options = body.options or StartMeetingOptions()
    llm_from_options = options.llm
    llm_from_body = body.llm

    selected_backend = _first_non_none(
        llm_from_options.llm_backend if llm_from_options else None,
        llm_from_options.backend if llm_from_options else None,
        options.llm_backend,
        options.backend,
        llm_from_body.llm_backend,
        getattr(llm_from_body, "backend", None),
        body.backend,
    ) or "ollama"

    ollama_model = _first_non_none(
        llm_from_options.ollama_model if llm_from_options else None,
        llm_from_options.model if llm_from_options and selected_backend == "ollama" else None,
        options.model if selected_backend == "ollama" else None,
        llm_from_body.ollama_model,
        llm_from_body.model if selected_backend == "ollama" else None,
    )
    openai_model = _first_non_none(
        llm_from_options.openai_model if llm_from_options else None,
        llm_from_options.model if llm_from_options and selected_backend == "openai" else None,
        options.model if selected_backend == "openai" else None,
        llm_from_body.openai_model,
        llm_from_body.model if selected_backend == "openai" else None,
    )

    py = sys.executable
    cmd_list: List[str] = [
        py,
        "-u",
        "-m",
        "backend.ai_meeting",
        "--topic",
        body.topic,
        "--precision",
        str(body.precision),
        "--agents",
        *agents,
    ]

    if body.rounds is not None:
        cmd_list.extend(["--rounds", str(body.rounds)])

    if selected_backend:
        cmd_list.extend(["--backend", selected_backend])
    if ollama_model:
        cmd_list.extend(["--ollama-model", ollama_model])
    if openai_model:
        cmd_list.extend(["--openai-model", openai_model])

    cmd_list.extend(["--outdir", str(outdir)])
    if selected_backend == "ollama":
        cmd_list.extend(["--ollama-url", normalized_ollama_url])

    flow_options = options.flow
    if flow_options:
        for token in _phase_turn_limit_tokens(flow_options.phase_turn_limit):
            cmd_list.extend(["--phase-turn-limit", token])
        for token in _phase_goal_tokens(flow_options.phase_goal):
            cmd_list.extend(["--phase-goal", token])
        if flow_options.max_phases is not None:
            max_phases = _ensure_int(flow_options.max_phases, "maxPhases", minimum=1)
            cmd_list.extend(["--max-phases", str(max_phases)])

    chat_options = options.chat
    if chat_options:
        if chat_options.chat_mode is False:
            cmd_list.append("--no-chat-mode")
        if chat_options.chat_mode is True:
            # 明示的に True が指定されても既定値と同じなのでフラグ不要
            pass
        if chat_options.chat_max_sentences is not None:
            max_sentences = _ensure_int(
                chat_options.chat_max_sentences,
                "chatMaxSentences",
                minimum=1,
                maximum=10,
            )
            cmd_list.extend(["--chat-max-sentences", str(max_sentences)])
        if chat_options.chat_max_chars is not None:
            max_chars = _ensure_int(chat_options.chat_max_chars, "chatMaxChars", minimum=1)
            cmd_list.extend(["--chat-max-chars", str(max_chars)])
        if chat_options.chat_window is not None:
            window = _ensure_int(chat_options.chat_window, "chatWindow", minimum=1)
            cmd_list.extend(["--chat-window", str(window)])

    memory_options = options.memory
    if memory_options:
        if memory_options.agent_memory_limit is not None:
            limit = _ensure_int(memory_options.agent_memory_limit, "agentMemoryLimit", minimum=0)
            cmd_list.extend(["--agent-memory-limit", str(limit)])
        if memory_options.agent_memory_window is not None:
            window = _ensure_int(memory_options.agent_memory_window, "agentMemoryWindow", minimum=0)
            cmd_list.extend(["--agent-memory-window", str(window)])

    return cmd_list, selected_backend


class StartMeetingIn(BaseModel):
    """会議起動リクエスト本体。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    topic: str = Field(..., min_length=1)
    precision: int = Field(5, ge=1, le=10)
    rounds: Optional[int] = Field(default=None, ge=1, le=100)
    agents: str = Field(DEFAULT_AGENT_STRING)
    backend: str = Field("ollama")  # "ollama" or "openai" など
    outdir: Optional[str] = None    # 明示指定したい場合。未指定なら自動で logs/<ts>_<slug> を作る
    llm: StartMeetingLLMOptions = Field(default_factory=StartMeetingLLMOptions)
    options: Optional[StartMeetingOptions] = None

class StartMeetingOut(BaseModel):
    ok: bool
    id: str
    pid: int
    outdir: str
    cmd: str
    log_id: Optional[str] = None

@app.post("/meetings", response_model=StartMeetingOut)
def start_meeting(body: StartMeetingIn, bg: BackgroundTasks):
    # ルート/ログパスを絶対パス化
    REPO_ROOT = Path(__file__).resolve().parent.parent
    LOGS_ROOT = REPO_ROOT / "logs"

    parsed_ollama = urlparse(settings.OLLAMA_URL)
    if not parsed_ollama.scheme or not parsed_ollama.hostname:
        raise HTTPException(status_code=500, detail="Invalid OLLAMA_URL in settings")
    ollama_port = parsed_ollama.port
    if ollama_port is None:
        ollama_port = 443 if parsed_ollama.scheme == "https" else 80
    normalized_ollama_url = f"{parsed_ollama.scheme}://{parsed_ollama.hostname}:{ollama_port}"

    ts = time.strftime("%Y%m%d-%H%M%S")
    slug = _slugify(body.topic)
    base_outdir = Path(body.outdir) if body.outdir else LOGS_ROOT / f"{ts}_{slug}"
    outdir = _create_unique_outdir(base_outdir)

    # 404防止のプレースホルダーを先に作る
    (outdir / "meeting_live.jsonl").touch()
    (outdir / "meeting_result.json").touch()

    # プロセス出力をファイルへ（デバッグ必須）
    stdout_f = open(outdir / "backend_stdout.log", "a", encoding="utf-8")
    stderr_f = open(outdir / "backend_stderr.log", "a", encoding="utf-8")

    cmd_list, selected_backend = _build_cli_command(body, outdir, normalized_ollama_url)
    cmd_str = " ".join(shlex.quote(c) for c in cmd_list)

    # 起動
    child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if selected_backend == "ollama":
        child_env["OLLAMA_URL"] = normalized_ollama_url
    proc = subprocess.Popen(
        cmd_list,
        stdout=stdout_f,
        stderr=stderr_f,
        cwd=str(REPO_ROOT),
        env=child_env,
        creationflags=0  # Windows なら CREATE_NO_WINDOW なども可
    )

    meeting_id = f"{ts}_{proc.pid}"
    log_id = _derive_log_id(outdir)

    with _processes_lock:
        _processes[meeting_id] = {
            "pid": proc.pid,
            "cmd": cmd_str,
            "outdir": str(outdir),
            "started_at": ts,
            "topic": body.topic,
            "backend": selected_backend,
            "log_id": log_id,
        }

    return StartMeetingOut(
        ok=True, id=meeting_id, pid=proc.pid,
        outdir=str(outdir.relative_to(LOGS_DIR.parent)) if str(outdir).startswith(str(LOGS_DIR)) else str(outdir),
        cmd=cmd_str,
        log_id=log_id,
    )

# 会議一覧
@app.get("/meetings")
def list_meetings():
    with _processes_lock:
        items = []
        for meeting_id, info in _processes.items():
            log_id = info.get("log_id") or _derive_log_id(info.get("outdir"))
            if log_id and info.get("log_id") != log_id:
                info["log_id"] = log_id
            entry = {"id": meeting_id, **info}
            entry["log_id"] = log_id
            items.append(entry)
        return {"items": items}

# meeting_result.json の有効性を確認するヘルパー
def _has_valid_meeting_result(path: Path) -> bool:
    """meeting_result.json が空ファイル・不正ファイルではないか判定する。"""

    if not path.exists() or not path.is_file():
        return False

    try:
        if path.stat().st_size <= 0:
            return False
    except OSError:
        return False

    try:
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return False

    if not isinstance(data, dict):
        return False

    final_text = data.get("final")
    if isinstance(final_text, str) and final_text.strip():
        return True

    turns = data.get("turns")
    if isinstance(turns, list) and turns:
        return True

    phases = data.get("phases")
    if isinstance(phases, list) and phases:
        return True

    kpi = data.get("kpi")
    if isinstance(kpi, dict) and kpi:
        return True

    return False


def _extract_started_at_from_payload(payload: Dict[str, Any], directory_name: str) -> str:
    """結果JSONやディレクトリ名から開始時刻を推測する。"""

    if not isinstance(payload, dict):
        return ""

    candidates: List[str] = []
    for key in ("started_at", "startedAt", "start_time", "startTime"):
        raw = payload.get(key)
        if isinstance(raw, str) and raw.strip():
            candidates.append(raw.strip())

    for container_key in ("meta", "metadata", "info", "meeting"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("started_at", "startedAt", "start_time", "startTime"):
            raw = container.get(key)
            if isinstance(raw, str) and raw.strip():
                candidates.append(raw.strip())

    if candidates:
        return candidates[0]

    match = _TIMESTAMP_PREFIX_RE.match(directory_name)
    if match:
        return match.group(1)

    return ""


def _collect_result_entry(log_dir: Path) -> Optional[Tuple[Tuple[int, str, float, str], Dict[str, Any]]]:
    """単一ディレクトリから結果API用のエントリを生成する。"""

    result_path = log_dir / "meeting_result.json"
    if not _has_valid_meeting_result(result_path):
        return None

    try:
        with result_path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    topic_raw = payload.get("topic")
    topic = topic_raw.strip() if isinstance(topic_raw, str) else ""

    final_raw = payload.get("final")
    final_text = final_raw.strip() if isinstance(final_raw, str) else ""

    started_at = _extract_started_at_from_payload(payload, log_dir.name)

    try:
        mtime = result_path.stat().st_mtime
    except OSError:
        mtime = 0.0

    sort_key = (
        1 if started_at else 0,
        started_at,
        mtime,
        log_dir.name,
    )

    item = {
        "meeting_id": log_dir.name,
        "topic": topic,
        "started_at": started_at,
        "final": final_text,
    }

    return sort_key, item


@app.get("/results")
def list_results():
    """logs ディレクトリを走査して会議結果の一覧を返す。"""

    try:
        log_dirs = [path for path in LOGS_DIR.iterdir() if path.is_dir()]
    except OSError:
        log_dirs = []

    entries: List[Tuple[Tuple[int, str, float, str], Dict[str, Any]]] = []
    for log_dir in log_dirs:
        collected = _collect_result_entry(log_dir)
        if collected is None:
            continue
        entries.append(collected)

    entries.sort(key=lambda item: item[0], reverse=True)
    return {"items": [item for _, item in entries]}


# 単体の状態（超シンプル版）
@app.get("/meetings/{mid}")
def meeting_status(mid: str):
    with _processes_lock:
        info = _processes.get(mid)
        log_id = None
        if info:
            log_id = info.get("log_id") or _derive_log_id(info.get("outdir"))
            if log_id and info.get("log_id") != log_id:
                info["log_id"] = log_id
    if not info:
        return {"ok": False, "error": "NOT_FOUND"}

    # プロセスの生存確認
    is_alive = psutil.pid_exists(info["pid"])

    # 最低限: 代表ファイルの存在で進捗を推測
    outdir = Path(info["outdir"])
    live = outdir / "meeting_live.jsonl"
    result = outdir / "meeting_result.json"
    exists_live = live.exists()
    exists_result = _has_valid_meeting_result(result)
    return {
        "ok": True,
        "id": mid,
        "pid": info["pid"],
        "is_alive": is_alive,
        "outdir": info["outdir"],
        "log_id": log_id,
        "topic": info["topic"],
        "backend": info["backend"],
        "has_live": exists_live,
        "has_result": exists_result,
    }

# liveログの最新N行を返す（フロントのポーリング用）
class TailOut(BaseModel):
    ok: bool
    lines: list[str]
    size: int

@app.get("/meetings/{mid}/live", response_model=TailOut)
def meeting_live(mid: str, n: int = 100):
    with _processes_lock:
        info = _processes.get(mid)
    if not info:
        return TailOut(ok=False, lines=[], size=0)

    path = Path(info["outdir"]) / "meeting_live.jsonl"
    if not path.exists():
        return TailOut(ok=True, lines=[], size=0)
    # ざっくりテール（行数が多い時の負荷を抑える）
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    tail = lines[-n:] if len(lines) > n else lines
    return TailOut(ok=True, lines=tail, size=len(lines))

# 要求があれば停止API（Windowsでも動くように taskkill / pid に切り替え可）
@app.post("/meetings/{mid}/stop")
def stop_meeting(mid: str):
    with _processes_lock:
        info = _processes.get(mid)
    if not info:
        raise HTTPException(status_code=404, detail="指定された会議が見つかりません。")

    pid = info["pid"]
    try:
        # POSIX: SIGTERM。Windowsは subprocess.Popen 参照が無いので taskkill を使う手も
        import signal, os
        os.kill(pid, signal.SIGTERM)
        return {"ok": True, "pid": pid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会議の停止に失敗しました: {e}") from e
