#!/usr/bin/env python3
"""Musical tempo, beat synchronization, and live BPM adjustment demo.

Demonstrates:
  1. Composing in musical units (`beats(1)`, `bars(4)`, `t.sixteenth`, `t.quarter`).
  2. Coexisting with fixed wall-clock seconds (`duration=0.1` for strobes/physics).
  3. Dynamic runtime tempo modulation (`t.bpm = 140`, `t.tap()`) with zero phase glitches!

Usage:
  python3 examples/demo_tempo_bpm.py --dry-run
  python3 examples/demo_tempo_bpm.py --host 192.168.1.158
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightshow import (
    Chase,
    Color,
    Hold,
    Pulse,
    Rig,
    Tempo,
    bars,
    beats,
)
from my_rig import PARS, STAGE


def create_tempo_show(tempo: Tempo):
    """Create a multi-layer lighting show bound to musical subdivisions."""
    # Layer 1: 4-on-the-floor kick pulse (1 beat = quarter note)
    kick_pulse = Pulse(Color.RED, duration=tempo.quarter, low=0.1, high=1.0)

    # Layer 2: Rapid 16th-note hi-hat chase
    hihat_chase = Chase(
        Color.CYAN,
        step_duration=tempo.sixteenth,
        tail=0.5,
        background=Color(0.0, 0.05, 0.1),
    )

    # Layer 3: Physical fixed 0.1s white strobe burst on fixture 0 and 7 on the downbeat
    strobe_hit = Hold(Color.WHITE, strobe=0.9, duration=0.1).on(0, 7)

    # Combine into a 2-bar groove
    groove = PARS(kick_pulse | hihat_chase | strobe_hit) * tempo.bars(2)
    return groove


def main() -> None:
    parser = argparse.ArgumentParser(description="Musical Tempo & BPM Modulation Demo")
    parser.add_argument("--host", default="192.168.1.158", help="Art-Net node IP")
    parser.add_argument("--universe", type=int, default=1, help="Art-Net universe")
    parser.add_argument("--dry-run", action="store_true", help="Print ASCII output without sending UDP")
    args = parser.parse_args()

    # 1. Initialize tempo at 120 BPM
    t = Tempo(120.0)
    print(f"🎵 Initialized Tempo at {t.bpm} BPM")
    print(f"   1 Beat (quarter)   = {float(t.quarter):.3f}s")
    print(f"   1 16th-note step   = {float(t.sixteenth):.3f}s")
    print(f"   1 Bar (4 beats)    = {float(t.bar):.3f}s")

    groove = create_tempo_show(t)
    print(f"\n✨ Created 2-bar groove scene (Duration: {groove.duration:.3f}s)")

    # 2. Demonstrate dynamic BPM change
    print("\n⚡ Dynamically speeding up from 120 BPM to 140 BPM...")
    t.bpm = 140.0
    print(f"   Now at {t.bpm} BPM:")
    print(f"   1 Beat (quarter)   = {float(t.quarter):.3f}s")
    print(f"   1 16th-note step   = {float(t.sixteenth):.3f}s")
    print(f"   2-Bar Groove dur   = {groove.duration:.3f}s (automatically updated!)")

    # 3. Demonstrate tap-tempo
    print("\n👆 Simulating tap-tempo (tapping 3 times at 133.3 BPM)...")
    base_t = time.monotonic()
    t.tap(base_t)
    t.tap(base_t + 0.45)
    t.tap(base_t + 0.90)
    print(f"   Updated BPM from taps: {t.bpm:.1f} BPM")
    print(f"   2-Bar Groove dur     : {groove.duration:.3f}s")

    # 4. Stream preview
    rig = Rig([PARS], host=args.host, universe=args.universe, dry_run=args.dry_run)
    print("\n▶️ Streaming first 2.0s of groove:")
    dt = 0.2
    for step in range(10):
        t_sample = step * dt
        dmx = rig.render_dmx(groove, t_sample)
        par_rgb = [f"({dmx[i]},{dmx[i+1]},{dmx[i+2]})" for i in range(0, 12, 3)]
        print(f"  t={t_sample:.2f}s | PAR 1..4: {' '.join(par_rgb)}")

    print("\n✓ Musical tempo demo completed successfully!")


if __name__ == "__main__":
    main()
