"""Generate the deterministic, redistributable Day 1 audio fixture."""

from __future__ import annotations

import argparse
import io
import struct
import sys
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "tests" / "fixtures" / "day1" / "audio" / "tiny_pulse.wav"
SAMPLE_RATE = 8_000
FRAME_COUNT = SAMPLE_RATE
PULSE_FRAMES = 200


def render_wav() -> bytes:
    """Render one second of four deterministic, decaying bipolar pulses."""

    frames = bytearray()
    pulse_starts = {0, SAMPLE_RATE // 4, SAMPLE_RATE // 2, (SAMPLE_RATE * 3) // 4}
    active_start = -PULSE_FRAMES
    for frame in range(FRAME_COUNT):
        if frame in pulse_starts:
            active_start = frame
        offset = frame - active_start
        if 0 <= offset < PULSE_FRAMES:
            amplitude = (12_000 * (PULSE_FRAMES - offset)) // PULSE_FRAMES
            sample = amplitude if (offset // 10) % 2 == 0 else -amplitude
        else:
            sample = 0
        frames.extend(struct.pack("<h", sample))

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the checked-in WAV differs from deterministic generator output",
    )
    args = parser.parse_args()
    expected = render_wav()
    if args.check:
        if not OUTPUT_PATH.is_file():
            print(f"missing fixture: {OUTPUT_PATH}", file=sys.stderr)
            return 1
        if OUTPUT_PATH.read_bytes() != expected:
            print(f"fixture drift: regenerate {OUTPUT_PATH}", file=sys.stderr)
            return 1
        print(f"fixture is deterministic: {OUTPUT_PATH}")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(expected)
    print(f"wrote {len(expected)} bytes to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
