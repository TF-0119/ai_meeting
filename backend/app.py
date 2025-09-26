from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
from settings import settings

app = FastAPI(title="Local LLM Gateway")

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

# === 追加: 会議サブプロセス起動API =========================================
from fastapi import BackgroundTasks
from pathlib import Path
import subprocess, shlex, re, time, threading
from typing import Optional, Dict

# プロセス管理用のレジストリ（メモリ保持）
_processes_lock = threading.Lock()
_processes: Dict[str, dict] = {}  # id -> {pid, cmd, outdir, started_at, topic, backend}

def _slugify(s: str, max_len: int = 60) -> str:
    """フォルダ名に使えるよう軽くサニタイズ"""
    s = s.strip()
    s = re.sub(r"[^\w\s\-\._]", "", s, flags=re.UNICODE)  # 記号除去
    s = re.sub(r"\s+", "_", s)
    return s[:max_len] or "topic"

class StartMeetingIn(BaseModel):
    topic: str = Field(..., min_length=1)
    precision: int = Field(5, ge=1, le=10)
    rounds: int = Field(4, ge=1, le=100)
    agents: str = Field("planner worker critic")
    backend: str = Field("ollama")  # "ollama" or "openai" など
    outdir: Optional[str] = None    # 明示指定したい場合。未指定なら自動で logs/<ts>_<slug> を作る

class StartMeetingOut(BaseModel):
    ok: bool
    id: str
    pid: int
    outdir: str
    cmd: str

@app.post("/meetings", response_model=StartMeetingOut)
def start_meeting(body: StartMeetingIn, bg: BackgroundTasks):
    # 出力先ディレクトリを決める（未指定なら自動）
    ts = time.strftime("%Y%m%d-%H%M%S")
    slug = _slugify(body.topic)
    outdir = Path(body.outdir) if body.outdir else Path("logs") / f"{ts}_{slug}"
    outdir.mkdir(parents=True, exist_ok=True)

    # Windowsでも動くようにリストでコマンドを作る
    cmd_list = [
        "python", "backend/ai_meeting.py",
        "--topic", body.topic,
        "--precision", str(body.precision),
        "--rounds", str(body.rounds),
        "--agents", body.agents,
        "--backend", body.backend,
        "--outdir", str(outdir),
    ]
    # 表示用のコマンド（ログやデバッグに便利）
    cmd_str = " ".join(shlex.quote(c) for c in cmd_list)

    # バックグラウンドで起動（レスポンスは即返す）
    proc = subprocess.Popen(
        cmd_list,
        stdout=subprocess.DEVNULL,  # ここで捨てる。必要なら outdir / "stdout.txt" にリダイレクトも可
        stderr=subprocess.DEVNULL,
        cwd=Path(__file__).resolve().parent.parent,  # リポジトリ直下想定
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
            "backend": body.backend,
        }

    return StartMeetingOut(ok=True, id=meeting_id, pid=proc.pid, outdir=str(outdir), cmd=cmd_str)

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
