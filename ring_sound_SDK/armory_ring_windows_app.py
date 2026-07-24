# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import ring_sound as sdk


DEFAULT_ADDRESS = "F2:ED:FF:60:21:F5"
EVENT_LOG_PATH = Path("ring_events_gui.jsonl")

MODE_BY_GESTURE = {
    "rotate_back": {
        "mode": "winter_soldier",
        "label": "Winter Soldier / stable grip",
        "arm_action": "grip",
    },
    "rotate_front": {
        "mode": "shinobi",
        "label": "Shinobi Prosthetic / tool switch",
        "arm_action": "switch_tool",
    },
    "wave": {
        "mode": "devil_breaker",
        "label": "Devil Breaker / burst action",
        "arm_action": "burst",
    },
    "idle": {
        "mode": "idle",
        "label": "Idle / standby",
        "arm_action": "idle",
    },
}

GESTURE_ID_BY_NAME = {
    "idle": 0,
    "rotate_back": 1,
    "rotate_front": 2,
    "wave": 3,
}


def build_payload(gesture_name: str, *, ring_timestamp_ms: int = 0) -> dict[str, object]:
    mapped = MODE_BY_GESTURE.get(gesture_name, MODE_BY_GESTURE["idle"])
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ring_timestamp_ms": ring_timestamp_ms,
        "gesture_id": GESTURE_ID_BY_NAME.get(gesture_name, -1),
        "gesture": gesture_name,
        **mapped,
    }


def append_event(payload: dict[str, object]) -> None:
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


async def connect_with_retry(
    address: str,
    *,
    attempts: int = 3,
    delay_s: float = 2.0,
    log=None,
) -> sdk.RingSoundClient:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        client = sdk.RingSoundClient(address=address)
        try:
            if log:
                log(f"连接尝试 {attempt}/{attempts}：{address}")
            await client.connect()
            return client
        except Exception as exc:
            last_error = exc
            await client.disconnect()
            if attempt < attempts:
                if log:
                    log(f"连接失败：{exc}。{delay_s:g} 秒后重试。")
                await asyncio.sleep(delay_s)

    raise sdk.TransportError(f"连续 {attempts} 次连接失败：{last_error}")


class RingDebugApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Armory Ring Windows Debugger")
        self.root.geometry("980x680")
        self.root.minsize(900, 620)

        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.listen_stop = threading.Event()
        self.listen_thread: threading.Thread | None = None
        self.worker_running = False

        self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
        self.status_var = tk.StringVar(value="未连接")
        self.info_var = tk.StringVar(value="还没有读取戒指信息")
        self.gesture_var = tk.StringVar(value="当前手势：无")

        self._build_ui()
        self._set_status("未连接", "#6b7280")
        self.root.after(100, self._pump_ui_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        title = ttk.Label(
            self.root,
            text="Armory Ring 戒指蓝牙调试面板",
            font=("Microsoft YaHei UI", 18, "bold"),
        )
        title.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))

        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            padx=12,
            pady=8,
            fg="white",
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=16)

        main = ttk.Frame(self.root)
        main.grid(row=2, column=0, sticky="nsew", padx=16, pady=12)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(1, weight=1)

        connection = ttk.LabelFrame(main, text="1. 扫描与连接")
        connection.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 10))
        connection.columnconfigure(1, weight=1)

        ttk.Label(connection, text="戒指地址").grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ttk.Entry(connection, textvariable=self.address_var).grid(
            row=0, column=1, sticky="ew", padx=(0, 10), pady=10
        )

        ttk.Button(connection, text="扫描附近设备", command=self.scan_devices).grid(
            row=1, column=0, sticky="ew", padx=10, pady=(0, 10)
        )
        ttk.Button(connection, text="测试连接/读电量", command=self.check_connection).grid(
            row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 10)
        )
        ttk.Button(connection, text="连接修复提示", command=self.show_fix_tips).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10)
        )

        gesture = ttk.LabelFrame(main, text="2. 手势监听")
        gesture.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 10))
        gesture.columnconfigure(0, weight=1)
        gesture.columnconfigure(1, weight=1)

        ttk.Button(gesture, text="开始监听真实戒指", command=self.start_listening).grid(
            row=0, column=0, sticky="ew", padx=10, pady=10
        )
        ttk.Button(gesture, text="停止监听", command=self.stop_listening).grid(
            row=0, column=1, sticky="ew", padx=(0, 10), pady=10
        )
        ttk.Button(gesture, text="模拟三种手势", command=self.simulate_gestures).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10)
        )
        ttk.Label(gesture, textvariable=self.gesture_var, font=("Microsoft YaHei UI", 12, "bold")).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10)
        )
        ttk.Label(gesture, textvariable=self.info_var, wraplength=420).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10)
        )

        devices_box = ttk.LabelFrame(main, text="扫描结果：双击一行可选中地址")
        devices_box.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        devices_box.rowconfigure(0, weight=1)
        devices_box.columnconfigure(0, weight=1)

        self.devices_tree = ttk.Treeview(
            devices_box,
            columns=("name", "address", "rssi"),
            show="headings",
            height=12,
        )
        self.devices_tree.heading("name", text="名称")
        self.devices_tree.heading("address", text="地址")
        self.devices_tree.heading("rssi", text="信号")
        self.devices_tree.column("name", width=180)
        self.devices_tree.column("address", width=180)
        self.devices_tree.column("rssi", width=80)
        self.devices_tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.devices_tree.bind("<Double-1>", self.use_selected_device)

        log_box = ttk.LabelFrame(main, text="调试日志")
        log_box.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        log_box.rowconfigure(0, weight=1)
        log_box.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_box, height=12, wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        self.log_text.configure(yscrollcommand=scroll.set)

        footer = ttk.Label(
            self.root,
            text="提示：真实手势需要戒指处于红灯 IMU/手势模式。操作方式：单击切换模式，长按，做动作，松手。",
        )
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))

    def _set_status(self, text: str, color: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(bg=color)

    def _log(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {text}\n")
        self.log_text.see("end")

    def _post(self, kind: str, payload: object = None) -> None:
        self.ui_queue.put((kind, payload))

    def _pump_ui_queue(self) -> None:
        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "status":
                text, color = payload  # type: ignore[misc]
                self._set_status(str(text), str(color))
            elif kind == "log":
                self._log(str(payload))
            elif kind == "devices":
                self._render_devices(payload)  # type: ignore[arg-type]
            elif kind == "info":
                self.info_var.set(str(payload))
            elif kind == "gesture":
                self._render_gesture(payload)  # type: ignore[arg-type]
            elif kind == "worker_done":
                self.worker_running = False

        self.root.after(100, self._pump_ui_queue)

    def _render_devices(self, devices: list[sdk.BleDeviceInfo]) -> None:
        self.devices_tree.delete(*self.devices_tree.get_children())
        for device in devices:
            values = (device.name or "", device.address, "" if device.rssi is None else device.rssi)
            item = self.devices_tree.insert("", "end", values=values)
            if "ring" in str(device.name or "").lower():
                self.devices_tree.selection_set(item)
                self.devices_tree.see(item)
                self.address_var.set(device.address)
        self._log(f"扫描到 {len(devices)} 个 BLE 设备。")

    def _render_gesture(self, payload: dict[str, object]) -> None:
        text = (
            f"当前手势：{payload['gesture']} | "
            f"模式：{payload['mode']} | "
            f"动作：{payload['arm_action']}"
        )
        self.gesture_var.set(text)
        self._log(text)

    def use_selected_device(self, _event: object = None) -> None:
        selected = self.devices_tree.selection()
        if not selected:
            return
        values = self.devices_tree.item(selected[0], "values")
        if len(values) >= 2:
            self.address_var.set(str(values[1]))
            self._log(f"已选择地址：{values[1]}")

    def run_async_worker(self, task_factory) -> None:
        if self.worker_running:
            self._log("已有任务正在运行，请稍等。")
            return

        self.worker_running = True

        def worker() -> None:
            try:
                asyncio.run(task_factory())
            except Exception as exc:
                self._post("status", (f"出错：{exc}", "#b91c1c"))
                self._post("log", f"错误：{type(exc).__name__}: {exc}")
            finally:
                self._post("worker_done")

        threading.Thread(target=worker, daemon=True).start()

    def scan_devices(self) -> None:
        async def task() -> None:
            self._post("status", ("正在扫描附近 BLE 设备...", "#d97706"))
            self._post("log", "开始扫描，建议把戒指贴近电脑。")
            devices = await sdk.scan_rings(timeout_s=8.0)
            self._post("devices", devices)
            ring_count = sum(1 for device in devices if "ring" in str(device.name or "").lower())
            if ring_count:
                self._post("status", (f"已扫描到 ring 设备：{ring_count} 个", "#2563eb"))
            else:
                self._post("status", ("扫描完成，但没看到名字为 ring 的设备", "#b45309"))

        self.run_async_worker(task)

    def check_connection(self) -> None:
        address = self.address_var.get().strip()
        if not address:
            messagebox.showwarning("缺少地址", "请先扫描并选择 ring，或者手动填写戒指地址。")
            return

        async def task() -> None:
            self._post("status", ("正在连接戒指...", "#d97706"))
            self._post("log", f"尝试连接：{address}")
            client = await connect_with_retry(
                address,
                attempts=3,
                delay_s=2.0,
                log=lambda text: self._post("log", text),
            )
            try:
                sdk.enable_time_sync(client)
                info = await sdk.get_system_info(client)
                self._post(
                    "info",
                    (
                        f"连接成功 | 电量 {info.battery_percent}% | "
                        f"型号 {info.model} | 固件 {info.firmware_version}"
                    ),
                )
                self._post("status", ("蓝牙连接成功，已读到戒指信息", "#15803d"))
                self._post("log", f"连接成功，电量 {info.battery_percent}%。")
            finally:
                await client.disconnect()

        self.run_async_worker(task)

    def start_listening(self) -> None:
        if self.listen_thread and self.listen_thread.is_alive():
            self._log("监听已经在运行。")
            return

        address = self.address_var.get().strip()
        if not address:
            messagebox.showwarning("缺少地址", "请先扫描并选择 ring，或者手动填写戒指地址。")
            return

        self.listen_stop.clear()

        def worker() -> None:
            asyncio.run(self._listen_task(address))

        self.listen_thread = threading.Thread(target=worker, daemon=True)
        self.listen_thread.start()

    async def _listen_task(self, address: str) -> None:
        self._post("status", ("正在连接并准备监听手势...", "#d97706"))
        self._post("log", f"开始监听：{address}")
        client: sdk.RingSoundClient | None = None
        try:
            client = await connect_with_retry(
                address,
                attempts=5,
                delay_s=2.0,
                log=lambda text: self._post("log", text),
            )
            sdk.enable_time_sync(client)
            info = await sdk.get_system_info(client)
            self._post("status", (f"监听中 | 电量 {info.battery_percent}%", "#15803d"))
            self._post("log", "请单击切换到红灯 IMU/手势模式，然后长按、做动作、松手。")

            while not self.listen_stop.is_set():
                try:
                    event = await sdk.wait_sensor_gesture_event(client, timeout_s=3.0)
                except sdk.TimeoutError:
                    continue

                gesture_name = sdk.sensor_gesture_name(event.gesture_id)
                payload = build_payload(gesture_name, ring_timestamp_ms=event.timestamp_ms)
                append_event(payload)
                self._post("gesture", payload)
        except Exception as exc:
            self._post("status", (f"监听失败：{exc}", "#b91c1c"))
            self._post("log", f"监听错误：{type(exc).__name__}: {exc}")
        finally:
            if client is not None:
                await client.disconnect()
            self._post("log", "监听已结束。")
            if self.listen_stop.is_set():
                self._post("status", ("已停止监听", "#6b7280"))

    def stop_listening(self) -> None:
        self.listen_stop.set()
        self._log("正在停止监听，请等 1-3 秒。")

    def simulate_gestures(self) -> None:
        for gesture_name in ["rotate_back", "rotate_front", "wave"]:
            payload = build_payload(gesture_name)
            append_event(payload)
            self._render_gesture(payload)
        self._set_status("模拟手势已生成，逻辑正常", "#2563eb")
        self._log(f"模拟事件已写入：{EVENT_LOG_PATH}")

    def show_fix_tips(self) -> None:
        messagebox.showinfo(
            "连接修复提示",
            "如果一直连不上：\n\n"
            "1. 关闭手机 App 对戒指的连接。\n"
            "2. 关闭所有正在运行的 PowerShell / Python 调试窗口。\n"
            "3. Windows 设置里把蓝牙关掉，再打开。\n"
            "4. 戒指靠近电脑，长按确认有灯。\n"
            "5. 回到本软件，先点“扫描附近设备”，再点“测试连接/读电量”。\n\n"
            "看到 ring 但连接失败，通常是 Windows BLE 栈卡住或戒指刚被占用。"
        )


def main() -> None:
    root = tk.Tk()
    app = RingDebugApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.stop_listening(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
