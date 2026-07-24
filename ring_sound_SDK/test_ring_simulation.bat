@echo off
cd /d "%~dp0"
python armory_ring_gesture_demo.py --simulate --max-events 3 --clear-output --output ring_events_simulated.jsonl
pause
