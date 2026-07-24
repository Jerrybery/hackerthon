# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import queue
import subprocess
import sys
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

import ring_sound as sdk


APP_TITLE = "Zilo Ring Only Debugger"
RING_NAME = "ring"
EVENT_LOG_PATH = Path("ring_only_events.jsonl")
SCAN_SECONDS = 25.0

MODE_BY_GESTURE = {
    "rotate_back": ("winter_soldier", "grip"),
    "rotate_front": ("shinobi", "switch_tool"),
    "wave": ("devil_breaker", "burst"),
    "idle": ("idle", "idle"),
}


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


def is_ring_device(device: sdk.BleDeviceInfo) -> bool:
    return str(device.name or "").strip().lower() == RING_NAME


def make_event(gesture_name: str, timestamp_ms: int = 0) -> dict[str, Any]:
    mode, action = MODE_BY_GESTURE.get(gesture_name, MODE_BY_GESTURE["idle"])
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ring_timestamp_ms": timestamp_ms,
        "gesture": gesture_name,
        "mode": mode,
        "arm_action": action,
    }


def save_event(payload: dict[str, Any]) -> None:
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def parse_info_output(output: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def run_official_info_command(
    address: str,
    *,
    timeout_s: float = 75.0,
    attempts: int = 3,
) -> dict[str, str]:
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            completed = subprocess.run(
                [sys.executable, "ring_sound.py", "info", "--address", address],
                cwd=Path(__file__).resolve().parent,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            last_error = f"official SDK info timeout after {timeout_s:g}s"
        else:
            if completed.returncode == 0:
                return parse_info_output(completed.stdout)
            last_error = (completed.stderr or completed.stdout).strip()
        if attempt < attempts:
            continue
    raise sdk.TransportError(f"official SDK info failed after {attempts} attempts: {last_error}")


async def scan_ring_only(
    *,
    rounds: int = 1,
    timeout_s: float = SCAN_SECONDS,
    log: Callable[[str], None] | None = None,
) -> tuple[list[sdk.BleDeviceInfo], int]:
    found_by_address: dict[str, sdk.BleDeviceInfo] = {}
    ignored_count = 0
    for round_index in range(1, rounds + 1):
        if log:
            log(f"扫描 ring 设备 {round_index}/{rounds}，本轮最多 {timeout_s:g} 秒...")
        devices = await sdk.scan_rings(timeout_s=timeout_s)
        ignored_count += sum(1 for device in devices if not is_ring_device(device))
        for device in devices:
            if is_ring_device(device):
                found_by_address[device.address] = device
    return list(found_by_address.values()), ignored_count


async def pick_ring_address(
    preferred_address: str | None,
    *,
    timeout_s: float = SCAN_SECONDS,
    log: Callable[[str], None] | None = None,
) -> sdk.BleDeviceInfo:
    rings, ignored_count = await scan_ring_only(rounds=1, timeout_s=timeout_s, log=log)
    if log:
        log(f"已忽略非 ring 蓝牙设备 {ignored_count} 个。")

    if preferred_address:
        preferred = preferred_address.strip().lower()
        for ring in rings:
            if ring.address.strip().lower() == preferred:
                return ring
        raise sdk.TransportError(
            f"地址 {preferred_address} 当前没有以名称 ring 广播。请先扫描确认。"
        )

    if not rings:
        raise sdk.TransportError("没有扫描到名称严格等于 ring 的设备。")
    if len(rings) > 1 and log:
        log(f"扫描到 {len(rings)} 个 ring，默认选择第一个：{rings[0].address}")
    return rings[0]


async def connect_ring_strict(
    preferred_address: str | None,
    *,
    attempts: int,
    log: Callable[[str], None] | None = None,
) -> tuple[sdk.RingSoundClient, sdk.BleDeviceInfo]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        client: sdk.RingSoundClient | None = None
        try:
            if preferred_address:
                ring = sdk.BleDeviceInfo(name=RING_NAME, address=preferred_address, rssi=None)
            else:
                ring = await pick_ring_address(None, timeout_s=SCAN_SECONDS, log=log)
            if log:
                log(f"连接 ring 尝试 {attempt}/{attempts}: {ring.address}")
            client = sdk.RingSoundClient(address=ring.address)
            await client.connect()
            sdk.enable_time_sync(client)
            return client, ring
        except Exception as exc:
            last_error = exc
            if client is not None:
                await client.disconnect()
            if log:
                log(f"连接失败：{type(exc).__name__}: {exc}")
            if preferred_address and attempt == 1:
                try:
                    await pick_ring_address(preferred_address, timeout_s=8.0, log=log)
                    if log:
                        log("已确认该地址仍以 ring 名称广播，继续重试连接。")
                except Exception as scan_exc:
                    if log:
                        log(f"快速复扫没有确认到该 ring：{scan_exc}")
            if attempt < attempts:
                await asyncio.sleep(2.0)
    raise sdk.TransportError(f"连续 {attempts} 次只连接 ring 失败：{last_error}")


class RingOnlyApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1040x720")
        self.root.minsize(920, 640)

        self.ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker_busy = False
        self.stop_event = threading.Event()
        self.listen_thread: threading.Thread | None = None

        self.address_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="未连接：只会扫描和连接名称为 ring 的蓝牙设备")
        self.info_var = tk.StringVar(value="还没有读取戒指信息")
        self.gesture_var = tk.StringVar(value="当前手势：无")

        self._build_ui()
        self._set_status("未连接：只识别 ring", "#4b5563")
        self.root.after(100, self._pump_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="Zilo Ring 专用蓝牙调试软件",
            font=("Microsoft YaHei UI", 20, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="扫描结果只保留名称严格等于 ring 的设备，避免连到其他蓝牙设备。",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            fg="white",
            anchor="w",
            padx=12,
            pady=9,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=16)

        main = ttk.Frame(self.root)
        main.grid(row=2, column=0, sticky="nsew", padx=16, pady=12)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=4)
        main.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(main, text="连接控制")
        controls.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="ring 地址").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ttk.Entry(controls, textvariable=self.address_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 10), pady=10
        )
        ttk.Button(controls, text="1. 只扫描 ring", command=self.scan).grid(
            row=0, column=2, sticky="ew", padx=(0, 10), pady=10
        )
        ttk.Button(controls, text="2. 测试连接/读电量", command=self.check).grid(
            row=0, column=3, sticky="ew", padx=(0, 10), pady=10
        )
        ttk.Button(controls, text="3. 开始监听手势", command=self.listen).grid(
            row=1, column=2, sticky="ew", padx=(0, 10), pady=(0, 10)
        )
        ttk.Button(controls, text="停止监听", command=self.stop_listen).grid(
            row=1, column=3, sticky="ew", padx=(0, 10), pady=(0, 10)
        )
        ttk.Button(controls, text="模拟三种手势", command=self.simulate).grid(
            row=1, column=0, sticky="ew", padx=10, pady=(0, 10)
        )
        ttk.Button(controls, text="连接修复提示", command=self.show_tips).grid(
            row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 10)
        )

        devices_frame = ttk.LabelFrame(main, text="ring 扫描结果（双击选择）")
        devices_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        devices_frame.rowconfigure(0, weight=1)
        devices_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(devices_frame, columns=("name", "address", "rssi"), show="headings")
        self.tree.heading("name", text="名称")
        self.tree.heading("address", text="地址")
        self.tree.heading("rssi", text="信号")
        self.tree.column("name", width=100)
        self.tree.column("address", width=180)
        self.tree.column("rssi", width=80)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.tree.bind("<Double-1>", self.use_selected)

        right = ttk.Frame(main)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        info = ttk.LabelFrame(right, text="戒指状态")
        info.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(info, textvariable=self.info_var, wraplength=580).grid(
            row=0, column=0, sticky="w", padx=10, pady=10
        )
        ttk.Label(info, textvariable=self.gesture_var, font=("Microsoft YaHei UI", 13, "bold")).grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 10)
        )

        log_frame = ttk.LabelFrame(right, text="调试日志")
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, wrap="word", font=("Consolas", 10), height=18)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.log_text.configure(yscrollcommand=scroll.set)

        footer = ttk.Label(
            self.root,
            text="手势模式：单击戒指切换到红灯 IMU 状态，然后长按，做动作，松手。",
        )
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(bg=color)

    def _log(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {text}\n")
        self.log_text.see("end")

    def _post(self, kind: str, payload: Any = None) -> None:
        self.ui_queue.put((kind, payload))

    def _pump_queue(self) -> None:
        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                text, color = payload
                self._set_status(text, color)
            elif kind == "log":
                self._log(str(payload))
            elif kind == "rings":
                self._render_rings(payload)
            elif kind == "info":
                self.info_var.set(str(payload))
            elif kind == "gesture":
                self._render_gesture(payload)
            elif kind == "done":
                self.worker_busy = False
        self.root.after(100, self._pump_queue)

    def _render_rings(self, rings: list[sdk.BleDeviceInfo]) -> None:
        self.tree.delete(*self.tree.get_children())
        for ring in rings:
            item = self.tree.insert("", "end", values=(ring.name, ring.address, ring.rssi or ""))
            self.tree.selection_set(item)
            self.tree.see(item)
            self.address_var.set(ring.address)
        if rings:
            self._set_status(f"扫描到 {len(rings)} 个 ring，请测试连接", "#2563eb")
        else:
            self._set_status("没有扫描到 ring", "#b45309")

    def _render_gesture(self, payload: dict[str, Any]) -> None:
        text = f"当前手势：{payload['gesture']} | 模式：{payload['mode']} | 动作：{payload['arm_action']}"
        self.gesture_var.set(text)
        self._log(text)

    def use_selected(self, _event: object = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if len(values) >= 2:
            self.address_var.set(str(values[1]))
            self._log(f"已选择 ring 地址：{values[1]}")

    def run_worker(self, task_factory: Callable[[], Any]) -> None:
        if self.worker_busy:
            self._log("已有任务正在运行，请稍等。")
            return
        self.worker_busy = True

        def worker() -> None:
            try:
                asyncio.run(task_factory())
            except Exception as exc:
                self._post("status", (f"失败：{exc}", "#b91c1c"))
                self._post("log", f"错误：{type(exc).__name__}: {exc}")
            finally:
                self._post("done")

        threading.Thread(target=worker, daemon=True).start()

    def scan(self) -> None:
        async def task() -> None:
            self._post("status", ("正在只扫描 ring...", "#d97706"))
            rings, ignored = await scan_ring_only(rounds=1, timeout_s=SCAN_SECONDS, log=lambda s: self._post("log", s))
            self._post("log", f"扫描完成：ring={len(rings)}，已隐藏非 ring 设备={ignored}")
            self._post("rings", rings)

        self.run_worker(task)

    def check(self) -> None:
        preferred = self.address_var.get().strip() or None

        async def task() -> None:
            self._post("status", ("正在确认 ring 并调用官方 SDK 读电量...", "#d97706"))
            ring = await pick_ring_address(preferred, timeout_s=SCAN_SECONDS, log=lambda s: self._post("log", s))
            self.address_var.set(ring.address)
            self._post("log", f"官方 SDK info 测试：{ring.address}")
            info = await asyncio.to_thread(run_official_info_command, ring.address)
            battery = info.get("battery_percent", "?")
            model = info.get("model", "?")
            firmware = info.get("firmware_version", "?")
            cpuid = info.get("cpuid", "?")
            self._post(
                "info",
                f"连接成功 | 地址 {ring.address} | 电量 {battery}% | 型号 {model} | 固件 {firmware} | CPUID {cpuid}",
            )
            self._post("status", ("ring 连接成功，官方 SDK 已读到电量", "#15803d"))
            self._post("log", f"连接成功：battery={battery} model={model}")

        self.run_worker(task)

    def listen(self) -> None:
        if self.listen_thread and self.listen_thread.is_alive():
            self._log("监听已经在运行。")
            return
        preferred = self.address_var.get().strip() or None
        self.stop_event.clear()

        def worker() -> None:
            asyncio.run(self._listen_task(preferred))

        self.listen_thread = threading.Thread(target=worker, daemon=True)
        self.listen_thread.start()

    async def _listen_task(self, preferred: str | None) -> None:
        self._post("status", ("正在连接 ring 并监听手势...", "#d97706"))
        client: sdk.RingSoundClient | None = None
        try:
            client, ring = await connect_ring_strict(preferred, attempts=5, log=lambda s: self._post("log", s))
            info = await sdk.get_system_info(client)
            self._post("status", (f"监听中 | {ring.address} | 电量 {info.battery_percent}%", "#15803d"))
            self._post("log", "现在操作戒指：单击切红灯，长按，做动作，松手。")
            while not self.stop_event.is_set():
                try:
                    event = await sdk.wait_sensor_gesture_event(client, timeout_s=3.0)
                except sdk.TimeoutError:
                    continue
                gesture = sdk.sensor_gesture_name(event.gesture_id)
                payload = make_event(gesture, event.timestamp_ms)
                save_event(payload)
                self._post("gesture", payload)
        except Exception as exc:
            self._post("status", (f"监听失败：{exc}", "#b91c1c"))
            self._post("log", f"监听错误：{type(exc).__name__}: {exc}")
        finally:
            if client is not None:
                await client.disconnect()
            if self.stop_event.is_set():
                self._post("status", ("已停止监听", "#4b5563"))
            self._post("log", "监听结束。")

    def stop_listen(self) -> None:
        self.stop_event.set()
        self._log("正在停止监听。")

    def simulate(self) -> None:
        for gesture in ["rotate_back", "rotate_front", "wave"]:
            payload = make_event(gesture)
            save_event(payload)
            self._render_gesture(payload)
        self._set_status("模拟手势通过", "#2563eb")
        self._log(f"模拟事件已写入 {EVENT_LOG_PATH}")

    def show_tips(self) -> None:
        messagebox.showinfo(
            "ring 连接修复提示",
            "请按顺序做：\n\n"
            "1. 关闭手机 App 对戒指的连接。\n"
            "2. 关闭其他 PowerShell、Python、旧版 ring 软件窗口。\n"
            "3. Windows 设置 -> 蓝牙，关闭后再打开。\n"
            "4. 戒指靠近电脑，长按确认有灯。\n"
            "5. 回到本软件，先点“只扫描 ring”，再点“测试连接/读电量”。\n\n"
            "本软件会隐藏所有非 ring 设备，所以列表为空就说明当前没看到 ring 广播。"
        )


def main() -> None:
    root = tk.Tk()
    app = RingOnlyApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_listen(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
