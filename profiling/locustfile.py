"""
ThingsBoard Load Testing Scenarios — Locust

Three User classes for TP2 profiling:
  1. WebSocketUser  — Progressive WebSocket subscription load
  2. TelemetryUser  — High-frequency telemetry ingestion via HTTP
  3. AdminUser       — Admin REST API burst under background load

Run a single scenario:
    locust -f locustfile.py WebSocketUser
    locust -f locustfile.py TelemetryUser
    locust -f locustfile.py AdminUser

Run with web UI (pick classes interactively):
    locust -f locustfile.py --class-picker

Headless with HTML report:
    locust -f locustfile.py WebSocketUser --headless -u 100 -r 10 -t 6m \
        --html reports/scenario1.html --csv reports/scenario1
"""

import json
import os
import random
import time
import threading

import requests
import websocket  # websocket-client (gevent-compatible)
from locust import HttpUser, User, task, between, events, tag

# ---------------------------------------------------------------------------
# Configuration (override with environment variables)
# ---------------------------------------------------------------------------
TB_URL = os.getenv("TB_URL", "http://localhost")
TB_WS_URL = os.getenv("TB_WS_URL", "ws://localhost/api/ws/plugins/telemetry")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")

# ---------------------------------------------------------------------------
# Shared state — populated once, reused by all Users
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_jwt_token = None
_devices = []
_device_tokens = []


def _login():
    """Authenticate and cache the JWT token."""
    global _jwt_token
    if _jwt_token is not None:
        return _jwt_token
    with _lock:
        if _jwt_token is not None:
            return _jwt_token
        resp = requests.post(
            f"{TB_URL}/api/auth/login",
            json={"username": TB_USERNAME, "password": TB_PASSWORD},
            timeout=10,
        )
        resp.raise_for_status()
        _jwt_token = resp.json()["token"]
        return _jwt_token


def _get_devices():
    """Fetch the list of tenant devices (cached)."""
    global _devices
    if _devices:
        return _devices
    with _lock:
        if _devices:
            return _devices
        token = _login()
        headers = {"X-Authorization": f"Bearer {token}"}
        resp = requests.get(
            f"{TB_URL}/api/tenant/devices?pageSize=50&page=0",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        _devices = resp.json().get("data", [])
        if not _devices:
            raise RuntimeError(
                "No devices found. Run: python setup_devices.py 50"
            )
        return _devices


def _get_device_tokens():
    """Fetch device access tokens (cached)."""
    global _device_tokens
    if _device_tokens:
        return _device_tokens
    with _lock:
        if _device_tokens:
            return _device_tokens
        token = _login()
        headers = {"X-Authorization": f"Bearer {token}"}
        devices = _get_devices()
        for device in devices:
            resp = requests.get(
                f"{TB_URL}/api/device/{device['id']['id']}/credentials",
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            _device_tokens.append(resp.json()["credentialsId"])
        return _device_tokens


# ---------------------------------------------------------------------------
# Scenario 1: WebSocket subscription user
# ---------------------------------------------------------------------------
class WebSocketUser(User):
    """
    Simulates a dashboard user connected via WebSocket.

    Each user opens a persistent WebSocket, subscribes to a device's
    telemetry, and listens for updates. Locust reports connection time,
    message receive latency, and ping round-trips as custom request types.
    """

    wait_time = between(1, 3)

    def on_start(self):
        token = _login()
        devices = _get_devices()
        self.device = random.choice(devices)
        self.ws_url = f"{TB_WS_URL}?token={token}"
        self.ws = None
        self._connect()

    def _connect(self):
        start = time.time()
        try:
            self.ws = websocket.create_connection(self.ws_url, timeout=10)
            sub_cmd = {
                "tsSubCmds": [
                    {
                        "entityType": "DEVICE",
                        "entityId": self.device["id"]["id"],
                        "scope": "LATEST_TELEMETRY",
                        "cmdId": 1,
                    }
                ],
                "historyCmds": [],
                "attrSubCmds": [],
            }
            self.ws.send(json.dumps(sub_cmd))
            elapsed_ms = (time.time() - start) * 1000
            events.request.fire(
                request_type="WSS",
                name="connect+subscribe",
                response_time=elapsed_ms,
                response_length=0,
                exception=None,
                context={},
            )
        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000
            events.request.fire(
                request_type="WSS",
                name="connect+subscribe",
                response_time=elapsed_ms,
                response_length=0,
                exception=exc,
                context={},
            )

    @task
    def receive_update(self):
        if self.ws is None:
            self._connect()
            return

        start = time.time()
        try:
            self.ws.settimeout(5)
            msg = self.ws.recv()
            elapsed_ms = (time.time() - start) * 1000
            events.request.fire(
                request_type="WSS",
                name="recv",
                response_time=elapsed_ms,
                response_length=len(msg),
                exception=None,
                context={},
            )
        except websocket.WebSocketTimeoutException:
            # No message available — send a keepalive ping
            ping_start = time.time()
            try:
                self.ws.ping()
                elapsed_ms = (time.time() - ping_start) * 1000
                events.request.fire(
                    request_type="WSS",
                    name="ping",
                    response_time=elapsed_ms,
                    response_length=0,
                    exception=None,
                    context={},
                )
            except Exception as exc:
                elapsed_ms = (time.time() - ping_start) * 1000
                events.request.fire(
                    request_type="WSS",
                    name="ping",
                    response_time=elapsed_ms,
                    response_length=0,
                    exception=exc,
                    context={},
                )
                self.ws = None
        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000
            events.request.fire(
                request_type="WSS",
                name="recv",
                response_time=elapsed_ms,
                response_length=0,
                exception=exc,
                context={},
            )
            self.ws = None

    def on_stop(self):
        if self.ws:
            self.ws.close()


# ---------------------------------------------------------------------------
# Scenario 2: Telemetry ingestion user (HTTP POST)
# ---------------------------------------------------------------------------
class TelemetryUser(HttpUser):
    """
    Simulates an IoT device sending telemetry via the HTTP Device API.

    Each user picks a device token and POSTs temperature/humidity/pressure
    readings at a high rate.
    """

    host = TB_URL
    wait_time = between(0.1, 0.5)

    def on_start(self):
        tokens = _get_device_tokens()
        self.device_token = random.choice(tokens)

    @task
    @tag("telemetry")
    def send_telemetry(self):
        telemetry = {
            "temperature": round(random.uniform(20, 30), 2),
            "humidity": round(random.uniform(40, 80), 2),
            "pressure": round(random.uniform(980, 1020), 2),
            "timestamp": int(time.time() * 1000),
        }
        self.client.post(
            f"/api/v1/{self.device_token}/telemetry",
            json=telemetry,
            name="/api/v1/[token]/telemetry",
            timeout=5,
        )


# ---------------------------------------------------------------------------
# Scenario 3: Admin REST API burst under background polling
# ---------------------------------------------------------------------------
class AdminUser(HttpUser):
    """
    Simulates admin/tenant users performing REST API queries.

    A mix of device, customer, dashboard, and asset listing endpoints
    with weighted task distribution. Run alongside a pool of users
    to simulate background dashboard polling + admin burst.
    """

    host = TB_URL
    wait_time = between(0.5, 2.0)

    def on_start(self):
        token = _login()
        self.client.headers.update({"X-Authorization": f"Bearer {token}"})

    @task(3)
    @tag("admin", "devices")
    def list_devices(self):
        self.client.get(
            "/api/tenant/devices?pageSize=100&page=0",
            name="/api/tenant/devices",
            timeout=10,
        )

    @task(2)
    @tag("admin", "customers")
    def list_customers(self):
        self.client.get(
            "/api/customers?pageSize=50&page=0",
            name="/api/customers",
            timeout=10,
        )

    @task(2)
    @tag("admin", "dashboards")
    def list_dashboards(self):
        self.client.get(
            "/api/tenant/dashboards?pageSize=50&page=0",
            name="/api/tenant/dashboards",
            timeout=10,
        )

    @task(1)
    @tag("admin", "assets")
    def list_assets(self):
        self.client.get(
            "/api/tenant/assets?pageSize=50&page=0",
            name="/api/tenant/assets",
            timeout=10,
        )
