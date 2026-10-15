# Hori Flex Controller PC input protocol

The Hori Flex Controller has a second USB port that lets a PC send it synthetic inputs. The Flex then passes those inputs on through its normal gamepad output. This document describes the protocol on that port.

[flex.py](flex.py) is an example implementation in Python using hidapi.

For a more complete application that can send inputs from any controller connected to your PC to the Flex Controller, see the `any2flex` tool in the [HID Router](https://github.com/jfedor2/hid-router) repository.

_Please note you will need a non-standard USB cable with Type A plugs on both ends._

## USB devices

| VID:PID | Role |
|---|---|
| `0F0D:0168` | PC input port (this protocol) |
| `0F0D:00FD` | Gamepad output in Switch mode |
| `0F0D:014B` | Gamepad output in PC mode (Xbox 360/"XInput") |

The PC input port is a HID device with two interfaces:

* **Interface 0** (usage page `0xFF00`) carries the protocol. The host sends report ID `0x02`, the device answers with report ID `0x01`. Both reports are 64 bytes including the report ID.
* **Interface 1** (usage page `0xFF01`) sends report ID `0x59` every 40 ms. You do not need to do anything with it to send synthetic inputs to the controller.

The protocol is the same whichever output mode the Flex is in.

## Output report (host to device)

| Offset | Contents |
|---|---|
| 0 | Report ID `0x02` |
| 1 | Command |
| 2-3 | Command-specific |
| 4-63 | Payload |

| Command | Meaning |
|---|---|
| `0x00` | Set input state |
| `0x01`, `0x02`, `0x03` | Handshake |
| `0xFF` | Latch the current state for readback |

## Handshake

After each power-up, the device ignores input state until the host completes a handshake. Every handshake packet carries the magic value `78 C1 87 3E` at offsets 60-63. The device answers each one with an input report:

```
01 <cmd> <status> <r> <16 bytes> ... 78 C1 87 3E
```

1. **Info.** The host sends `02 01`, with byte 12 = `01`. The device replies with `01 01 01 01 1E 01 08 02 1D 01 26 01 <b12> <b13> ...`. Byte 13 is `01` once the device is unlocked.
2. **Host challenges device.** The host sends `02 02 00 r` followed by 16 random bytes, where `r` is a random byte. The device replies with `01 02 01 r` followed by `cipher(r, challenge)`. The host can use this reply to check that the device is genuine.
3. **Device challenges host.** The host sends `02 03 00 00` with an empty payload. The device replies with `01 03 00 r` followed by a 16-byte challenge.
4. **Host responds.** The host sends `02 03 00 r` followed by `cipher(r, challenge)`, using the `r` and challenge from step 3. The device replies with `01 03 <status> r`. Status `01` means the device accepted the response and is now unlocked.

### Cipher

The cipher is a variant of RC4 that runs on a 16-entry state and works on 16-byte blocks:

```
key[0] = 0x54, key[1] = 0x21
key[n] = key[n-2] + key[n-1] + n  (mod 256), for n = 2..15

S[i] = (4*i + r) & 0xFF, or 0xF9 if that is 0, for i = 0..15

j = 0
for i in 0..15:
    j = (j + key[i] + S[i]) & 15
    swap(S[i], S[j])

i = 0                      # j is carried over, not reset
for n in 0..15:
    i = (i + 1) & 15
    j = (j + S[i]) & 15
    swap(S[i], S[j])
    out[n] = in[n] ^ S[(S[i] + S[j]) & 15]
```

## Input state (command `0x00`)

To set the input state, the host sends `02 00 00 00` followed by one byte per input. The device keeps the last state it received, so the host only needs to send a report when something changes.

| Offset | Switch mode | PC mode (Xbox 360) |
|---|---|---|
| 4 | Y | Y |
| 5 | B | B |
| 6 | A | A |
| 7 | X | X |
| 8 | L | LB |
| 9 | R | RB |
| 10 | ZL | LT |
| 11 | ZR | RT |
| 12 | - | Back |
| 13 | + | Start |
| 14 | Left stick click | Left stick click |
| 15 | Right stick click | Right stick click |
| 16 | Home | Guide |
| 17 | Capture | (none) |
| 18 | D-pad up | D-pad up |
| 19 | D-pad down | D-pad down |
| 20 | D-pad left | D-pad left |
| 21 | D-pad right | D-pad right |
| 22 | Left stick X | Left stick X |
| 23 | Left stick Y | Left stick Y |
| 24 | Right stick X | Right stick X |
| 25 | Right stick Y | Right stick Y |
| 26-63 | Unused (0) | Unused (0) |

* **Buttons** (offsets 4-21) are pressed when their byte is exactly `0x64`. Any other value means released, and this includes triggers: in PC mode LT/RT report 0 or 255. To press a d-pad diagonal, set both of its direction bytes.
* **Sticks** (offsets 22-25) take values from `0x00` to `0x7F`; higher values are clamped. Neutral is `3F 40 3F 40`. For X, `0x00` is full left and `0x7F` is full right. For Y, `0x00` is full down and `0x7F` is full up. In PC mode, the full range maps to -32768 ... +32767.

## State readback (command `0xFF`)

To read back the state the device currently holds:

1. Send `02 FF` with the rest of the report zero.
2. Read **string descriptor index `0xFD`** (66 bytes), for example with `HidD_GetIndexedString` on Windows. The data starts `42 03 01 04 55 AA`, followed by the current input state: input-state offset *n* appears at descriptor offset *n* + 2.
3. If bytes 3-5 aren't `04 55 AA` yet, read it again.

String descriptor index `0xFE` returns the firmware version (`08 03 01 26 02 08 ...`).
