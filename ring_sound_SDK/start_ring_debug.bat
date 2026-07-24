@echo off
cd /d "%~dp0"
python armory_ring_gesture_demo.py --address F2:ED:FF:60:21:F5 --output ring_events.jsonl --timeout 30 --retries 5 --retry-delay 2
pause
