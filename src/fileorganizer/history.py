import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

HISTORY_FILE = Path.home() / ".file_organizer_history.json"


def load() -> List[Dict]:
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f).get("moves", [])
    except Exception:
        pass
    return []


def append_move(filename: str, source: str, destination: str, category: str):
    moves = load()
    moves.append({
        "ts":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fn":  filename,
        "src": source,
        "dst": destination,
        "cat": category,
    })
    if len(moves) > 2000:
        moves = moves[-2000:]
    _write(moves)


def _write(moves: list):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"moves": moves}, f, ensure_ascii=False)
    except Exception:
        pass


def clear():
    _write([])


def stats_by_category(moves: Optional[List[Dict]] = None) -> Dict[str, int]:
    if moves is None:
        moves = load()
    result: Dict[str, int] = {}
    for m in moves:
        cat = m.get("cat", "Otros")
        result[cat] = result.get(cat, 0) + 1
    return result


def stats_by_day(days: int = 7, moves: Optional[List[Dict]] = None) -> Dict[str, int]:
    if moves is None:
        moves = load()
    result: Dict[str, int] = {}
    for i in range(days, 0, -1):
        key = (datetime.now() - timedelta(days=i - 1)).strftime("%d/%m")
        result[key] = 0
    cutoff = datetime.now() - timedelta(days=days)
    for m in moves:
        try:
            ts = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S")
            if ts < cutoff:
                continue
            key = ts.strftime("%d/%m")
            if key in result:
                result[key] += 1
        except Exception:
            continue
    return result
