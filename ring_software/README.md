# Ring Sound 本地控制台

这是基于 `ring_sound_SDK_副本` 构建的戒指本地软件。后端使用 Python SDK 连接 BLE 戒指，前端在浏览器中提供操作界面。

## 功能

- 扫描附近 BLE 设备，并按 MAC 地址连接戒指
- 自动响应设备校时请求
- 读取系统信息、电量、固件、型号、SN、存储空间
- 查询录音数量、下载指定录音、等待戒指保存后的主动录音上报
- 将录音同时保存为原始 `.bin` 和可播放 `.wav`
- 开启/停止实时 IMU 上报，并绘制加速度曲线
- 监听普通双击、按键单击、按键双击、HMM 手势事件
- 支持清空设备录音，操作前需要勾选确认

## 启动

```bash
cd /Users/ronggang/code/funcode/adv/ring_software
python3 -m pip install -r requirements.txt
python3 -m uvicorn app:app --host 127.0.0.1 --port 8765
```

打开：

```text
http://127.0.0.1:8765
```

## 使用提示

- BLE 操作依赖 macOS 蓝牙权限。如果系统弹窗请求蓝牙权限，请允许运行中的 Python 或终端。
- 录音解码依赖 `ffmpeg`，当前机器已检测到可用的 `ffmpeg`。
- 实时 IMU 前，需要先单击戒指切到手势模式，再点击界面里的“开始”。
- HMM 手势识别使用 `hmm_gesture/pretrained_models` 内置模型，支持向上、向下、向左、向右、甩、打响指。
- “等待新录音”需要在连接保持期间长按戒指录音并松开，设备保存后会主动推送数据。
- 录音文件保存在 `/Users/ronggang/code/funcode/adv/ring_software/recordings`。

## HMM 手势流程

算法文件位于 `hmm_gesture/`，可按“采集 -> 训练 -> 识别”三步独立运行。

```bash
# 采集训练数据
python -m hmm_gesture.record_gesture --name 打响指 --ring --address F1:C1:8A:35:40:FB --reps 5

# 训练模型
python -m hmm_gesture.train_hmm --data hmm_gesture/gestures --output hmm_gesture/models

# 使用预训练模型离线验证
python -m hmm_gesture.recognize --models hmm_gesture/pretrained_models --input hmm_gesture/sample_data/向上.json
```

## SDK 来源

项目中的 `ring_sound.py` 直接复制自：

```text
/Users/ronggang/Downloads/ring_sound_SDK_副本/ring_sound.py
```
