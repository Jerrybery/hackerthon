from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import ring_sound as sdk
from hmm_gesture.feature_extractor import FeatureExtractor
from hmm_gesture.recognize import HMMRecognizer
from hmm_gesture.signal_filter import SignalFilter


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
RECORDINGS_DIR = APP_DIR / "recordings"
HMM_MODEL_DIR = APP_DIR / "hmm_gesture" / "pretrained_models"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


class ConnectRequest(BaseModel):
    address: str = Field(min_length=3)
    auto_time_sync: bool = True
    command_timeout_s: float = Field(default=10.0, ge=1.0, le=120.0)


class DownloadAudioRequest(BaseModel):
    file_index: int = Field(ge=0)
    timeout_s: float = Field(default=45.0, ge=1.0, le=300.0)
    quick: bool = True


class ReceiveAutoAudioRequest(BaseModel):
    timeout_s: float = Field(default=90.0, ge=1.0, le=600.0)


class ClearAudioRequest(BaseModel):
    confirm: bool = False


class ScanRequest(BaseModel):
    address: str | None = None
    timeout_s: float = Field(default=8.0, ge=1.0, le=60.0)


def to_payload(value: Any) -> Any:
    if is_dataclass(value):
        return to_payload(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): to_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_payload(item) for item in value]
    return value


def timestamp_payload(seconds: int) -> dict[str, Any]:
    if not seconds:
        return {"epoch": 0, "local": ""}
    local = datetime.fromtimestamp(seconds)
    return {"epoch": seconds, "local": local.strftime("%Y-%m-%d %H:%M:%S")}


def public_audio_bundle(bundle: sdk.AudioBundle) -> dict[str, Any]:
    raw_name = bundle.raw_path.name
    play_name = bundle.play_path.name
    return {
        **to_payload(bundle),
        "raw_url": f"/recordings/{raw_name}",
        "play_url": f"/recordings/{play_name}",
    }


class RingRuntime:
    def __init__(self) -> None:
        self.client: sdk.RingSoundClient | None = None
        self.address: str | None = None
        self.connected_at: datetime | None = None
        self.sensor_started = False
        self.sensor_info: sdk.SensorStartInfo | None = None
        self.hmm_enabled = False
        self.hmm_recognizer: HMMRecognizer | None = None
        self.hmm_count = 0
        self._request_lock = asyncio.Lock()
        self._websockets: set[WebSocket] = set()
        self._event_tasks: list[asyncio.Task[None]] = []
        self._imu_task: asyncio.Task[None] | None = None

    async def broadcast(self, event: str, data: Any = None) -> None:
        payload = {"event": event, "data": to_payload(data)}
        dead: list[WebSocket] = []
        for websocket in list(self._websockets):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self._websockets.discard(websocket)

    def status(self) -> dict[str, Any]:
        connected = bool(self.client and self.client.is_connected)
        return {
            "connected": connected,
            "address": self.address if connected else None,
            "connected_at": self.connected_at.isoformat() if connected and self.connected_at else None,
            "sensor_started": self.sensor_started if connected else False,
            "sensor_info": to_payload(self.sensor_info) if connected and self.sensor_info else None,
            "hmm_enabled": self.hmm_enabled if connected else False,
            "hmm_available": HMM_MODEL_DIR.exists(),
            "hmm_models": self._hmm_model_names(),
            "hmm_count": self.hmm_count if connected else 0,
        }

    async def scan(self, request: ScanRequest) -> list[dict[str, Any]]:
        devices = await sdk.scan_rings(address=request.address, timeout_s=request.timeout_s)
        return [to_payload(device) for device in devices]

    async def connect(self, request: ConnectRequest) -> dict[str, Any]:
        async with self._request_lock:
            await self._disconnect_locked()
            client = await sdk.connect_ring(
                address=request.address,
                command_timeout_s=request.command_timeout_s,
                auto_time_sync=request.auto_time_sync,
            )
            self.client = client
            self.address = request.address
            self.connected_at = datetime.now()
            self._start_event_watchers(client)
        await self.broadcast("status", self.status())
        return self.status()

    async def disconnect(self) -> dict[str, Any]:
        async with self._request_lock:
            await self._disconnect_locked()
        await self.broadcast("status", self.status())
        return self.status()

    async def system_info(self) -> dict[str, Any]:
        async with self._request_lock:
            client = self._require_client()
            info = await sdk.get_system_info(client)
        data = to_payload(info)
        data["system_time_display"] = timestamp_payload(info.system_time)
        await self.broadcast("system_info", data)
        return data

    async def audio_count(self) -> dict[str, int]:
        async with self._request_lock:
            count = await sdk.get_audio_file_count(self._require_client())
        return {"count": count}

    async def download_audio(self, request: DownloadAudioRequest) -> dict[str, Any]:
        async with self._request_lock:
            client = self._require_client()
            loop = asyncio.get_running_loop()

            def progress(current: int, total: int) -> None:
                loop.create_task(
                    self.broadcast(
                        "audio_progress",
                        {
                            "mode": "download",
                            "file_index": request.file_index,
                            "current": current,
                            "total": total,
                        },
                    )
                )

            info, data = await sdk.download_audio_file(
                client,
                request.file_index,
                progress=progress,
                timeout_s=request.timeout_s,
                quick=request.quick,
            )
            bundle = sdk.save_audio_bundle(
                file_index=info.file_index,
                data=data,
                metadata={"record_time": info.record_time},
                output_dir=RECORDINGS_DIR,
            )
        result = {"info": to_payload(info), "record_time": timestamp_payload(info.record_time), "bundle": public_audio_bundle(bundle)}
        await self.broadcast("audio_saved", result)
        return result

    async def receive_auto_audio(self, request: ReceiveAutoAudioRequest) -> dict[str, Any]:
        async with self._request_lock:
            client = self._require_client()
            file_index, data = await sdk.receive_auto_audio_file(
                client,
                timeout_s=request.timeout_s,
            )
            bundle = sdk.save_audio_bundle(
                file_index=file_index,
                data=data,
                output_dir=RECORDINGS_DIR,
            )
        result = {"file_index": file_index, "bundle": public_audio_bundle(bundle)}
        await self.broadcast("audio_saved", result)
        return result

    async def clear_audio(self, request: ClearAudioRequest) -> dict[str, Any]:
        if not request.confirm:
            raise HTTPException(status_code=400, detail="清空录音需要 confirm=true")
        async with self._request_lock:
            await sdk.clear_audio_files(self._require_client())
        await self.broadcast("audio_cleared", {})
        return {"cleared": True}

    async def start_imu(self) -> dict[str, Any]:
        async with self._request_lock:
            client = self._require_client()
            if self.sensor_started:
                return self.status()
            self.sensor_info = await sdk.start_sensor_report(client)
            self.sensor_started = True
            self._imu_task = asyncio.create_task(self._imu_loop(client))
        await self.broadcast("status", self.status())
        return self.status()

    async def start_hmm(self) -> dict[str, Any]:
        async with self._request_lock:
            client = self._require_client()
            self._ensure_hmm_recognizer()
            if not self.sensor_started:
                self.sensor_info = await sdk.start_sensor_report(client)
                self.sensor_started = True
                self._imu_task = asyncio.create_task(self._imu_loop(client))
            self.hmm_enabled = True
        await self.broadcast("status", self.status())
        return self.status()

    async def stop_hmm(self) -> dict[str, Any]:
        self.hmm_enabled = False
        await self.broadcast("status", self.status())
        return self.status()

    async def stop_imu(self) -> dict[str, Any]:
        async with self._request_lock:
            client = self._require_client()
            if self._imu_task:
                self._imu_task.cancel()
                await asyncio.gather(self._imu_task, return_exceptions=True)
                self._imu_task = None
            if self.sensor_started:
                await sdk.stop_sensor_report(client)
            self.sensor_started = False
            self.sensor_info = None
            self.hmm_enabled = False
        await self.broadcast("status", self.status())
        return self.status()

    async def websocket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._websockets.add(websocket)
        await websocket.send_json({"event": "status", "data": self.status()})
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            self._websockets.discard(websocket)

    def _require_client(self) -> sdk.RingSoundClient:
        if self.client is None or not self.client.is_connected:
            raise HTTPException(status_code=409, detail="戒指尚未连接")
        return self.client

    async def _disconnect_locked(self) -> None:
        for task in self._event_tasks:
            task.cancel()
        if self._imu_task:
            self._imu_task.cancel()
            await asyncio.gather(self._imu_task, return_exceptions=True)
            self._imu_task = None
        if self._event_tasks:
            await asyncio.gather(*self._event_tasks, return_exceptions=True)
        self._event_tasks.clear()
        self.sensor_started = False
        self.sensor_info = None
        self.hmm_enabled = False
        self.hmm_count = 0

        if self.client is not None:
            try:
                await self.client.disconnect()
            finally:
                self.client = None
                self.address = None
                self.connected_at = None

    def _start_event_watchers(self, client: sdk.RingSoundClient) -> None:
        watchers = [
            ("double_tap", sdk.wait_sensor_double_tap_event, None),
            ("key_single_press", sdk.wait_sensor_key_single_press_event, None),
            ("key_double_press", sdk.wait_sensor_key_double_press_event, None),
            ("gesture", sdk.wait_sensor_gesture_event, self._format_gesture),
        ]
        self._event_tasks = [
            asyncio.create_task(self._event_loop(client, event_name, waiter, formatter))
            for event_name, waiter, formatter in watchers
        ]

    async def _event_loop(self, client: sdk.RingSoundClient, event_name: str, waiter: Any, formatter: Any) -> None:
        while client is self.client and client.is_connected:
            try:
                event = await waiter(client, timeout_s=3600.0)
                data = to_payload(event)
                if formatter:
                    data.update(formatter(event))
                await self.broadcast("ring_event", {"type": event_name, **data})
            except asyncio.CancelledError:
                raise
            except sdk.TimeoutError:
                continue
            except sdk.TransportError:
                break
            except Exception as exc:
                await self.broadcast("error", {"source": event_name, "message": str(exc)})
                await asyncio.sleep(1)

    async def _imu_loop(self, client: sdk.RingSoundClient) -> None:
        while client is self.client and client.is_connected and self.sensor_started:
            try:
                batch = await sdk.wait_sensor_data(client, timeout_s=10.0)
                hmm_samples = [
                    [sample.accel_x, sample.accel_y, sample.accel_z, sample.gyro_x, sample.gyro_y, sample.gyro_z]
                    for sample in batch.samples
                ]
                if self.hmm_enabled and self.hmm_recognizer:
                    try:
                        result = self.hmm_recognizer.feed(hmm_samples)
                        if result:
                            name, confidence = result
                            self.hmm_count += 1
                            await self.broadcast(
                                "hmm_gesture",
                                {
                                    "name": name,
                                    "confidence": round(confidence, 3),
                                    "count": self.hmm_count,
                                },
                            )
                    except Exception as exc:
                        await self.broadcast("error", {"source": "hmm", "message": str(exc)})
                samples = batch.samples[-30:]
                await self.broadcast(
                    "imu",
                    {
                        "sequence_start": batch.sequence_start,
                        "frame_count": batch.frame_count,
                        "samples": [to_payload(sample) for sample in samples],
                    },
                )
            except asyncio.CancelledError:
                raise
            except sdk.TimeoutError:
                continue
            except Exception as exc:
                self.sensor_started = False
                await self.broadcast("error", {"source": "imu", "message": str(exc)})
                await self.broadcast("status", self.status())
                break

    def _ensure_hmm_recognizer(self) -> None:
        if self.hmm_recognizer is not None:
            return
        if not HMM_MODEL_DIR.exists():
            raise HTTPException(status_code=400, detail=f"HMM 模型目录不存在: {HMM_MODEL_DIR}")
        self.hmm_recognizer = HMMRecognizer(
            HMM_MODEL_DIR,
            SignalFilter(sample_rate=25.0, cutoff_hz=10.0),
            FeatureExtractor(window_size=8, overlap=4),
        )
        if not self.hmm_recognizer._models:
            raise HTTPException(status_code=400, detail="没有加载到 HMM 预训练模型")

    def _hmm_model_names(self) -> list[str]:
        if not HMM_MODEL_DIR.exists():
            return []
        return sorted(path.stem for path in HMM_MODEL_DIR.glob("*.pkl"))

    def _format_gesture(self, event: sdk.SensorGestureEvent) -> dict[str, Any]:
        return {"gesture_name": sdk.sensor_gesture_name(event.gesture_id)}


runtime = RingRuntime()
app = FastAPI(title="Ring Sound Control", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/recordings", StaticFiles(directory=RECORDINGS_DIR), name="recordings")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    return runtime.status()


@app.post("/api/scan")
async def api_scan(request: ScanRequest) -> list[dict[str, Any]]:
    return await guarded(runtime.scan(request))


@app.post("/api/connect")
async def api_connect(request: ConnectRequest) -> dict[str, Any]:
    return await guarded(runtime.connect(request))


@app.post("/api/disconnect")
async def api_disconnect() -> dict[str, Any]:
    return await guarded(runtime.disconnect())


@app.get("/api/system")
async def api_system() -> dict[str, Any]:
    return await guarded(runtime.system_info())


@app.get("/api/audio/count")
async def api_audio_count() -> dict[str, int]:
    return await guarded(runtime.audio_count())


@app.post("/api/audio/download")
async def api_audio_download(request: DownloadAudioRequest) -> dict[str, Any]:
    return await guarded(runtime.download_audio(request))


@app.post("/api/audio/receive-auto")
async def api_receive_auto_audio(request: ReceiveAutoAudioRequest) -> dict[str, Any]:
    return await guarded(runtime.receive_auto_audio(request))


@app.post("/api/audio/clear")
async def api_audio_clear(request: ClearAudioRequest) -> dict[str, Any]:
    return await guarded(runtime.clear_audio(request))


@app.post("/api/imu/start")
async def api_imu_start() -> dict[str, Any]:
    return await guarded(runtime.start_imu())


@app.post("/api/imu/stop")
async def api_imu_stop() -> dict[str, Any]:
    return await guarded(runtime.stop_imu())


@app.post("/api/hmm/start")
async def api_hmm_start() -> dict[str, Any]:
    return await guarded(runtime.start_hmm())


@app.post("/api/hmm/stop")
async def api_hmm_stop() -> dict[str, Any]:
    return await guarded(runtime.stop_hmm())


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await runtime.websocket(websocket)


async def guarded(awaitable: Any) -> Any:
    try:
        return await awaitable
    except HTTPException:
        raise
    except sdk.RingSoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
