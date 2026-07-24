from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

import ring_sound as sdk


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

SIMULATED_GESTURES = ["rotate_back", "rotate_front", "wave"]
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


def save_payload(output_path: Path, payload: dict[str, object]) -> None:
    with output_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def print_payload(payload: dict[str, object]) -> None:
    print(
        f"[{payload['ts']}] gesture={payload['gesture']} "
        f"mode={payload['mode']} arm_action={payload['arm_action']}"
    )


async def resolve_address(args: argparse.Namespace) -> str:
    if args.address:
        return args.address

    print("No address provided. Scanning nearby BLE devices...")
    devices = await sdk.scan_rings(timeout_s=args.scan_timeout)
    ring_devices = [
        device
        for device in devices
        if "ring" in str(device.name or "").lower()
    ]

    if not ring_devices:
        print("Scan results:")
        for device in devices:
            print(f"  name={device.name!r} address={device.address} rssi={device.rssi}")
        raise SystemExit("No device named 'ring' found. Run scan again near the ring.")

    selected = ring_devices[0]
    print(f"Selected ring: name={selected.name!r} address={selected.address}")
    return selected.address


async def run_simulation(args: argparse.Namespace) -> None:
    output_path = Path(args.output)
    if args.clear_output and output_path.exists():
        output_path.unlink()

    event_count = args.max_events or len(SIMULATED_GESTURES)
    print("Simulation mode. No BLE hardware is required.")
    for index in range(event_count):
        gesture_name = SIMULATED_GESTURES[index % len(SIMULATED_GESTURES)]
        payload = build_payload(gesture_name, ring_timestamp_ms=index * 1000)
        print_payload(payload)
        save_payload(output_path, payload)
    print(f"Wrote simulated events to {output_path}")


async def connect_with_retry(address: str, *, retries: int, retry_delay: float) -> sdk.RingSoundClient:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        client = sdk.RingSoundClient(address=address)
        try:
            print(f"Connecting to ring... attempt {attempt}/{retries}")
            await client.connect()
            return client
        except Exception as exc:
            last_error = exc
            await client.disconnect()
            if attempt < retries:
                print(f"Connect failed: {exc}. Retrying in {retry_delay:g}s...")
                await asyncio.sleep(retry_delay)

    raise SystemExit(f"Could not connect to ring after {retries} attempts: {last_error}")


async def run_real_ring(args: argparse.Namespace) -> None:
    output_path = Path(args.output)
    if args.clear_output and output_path.exists():
        output_path.unlink()

    address = await resolve_address(args)
    ring = await connect_with_retry(
        address,
        retries=max(1, args.retries),
        retry_delay=max(0.0, args.retry_delay),
    )
    try:
        sdk.enable_time_sync(ring)
        info = await sdk.get_system_info(ring)
        print(
            f"Connected. address={address} battery={info.battery_percent}% "
            f"model={info.model!r} firmware={info.firmware_version!r}"
        )

        if args.check_only:
            print("Check-only complete.")
            return

        print("Make sure the ring is in IMU/gesture mode.")
        print("Operation: single-click to switch mode, long-press, move, release.")
        print("Supported gestures: rotate_back / rotate_front / wave.")
        print("Press Ctrl+C to stop.\n")

        event_count = 0
        empty_count = 0
        while args.max_events <= 0 or event_count < args.max_events:
            try:
                event = await sdk.wait_sensor_gesture_event(ring, timeout_s=args.timeout)
            except sdk.TimeoutError:
                empty_count += 1
                print("No gesture received. Long-press, move, then release.")
                if args.max_empty > 0 and empty_count >= args.max_empty:
                    break
                continue

            empty_count = 0
            gesture_name = sdk.sensor_gesture_name(event.gesture_id)
            payload = build_payload(gesture_name, ring_timestamp_ms=event.timestamp_ms)
            print_payload(payload)
            save_payload(output_path, payload)
            event_count += 1
    finally:
        await ring.disconnect()

    print(f"Wrote real ring events to {output_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Armory Ring gesture debugger.")
    parser.add_argument("--address", default=None, help="Ring BLE address. Optional.")
    parser.add_argument("--scan-timeout", type=float, default=8.0)
    parser.add_argument("--output", default="ring_events.jsonl", help="JSONL event log path.")
    parser.add_argument("--timeout", type=float, default=60.0, help="Seconds to wait per gesture.")
    parser.add_argument("--max-events", type=int, default=0, help="0 means keep listening.")
    parser.add_argument("--max-empty", type=int, default=0, help="Stop after N timeouts; 0 means never.")
    parser.add_argument("--retries", type=int, default=3, help="BLE connection retries.")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Seconds between retries.")
    parser.add_argument("--check-only", action="store_true", help="Connect, print info, then exit.")
    parser.add_argument("--simulate", action="store_true", help="Write fake events without BLE hardware.")
    parser.add_argument("--clear-output", action="store_true", help="Clear output file before writing.")
    args = parser.parse_args()

    if args.simulate:
        await run_simulation(args)
    else:
        await run_real_ring(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
