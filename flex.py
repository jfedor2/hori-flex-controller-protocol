#!/usr/bin/env python3
# Copyright (c) 2026 Jacek Fedorynski
# SPDX-License-Identifier: MIT
"""Send synthetic inputs to a HORI Flex Controller via its PC-side "View" USB port.

Requires: pip install hidapi
See https://github.com/jfedor2/hori-flex-controller-protocol for the protocol description.
"""
import os
import time

import hid

VID = 0x0F0D
PID_VIEW = 0x0168  # PC-side input port ("Flex Controller(View)"), interface 0

MAGIC = bytes.fromhex("78c1873e")  # trailer on handshake commands (offset 60)
PRESSED = 0x64  # buttons only register at exactly 100

# Payload offsets in the 64-byte output report
Y, B, A, X, L, R, ZL, ZR = range(4, 12)
MINUS, PLUS, LSTICK, RSTICK, HOME, CAPTURE = range(12, 18)
UP, DOWN, LEFT, RIGHT = range(18, 22)
LX, LY, RX, RY = range(22, 26)  # 0x00..0x7f; X: 0=left, Y: 0=down (inverted)
STICK_CENTER = {LX: 0x3F, LY: 0x40, RX: 0x3F, RY: 0x40}

# The same offsets under their PC-mode (Xbox 360) names. Face buttons follow
# the label (Switch A -> Xbox A), not the position. As with all buttons,
# triggers are either off or fully pulled (255).
# CAPTURE has no Xbox 360 equivalent and does nothing in PC mode.
XB_A, XB_B, XB_X, XB_Y = A, B, X, Y
LB, RB, LT, RT = L, R, ZL, ZR
BACK, START, GUIDE = MINUS, PLUS, HOME


def flex_cipher(r, data):
    """16-byte RC4-like cipher used in both directions of the handshake."""
    key = [0x54, 0x21]
    for n in range(2, 16):
        key.append((key[n - 2] + key[n - 1] + n) & 0xFF)
    s = [((4 * i + r) & 0xFF) or 0xF9 for i in range(16)]
    j = 0
    for i in range(16):
        j = (j + key[i] + s[i]) & 15
        s[i], s[j] = s[j], s[i]
    out = bytearray(data)
    i = 0  # note: j is NOT reset after key scheduling
    for n in range(16):
        i = (i + 1) & 15
        j = (j + s[i]) & 15
        s[i], s[j] = s[j], s[i]
        out[n] ^= s[(s[i] + s[j]) & 15]
    return bytes(out)


class Flex:
    def __init__(self, path=None):
        if path is None:
            devs = [d for d in hid.enumerate(VID, PID_VIEW) if d["interface_number"] == 0]
            if not devs:
                raise IOError("Flex Controller(View) not found")
            path = devs[0]["path"]
        self.dev = hid.device()
        self.dev.open_path(path)
        self.state = bytearray(64)
        self.state[0] = 0x02
        for off, v in STICK_CENTER.items():
            self.state[off] = v

    def close(self):
        self.dev.close()

    def _command(self, cmd, r=0, body=b"", flag=None):
        pkt = bytearray(64)
        pkt[0], pkt[1], pkt[3] = 0x02, cmd, r
        pkt[4:4 + len(body)] = body
        if flag is not None:
            pkt[12] = flag
        pkt[60:64] = MAGIC
        self.dev.write(bytes(pkt))
        resp = bytes(self.dev.read(64, 1000))
        if len(resp) < 20 or resp[0] != 0x01 or resp[1] != cmd:
            raise IOError("no/bad response to command %02x: %s" % (cmd, resp.hex()))
        return resp

    def handshake(self):
        """Unlock synthetic input. Needed once after each power-up."""
        info = self._command(0x01, flag=1)
        # 1) host challenges device (device authenticity check; optional for us)
        r, chal = os.urandom(1)[0], os.urandom(16)
        resp = self._command(0x02, r, chal)
        if resp[4:20] != flex_cipher(r, chal):
            raise IOError("device failed authentication")
        # 2) device challenges host
        resp = self._command(0x03)
        r, chal = resp[3], resp[4:20]
        resp = self._command(0x03, r, flex_cipher(r, chal))
        if resp[2] != 1:
            raise IOError("device rejected our handshake response")
        return info

    def send(self):
        self.dev.write(bytes(self.state))

    def set(self, offset, value, send=True):
        self.state[offset] = value
        if send:
            self.send()

    def press(self, offset, send=True):
        self.set(offset, PRESSED, send)

    def release(self, offset, send=True):
        self.set(offset, 0, send)

    def tap(self, offset, hold=0.4):
        self.press(offset)
        time.sleep(hold)
        self.release(offset)

    def reset(self):
        self.state[1:] = bytes(63)
        for off, v in STICK_CENTER.items():
            self.state[off] = v
        self.send()


if __name__ == "__main__":
    f = Flex()
    print("info:", f.handshake()[:16].hex())
    f.reset()
    for _ in range(8):
        for btn in (A, B, X, Y):
            f.tap(btn)
            time.sleep(0.1)
    f.close()
