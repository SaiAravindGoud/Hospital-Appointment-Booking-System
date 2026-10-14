
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.queue_connections: dict[int, set[WebSocket]] = defaultdict(set)
        self.notification_connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect_queue(self, doctor_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.queue_connections[doctor_id].add(websocket)

    def disconnect_queue(self, doctor_id: int, websocket: WebSocket) -> None:
        self.queue_connections[doctor_id].discard(websocket)
        if not self.queue_connections[doctor_id]:
            self.queue_connections.pop(doctor_id, None)

    async def connect_notifications(
        self, user_id: int, websocket: WebSocket
    ) -> None:
        await websocket.accept()
        self.notification_connections[user_id].add(websocket)

    def disconnect_notifications(
        self, user_id: int, websocket: WebSocket
    ) -> None:
        self.notification_connections[user_id].discard(websocket)
        if not self.notification_connections[user_id]:
            self.notification_connections.pop(user_id, None)

    async def broadcast_queue(
        self, doctor_id: int, message: dict[str, Any]
    ) -> None:
        connections = list(self.queue_connections.get(doctor_id, set()))
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect_queue(doctor_id, websocket)

    async def notify_user(
        self, user_id: int, message: dict[str, Any]
    ) -> None:
        connections = list(
            self.notification_connections.get(user_id, set())
        )
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect_notifications(user_id, websocket)


manager = ConnectionManager()
