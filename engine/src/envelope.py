"""Pembuat envelope event SIGAP — format yang dipahami backend consumer."""
import uuid
from datetime import datetime, timezone, timedelta

_WIB = timezone(timedelta(hours=7))


def build_envelope(camera_id: str, module: str, event_type: str,
                   data: dict, confidence: float | None = None) -> dict:
    """Bentuk pesan standar:
    { messageId, ts, cameraId, module, eventType, confidence, data }
    """
    return {
        "messageId": str(uuid.uuid4()),
        "ts": datetime.now(_WIB).isoformat(),
        "cameraId": camera_id,
        "module": module,
        "eventType": event_type,
        "confidence": confidence,
        "data": data,
    }
