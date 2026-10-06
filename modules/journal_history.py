"""
Чтение журналов игры за прошлые сессии (в том числе когда плагина ещё не было).

Поддерживает два режима чтения: полная история событий для восстановления
экспедиции и события после последней границы для расчёта текущих непроданных
биологических данных.
"""
import json
import re
from pathlib import Path
from typing import Iterable, List, Optional

from config import config as base_config
from modules.debug import debug

JOURNAL_RE = re.compile(r"^Journal\.\d{4}-\d{2}-\d{2}T\d{6}\.\d{2}\.log$")
DEFAULT_MAX_FILES = 300     # защита от чтения тысяч файлов, если границы нет вообще


def journal_dir() -> Optional[Path]:
    candidates = []
    try:
        custom = base_config.get_str("journaldir")
        if custom:
            candidates.append(Path(custom))
    except Exception:
        pass
    default = getattr(base_config, "default_journal_dir_path", None)
    if default:
        candidates.append(Path(default))
    candidates.append(Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous")
    for c in candidates:
        if c.is_dir():
            return c
    return None


def read_file(path: Path) -> List[dict]:
    events = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue        # недописанная строка в активном журнале
    except OSError:
        debug(f"journal_history: не удалось прочитать {path}")
    return events


def all_events(max_files: Optional[int] = None,
               directory: Optional[Path] = None) -> List[dict]:
    """Все события просмотренных файлов в хронологическом порядке."""
    d = directory or journal_dir()
    if d is None:
        return []
    files = sorted((p for p in d.iterdir() if p.is_file() and JOURNAL_RE.match(p.name)),
                   reverse=True)
    if max_files is not None:
        files = files[:max_files]
    result: List[dict] = []
    for path in reversed(files):
        result.extend(read_file(path))
    return result


def events_since_boundary(boundary_events: Iterable[str],
                          max_files: int = DEFAULT_MAX_FILES,
                          directory: Optional[Path] = None) -> List[dict]:
    """События (в хронологическом порядке) после последнего события из boundary_events.
    Если границы нет в просмотренных файлах - возвращаются все просмотренные события."""
    boundary = set(boundary_events)
    d = directory or journal_dir()
    if d is None:
        return []
    files = sorted((p for p in d.iterdir() if p.is_file() and JOURNAL_RE.match(p.name)),
                   reverse=True)[:max_files]
    segments: List[List[dict]] = []
    for path in files:
        events = read_file(path)
        idx = -1
        for i in range(len(events) - 1, -1, -1):
            if events[i].get("event") in boundary:
                idx = i
                break
        if idx >= 0:
            segments.append(events[idx + 1:])
            break
        segments.append(events)
    result: List[dict] = []
    for seg in reversed(segments):
        result.extend(seg)
    return result
