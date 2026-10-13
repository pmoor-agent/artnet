"""Zero-dependency Art-Net (ArtDMX) UDP client and generic Rig controller."""

from __future__ import annotations
import socket
import struct
import time
from typing import Mapping, Optional, Sequence, Union

from .clips import Clip
from .fixtures import DMXCanvas, FixtureGroup, Scene


ARTNET_PORT = 6454
ARTNET_HEADER = b"Art-Net\x00"
OPCODE_ARTDMX = 0x5000  # Little-endian on the wire: 0x00, 0x50
PROTOCOL_VERSION = 14


def build_artdmx_packet(
    dmx_data: bytes | Sequence[int],
    universe: int = 1,
    sequence: int = 0,
    physical: int = 0,
) -> bytes:
    """Build an Art-Net ArtDMX (OpOutput / 0x5000) UDP packet.

    Args:
        dmx_data: Up to 512 DMX channel bytes (0..255). Length is padded to an even number
            (minimum 2 bytes) per the Art-Net specification.
        universe: 15-bit Port-Address (Net/Sub-Net/Universe combined, e.g. 0 or 1).
        sequence: Packet sequence number (1..255, or 0 to disable sequence tracking).
        physical: Physical input port number (informational, usually 0).
    """
    payload = bytes(dmx_data)
    if len(payload) > 512:
        payload = payload[:512]
    if len(payload) < 2:
        payload = payload.ljust(2, b"\x00")
    elif len(payload) % 2 == 1:
        payload += b"\x00"

    header = (
        ARTNET_HEADER
        + struct.pack("<H", OPCODE_ARTDMX)
        + struct.pack(">H", PROTOCOL_VERSION)
        + struct.pack("BB", sequence & 0xFF, physical & 0xFF)
        + struct.pack("<H", universe & 0x7FFF)
        + struct.pack(">H", len(payload))
    )
    return header + payload


class ArtNetClient:
    """UDP client for sending ArtDMX frames to an Art-Net node."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = ARTNET_PORT,
        universe: int = 0,
        universe_base: int = 0,
        frame_size: int = 512,
    ) -> None:
        self.host = host
        self.port = port
        self.universe = universe
        self.universe_base = universe_base
        self.frame_size = max(2, min(512, frame_size))
        self._sequence = 1
        self._sock: Optional[socket.socket] = None

    @property
    def wire_universe(self) -> int:
        """The 15-bit universe value sent inside the ArtDMX packet."""
        return max(0, self.universe - self.universe_base)

    def open(self) -> None:
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def send_dmx(self, channels: Sequence[int]) -> bytes:
        """Send a DMX frame (up to 512 channels, 1-indexed DMX Channel 1 is `channels[0]`)."""
        self.open()
        buf = bytearray(max(self.frame_size, len(channels)))
        for i, val in enumerate(channels[:512]):
            buf[i] = max(0, min(255, int(val)))

        packet = build_artdmx_packet(
            buf,
            universe=self.wire_universe,
            sequence=self._sequence,
        )
        self._sequence = (self._sequence % 255) + 1
        assert self._sock is not None
        self._sock.sendto(packet, (self.host, self.port))
        return packet

    def __enter__(self) -> ArtNetClient:
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


SceneInput = Union[Scene, Clip, Mapping[Union[str, FixtureGroup], Clip]]


class Rig:
    """Generic DMX Rig controller that streams composable `Scene`s over Art-Net."""

    def __init__(
        self,
        groups: Optional[Sequence[FixtureGroup]] = None,
        *,
        host: str = "127.0.0.1",
        universe: int = 0,
        universe_base: int = 0,
        fps: float = 40.0,
        dry_run: bool = False,
    ) -> None:
        self.groups: tuple[FixtureGroup, ...] = tuple(groups or ())
        self.groups_by_name: dict[str, FixtureGroup] = {g.name: g for g in self.groups}
        self.fps = fps
        self.dry_run = dry_run
        self.client = ArtNetClient(
            host=host,
            universe=universe,
            universe_base=universe_base,
        )

    def _to_scene(self, scene_input: SceneInput) -> Scene:
        """Normalize a `Scene`, a bare `Clip`, or a `{group: Clip}` dict into a `Scene`."""
        if isinstance(scene_input, Scene):
            return scene_input
        if isinstance(scene_input, Clip):
            if not self.groups:
                raise ValueError("Cannot pass a bare Clip when Rig has no default groups configured.")
            return self.groups[0](scene_input)

        # Convert dict into a layered `|` Scene
        combined: Optional[Scene] = None
        for key, clip in scene_input.items():
            if isinstance(key, FixtureGroup):
                grp = key
            else:
                name = str(key)
                if name not in self.groups_by_name:
                    raise KeyError(f"Unknown fixture group {name!r}. Available: {list(self.groups_by_name)}")
                grp = self.groups_by_name[name]
            bound = grp(clip)
            combined = bound if combined is None else (combined | bound)

        if combined is None:
            raise ValueError("Empty scene mapping provided.")
        return combined

    def render_dmx(self, scene_input: SceneInput, t: float) -> list[int]:
        """Evaluate `scene_input` at time `t` into a DMX byte list."""
        scene = self._to_scene(scene_input)
        base_canvas = DMXCanvas()
        for grp in self.groups:
            grp.register_canvas_defaults(base_canvas)
        scene_canvas = scene.eval_canvas(t)
        merged = base_canvas.merge(scene_canvas, mode="override")
        max_ch = max(
            [g.max_channel for g in self.groups]
            + [g.max_channel for g in scene.groups()]
            + [24]
        )
        return merged.to_dmx_list(min_size=max_ch)

    def blackout(self, max_ch: int = 512) -> None:
        """Immediately zero all channels on the rig."""
        if not self.dry_run:
            ch_count = max([g.max_channel for g in self.groups] or [max_ch])
            self.client.send_dmx([0] * ch_count)

    def play(
        self,
        scene_input: SceneInput,
        *,
        max_duration: Optional[float] = None,
        blackout_on_exit: bool = True,
        preview: bool = False,
    ) -> None:
        """Stream `scene_input` in real time at `self.fps` over Art-Net."""
        scene = self._to_scene(scene_input)
        duration = scene.duration if max_duration is None else min(scene.duration, max_duration)
        preview_groups = list(self.groups) if self.groups else scene.groups()
        max_ch = max(
            [g.max_channel for g in self.groups]
            + [g.max_channel for g in scene.groups()]
            + [24]
        )
        frame_interval = 1.0 / self.fps
        start_time = time.monotonic()

        try:
            while True:
                now = time.monotonic()
                t = now - start_time
                if t > duration:
                    break

                dmx = self.render_dmx(scene, t)

                if not self.dry_run:
                    self.client.send_dmx(dmx)
                if preview:
                    self._print_preview_line(preview_groups, dmx, t)

                elapsed = time.monotonic() - now
                sleep_for = frame_interval - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except KeyboardInterrupt:
            if preview:
                print("\nStopped by user.")
        finally:
            if blackout_on_exit:
                self.blackout(max_ch=max_ch)
            self.client.close()

    def _print_preview_line(self, preview_groups: Sequence[FixtureGroup], dmx: Sequence[int], t: float) -> None:
        parts = [grp.preview_from_dmx(dmx) for grp in preview_groups]
        line = f"\rt={t:6.2f}s | " + " | ".join(parts)
        print(line, end="", flush=True)
