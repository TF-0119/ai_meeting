from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from backend.settings import settings
from backend.defaults import DEFAULT_AGENT_STRING, DEFAULT_AGENT_NAMES
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlparse
import psutil
import httpx, sys, os
import subprocess, shlex, re, time, threading

app = FastAPI(title="Local LLM Gateway")

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
app.mount("/logs", StaticFiles(directory=str(LOGS_DIR)), name="logs")

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

def _slugify(s: str, max_len: int = 60) -> str:
    """フォルダ名に使えるよう軽くサニタイズ"""
    s = s.strip()
    s = re.sub(r"[^\w\s\-\._]", "", s, flags=re.UNICODE)  # 記号除去
    s = re.sub(r"\s+", "_", s)
    return s[:max_len] or "topic"

class StartMeetingLLMOptions(BaseModel):
    llm_backend: Optional[str] = None
    ollama_model: Optional[str] = None
    openai_model: Optional[str] = None


class StartMeetingIn(BaseModel):
    topic: str = Field(..., min_length=1)
    precision: int = Field(5, ge=1, le=10)
    rounds: int = Field(4, ge=1, le=100)
    agents: str = Field(DEFAULT_AGENT_STRING)
    backend: str = Field("ollama")  # "ollama" or "openai" など
    outdir: Optional[str] = None    # 明示指定したい場合。未指定なら自動で logs/<ts>_<slug> を作る
    llm: StartMeetingLLMOptions = Field(default_factory=StartMeetingLLMOptions)

class StartMeetingOut(BaseModel):
    ok: bool
    id: str
    pid: int
    outdir: str
    cmd: str

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
    outdir = (Path(body.outdir) if body.outdir
              else LOGS_ROOT / f"{ts}_{slug}")
    outdir.mkdir(parents=True, exist_ok=True)

    # 404防止のプレースホルダーを先に作る
    (outdir / "meeting_live.jsonl").touch()
    (outdir / "meeting_result.json").touch()

    # プロセス出力をファイルへ（デバッグ必須）
    stdout_f = open(outdir / "backend_stdout.log", "a", encoding="utf-8")
    stderr_f = open(outdir / "backend_stderr.log", "a", encoding="utf-8")

    # “python” ではなく現在のPythonを使う（環境ズレ防止）
    py = sys.executable
    agents = shlex.split(body.agents)
    if not agents:
        raise HTTPException(status_code=400, detail="agents must not be empty")
    selected_backend = body.llm.llm_backend or body.backend
    cmd_list = [
        py, "-u", "-m", "backend.ai_meeting",
        "--topic", body.topic,
        "--precision", str(body.precision),
        "--rounds", str(body.rounds),
        "--agents", *agents,
    ]
    if selected_backend:
        cmd_list.extend(["--backend", selected_backend])
    if body.llm.ollama_model:
        cmd_list.extend(["--ollama-model", body.llm.ollama_model])
    if body.llm.openai_model:
        cmd_list.extend(["--openai-model", body.llm.openai_model])
    cmd_list.extend(["--outdir", str(outdir)])
    if selected_backend == "ollama":
        cmd_list.extend(["--ollama-url", normalized_ollama_url])
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
    with _processes_lock:
        _processes[meeting_id] = {
            "pid": proc.pid,
            "cmd": cmd_str,
            "outdir": str(outdir),
            "started_at": ts,
            "topic": body.topic,
            "backend": selected_backend,
        }

    return StartMeetingOut(
        ok=True, id=meeting_id, pid=proc.pid,
        outdir=str(outdir.relative_to(LOGS_DIR.parent)) if str(outdir).startswith(str(LOGS_DIR)) else str(outdir),
        cmd=cmd_str
    )

# 会議一覧
@app.get("/meetings")
def list_meetings():
    with _processes_lock:
        return {"items": [
            {"id": k, **v} for k, v in _processes.items()
        ]}

# 単体の状態（超シンプル版）
@app.get("/meetings/{mid}")
def meeting_status(mid: str):
    with _processes_lock:
        info = _processes.get(mid)
    if not info:
        return {"ok": False, "error": "NOT_FOUND"}

    # プロセスの生存確認
    is_alive = psutil.pid_exists(info["pid"])

    # 最低限: 代表ファイルの存在で進捗を推測
    outdir = Path(info["outdir"])
    live = outdir / "meeting_live.jsonl"
    result = outdir / "meeting_result.json"
    exists_live = live.exists()
    exists_result = result.exists()
    return {
        "ok": True,
        "id": mid,
        "pid": info["pid"],
        "is_alive": is_alive,
        "outdir": info["outdir"],
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
        return {"ok": False, "error": "NOT_FOUND"}

    pid = info["pid"]
    try:
        # POSIX: SIGTERM。Windowsは subprocess.Popen 参照が無いので taskkill を使う手も
        import signal, os
        os.kill(pid, signal.SIGTERM)
        return {"ok": True, "pid": pid}
    except Exception as e:
        return {"ok": False, "error": str(e)}
