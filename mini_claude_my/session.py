from pathlib import Path
import json

SESSION_DIR = Path.cwd() / ".my_claude" / "sessions"


def _ensure_dir()->None:
   SESSION_DIR.mkdir(parents=True, exist_ok=True)

# 保存 session 会话
def save_session(session_id:str, data:dict) -> None:
   _ensure_dir()
   session_file = SESSION_DIR / f"{session_id}.json"
   session_file.write_text(json.dumps(data, indent=2, default=str))

# 罗列 session_id
def list_sessions() -> list[dict]:
   _ensure_dir()
   result = []
   sessions = SESSION_DIR.glob("*.json")
   for f in sessions:
      data = json.loads(f.read_text())
      # print(f"{f.name}:{data}")
      if "metadata" in data:
         result.append(data["metadata"])
   return result

def get_latest_session_id() -> str | None:
   sessions = list_sessions()
   if len(sessions) == 0:
       return None
   # 排序 reverse=True 降序排列
   sessions.sort(key = lambda s:s.get("startTime"),reverse=True)
   return sessions[0]["id"]


# 加载会话
def load_session(session_id) -> dict | None:
   session_file = Path(f"{SESSION_DIR}/{session_id}.json")
   data = json.loads(session_file.read_text())
   return data