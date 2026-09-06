from pathlib import Path
from typing import Any

from ..database import connect_readonly


def query_selected_captures(database_path: Path, capture_ids: list[int]) -> dict[str, Any]:
    """Read explicit selections, including unavailable captures, without inspecting files."""
    if not 1 <= len(capture_ids) <= 500 or any(value < 1 for value in capture_ids):
        raise ValueError("请选择 1–500 个有效照片 ID")
    ids = list(dict.fromkeys(capture_ids))
    connection = connect_readonly(database_path)
    try:
        rows = connection.execute(
            f"""SELECT c.id, c.stem, c.captured_at,
                (SELECT e.proposed_name FROM event_captures ec
                 JOIN events e ON e.id=ec.event_id WHERE ec.capture_id=c.id
                 ORDER BY e.id LIMIT 1) AS album_name,
                EXISTS(SELECT 1 FROM capture_files cf JOIN files f ON f.id=cf.file_id
                       WHERE cf.capture_id=c.id AND cf.role='jpeg' AND f.present=1)
                    AS jpeg_present
                FROM captures c WHERE c.id IN ({','.join('?' for _ in ids)})""",
            ids,
        ).fetchall()
        by_id = {row["id"]: dict(row) for row in rows}
        return {"items": [by_id.get(value, {"id": value, "missing": True}) for value in ids]}
    finally:
        connection.close()
