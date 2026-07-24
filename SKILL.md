---
name: ring-sound
description: "Ring Sound 智能戒指 SDK 速查：BLE 端口、v4 协议命令、Python 公开 API、录音下载/解码、IMU 与手势事件。当用户开发、调试或集成 ring_sound_SDK（语音戒指、ring_sound.py、录音下载、Speex 解码、IMU 0x0605、手势 0x0702）时使用本 skill。"
---

# Ring Sound SDK 速查

单文件 Python SDK `ring_sound.py`（v0.3.4），通过 BLE（Nordic UART Service + bleak）与语音戒指通信。协议 v4，固件基线 `V2.000.0001.0015`。

源文档（更详细时查阅）：
- `ring_sound_SDK/ring_sound_use.md` — 公开 API 手册（参数/返回值/异常/示例）
- `ring_sound_SDK/protocol.md` — 协议字段表
- `ring_sound_SDK/README.md` — 分层、字节序、音频格式原理

## 环境

- Python ≥ 3.11，全部 BLE 调用为 `async`/`await`
- `pip install bleak`（BLE 必需）；解码 WAV 还需系统可执行 `ffmpeg`
- 导入：`import ring_sound as sdk`（`ring_sound.py` 与调用脚本同目录）

## BLE 端口（NUS）

| 用途 | UUID |
|---|---|
| Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| TX（戒指→主机，notify） | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |
| RX（主机→戒指，write） | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |

按 MAC 地址筛选设备（不依赖广播名）。一次 BLE notify ≠ 一个完整协议包，SDK 内部 `PacketStream` 负责重组。

## 协议包格式（v4）

11 字节头，大端：`magic(1B=0x3F) | version(2B=4) | command(2B) | body_length(4B) | body_crc(2B)` + body（≤5120B，CRC16 初值 0xFFFF 只覆盖 body）。包体内 u16/i16/u32 均大端。**例外**：录音 .bin 内 Speex 帧长为 2 字节小端。

## 协议命令地图

| 命令 | 功能 | SDK 高层函数 |
|---|---|---|
| `0x0101/0x0102` | 系统信息 | `get_system_info()` |
| `0x0301–0x0304` | 日志存储信息/分块读 | `get_log_storage()`、`read_log_chunk()` |
| `0x0401/0x0402` | 校时（设备主动请求） | `enable_time_sync()`、`send_time_response()` |
| `0x0501/0x0502` | 录音数量 | `get_audio_file_count()` |
| `0x0503→0x0508` | 普通下载链路 | `download_audio_file(quick=False)` |
| `0x0509→0x0504→0x0505…` | quick 下载链路（默认） | `download_audio_file(quick=True)` |
| 连续 `0x0505`（无 0x0504） | 录音保存后自动推送 | `receive_auto_audio_file()` |
| `0x050B/0x050C` | 清空所有录音（破坏性） | `clear_audio_files()` |
| `0x0601–0x0604` | 开/关 IMU 批量上报 | `start_sensor_report()`、`stop_sensor_report()` |
| `0x0605` | 批量六轴数据（主动） | `wait_sensor_data()` → `SensorDataBatch` |
| `0x0701` | 普通双击事件 | `wait_sensor_double_tap_event()` |
| `0x0702` | HMM 手势（0 idle/1 rotate_back/2 rotate_front/3 wave） | `wait_sensor_gesture_event()` |
| `0x0703` | 按键双击（排他） | `wait_sensor_key_double_press_event()` |
| `0x0704` | 按键单击（尝试切换模式） | `wait_sensor_key_single_press_event()` |

设备错误码：0 成功 / 2 busy / 3 文件不存在 / 7 参数错误（`DeviceError.error_code`）。

## 设备模式状态机（关键）

设备只有**录音模式**（开机默认）和**手势模式**，无协议命令可查询或切换模式——只有用户单击按键尝试切换（上报 `0x0704`，但不保证成功）。

| 操作 | 效果 |
|---|---|
| 单击 | `0x0704`，尝试切换模式（双击判定窗口 500ms 后才到达） |
| 双击 | 仅 `0x0703`，不切换模式 |
| 长按 | 录音模式→开始录音；手势模式→HMM 手势会话 |
| 长按松开 | 结束录音（保存后自动推送 0x0505）或手势（上报 0x0702） |

IMU 要点：本地 IMU 采集只存在于手势模式。`start_sensor_report()`（0x0601）只开 BLE 上报开关、不启动 IMU；录音模式调用返回 `DeviceError(2)` busy。`0x0702` HMM 用手势模式内部 IMU，**不要求**先开 0x0605。

## 录音数据格式

设备 .bin = 连续 `[u16 小端帧长][Speex payload]`（Speex Wideband 16kHz，20ms/帧，quality 3，payload 约 20B）。**不是** WAV/Ogg，不能直接播放。SDK 解码链：解析长度前缀 → 构建 Ogg Speex → ffmpeg → s16le PCM → WAV 头（16kHz/单声道/16bit）。

## 常用代码骨架

连接 + 系统信息：

```python
async with sdk.RingSoundClient(address="F1:C1:8A:35:40:FB") as ring:
    sdk.enable_time_sync(ring)
    info = await sdk.get_system_info(ring)
```

下载录音并保存 WAV：

```python
count = await sdk.get_audio_file_count(ring)
info, raw = await sdk.download_audio_file(ring, file_index=0)  # 默认 quick 链路
bundle = sdk.save_audio_bundle(file_index=info.file_index, data=raw,
                               metadata={"record_time": info.record_time},
                               output_dir="audio")
# bundle.raw_path (.bin) / bundle.play_path (.wav)
```

即时接收刚录完的录音（设备保存后自动推送）：

```python
file_index, raw = await sdk.receive_auto_audio_file(ring, timeout_s=60.0)
```

IMU 批量数据（前提：设备已在手势模式）：

```python
await sdk.start_sensor_report(ring)
try:
    batch = await sdk.wait_sensor_data(ring, timeout_s=5.0)
    for i, s in enumerate(batch.samples):
        print(batch.sequence_start + i, s.accel_x, s.gyro_x)
finally:
    await sdk.stop_sensor_report(ring)
```

手势事件：`event = await sdk.wait_sensor_gesture_event(ring, timeout_s=30.0)`，名称用 `sdk.sensor_gesture_name(event.gesture_id)`。

## CLI

```bash
python ring_sound.py scan --address <MAC>
python ring_sound.py info --address <MAC>
python ring_sound.py audio-count --address <MAC>
python ring_sound.py audio-download --address <MAC> 0 output.wav --timeout 30
python ring_sound.py audio-decode input.bin output.wav
python ring_sound.py audio-clear --address <MAC> --yes   # 破坏性
```

## 常见坑

- `receive_auto_audio_file()` 与 `download_audio_file()`/`read_audio_frame()` **不能并发**——消费同一 0x0505 队列。错过自动推送就查 count 后 `download_audio_file()` 补下。
- 同一连接同一时间只发一个"请求-响应"命令，否则响应互相消费导致超时。
- `0x0704` ≠ 模式切换成功；设备忙时切换可能失败但事件照样上报。
- .bin 改名 .wav/.spx 不会变成可播放文件——必须走 `save_audio_bundle()`/`decode_audio_to_wav()`。
- 高层解码函数默认 `allow_framed_blocks=False`；1026 字节外层分块输入需显式传 `True`。
- 异常层级：`RingSoundError` ← `TransportError`(BLE) / `ProtocolError`(协议) / `TimeoutError` / `DeviceError`(设备错误码) / `AudioDecodeError` ← `SpeexDecoderUnavailable`(缺 ffmpeg)。
- 清空录音 `clear_audio_files()` 不可逆，业务代码需二次确认。
