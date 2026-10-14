
import asyncio

from app.websockets.manager import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.fail = False

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("Connection closed")
        self.messages.append(message)


def test_broadcast_queue_sends_to_all_connections():
    manager = ConnectionManager()
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()

    manager.queue_connections[1].update({ws1, ws2})
    message = {
        "type": "queue_snapshot",
        "doctor_id": 1,
        "queue": [],
    }

    asyncio.run(manager.broadcast_queue(1, message))

    assert ws1.messages == [message]
    assert ws2.messages == [message]


def test_notify_user_sends_to_user_connections():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    manager.notification_connections[3].add(ws)
    message = {"type": "patient_called", "appointment_id": 5}

    asyncio.run(manager.notify_user(3, message))

    assert ws.messages == [message]


def test_broken_queue_connection_is_removed():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    ws.fail = True
    manager.queue_connections[1].add(ws)

    asyncio.run(
        manager.broadcast_queue(1, {"type": "queue_snapshot"})
    )

    assert ws not in manager.queue_connections.get(1, set())


def test_broken_notification_connection_is_removed():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    ws.fail = True
    manager.notification_connections[3].add(ws)

    asyncio.run(
        manager.notify_user(3, {"type": "patient_called"})
    )

    assert ws not in manager.notification_connections.get(3, set())


def test_patient_called_notification_payload():
    manager = ConnectionManager()
    patient_user_id = 3
    ws = FakeWebSocket()
    manager.notification_connections[patient_user_id].add(ws)

    message = {
        "type": "patient_called",
        "message": "Next patient called successfully",
        "appointment_id": 6,
        "appointment_number": "APT-20261014-BD8CB8BB",
        "token_number": 1,
        "status": "In Consultation",
        "doctor_id": 1,
    }

    asyncio.run(manager.notify_user(patient_user_id, message))

    assert len(ws.messages) == 1
    assert ws.messages[0]["type"] == "patient_called"
    assert ws.messages[0]["appointment_id"] == 6
    assert ws.messages[0]["status"] == "In Consultation"
    assert ws.messages[0]["doctor_id"] == 1


def test_queue_snapshot_payload():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    manager.queue_connections[1].add(ws)

    message = {
        "type": "queue_snapshot",
        "doctor_id": 1,
        "date": "2026-10-14",
        "queue": [
            {
                "appointment_id": 6,
                "appointment_number": "APT-20261014-BD8CB8BB",
                "token_number": 1,
                "patient_name": "Test Patient",
                "slot_time": "14:45:00",
                "status": "In Consultation",
            }
        ],
    }

    asyncio.run(manager.broadcast_queue(1, message))

    assert len(ws.messages) == 1
    assert ws.messages[0]["type"] == "queue_snapshot"
    assert ws.messages[0]["doctor_id"] == 1
    assert ws.messages[0]["queue"][0]["status"] == "In Consultation"
