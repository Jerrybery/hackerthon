"""Shared helpers to open the HHS USB-CANFD adapter on macOS via gs_usb userspace."""

import platform

import can
import usb.core
from gs_usb.gs_usb import GsUsb

HHS_VID = 0xA8FA
HHS_PID = 0x8598

_patched = False


def _patch() -> None:
    global _patched
    if _patched:
        return
    _orig = GsUsb.is_gs_usb_device
    GsUsb.is_gs_usb_device = staticmethod(
        lambda dev: _orig(dev) or (dev.idVendor == HHS_VID and dev.idProduct == HHS_PID)
    )
    if platform.system() == "Darwin":
        usb.core.Device.is_kernel_driver_active = lambda self, intf: False

    # HHS adapter: OUT endpoint is 0x01, not gs_usb's default 0x02
    def _send_ep01(self: GsUsb, frame, hw_timestamps: bool = False) -> None:
        self.gs_usb.write(0x01, frame.pack(hw_timestamps))

    GsUsb.send = _send_ep01
    _patched = True


def open_bus(bitrate: int = 1_000_000, channel: int = 0) -> can.BusABC:
    _patch()
    return can.interface.Bus(interface="gs_usb", channel=channel, bitrate=bitrate)


class EchoFilterBus(can.BusABC):
    """Wraps a gs_usb bus and drops TX-echo frames (is_rx=False).

    SocketCAN suppresses echo frames by default; the userspace gs_usb backend
    delivers them, which confuses the A1Z SDK control loop (it parses its own
    MIT command frames as motor feedback -> saturated positions, false faults).
    """

    def __init__(self, inner: can.BusABC, channel: str = "echo-filtered"):
        self._inner = inner
        super().__init__(channel=channel)

    def send(self, msg: can.Message, timeout=None) -> None:
        self._inner.send(msg, timeout)

    def _recv_internal(self, timeout):
        while True:
            msg, filtered = self._inner._recv_internal(timeout)
            if msg is None or msg.is_rx:
                return msg, filtered
            # echo frame: drop and keep waiting with remaining budget
            timeout = 0.05

    def shutdown(self) -> None:
        self._inner.shutdown()

    @property
    def state(self):
        return self._inner.state
