from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator

import numpy as np


@dataclass(slots=True)
class AudioUtterance:
    samples: np.ndarray
    start_ms: int
    end_ms: int


class MicrophoneStream:
    def __init__(
        self,
        sample_rate: int = 16_000,
        block_size: int = 512,
        device: int | str | None = None,
    ):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.device = device
        self.dropped_frames = 0

    async def frames(self) -> AsyncIterator[np.ndarray]:
        import sounddevice as sd

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=256)

        def enqueue(frame: np.ndarray) -> None:
            if queue.full():
                queue.get_nowait()
                self.dropped_frames += 1
            queue.put_nowait(frame)

        def callback(indata: np.ndarray, _frames: int, _time: object, status: object) -> None:
            if status:
                loop.call_soon_threadsafe(print, f"[audio] {status}")
            frame = np.asarray(indata[:, 0], dtype=np.float32).copy()
            loop.call_soon_threadsafe(enqueue, frame)

        with sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            device=self.device,
            channels=1,
            dtype="float32",
            callback=callback,
        ):
            while True:
                yield await queue.get()


class UtteranceDetector:
    def __init__(
        self,
        sample_rate: int = 16_000,
        threshold: float = 0.5,
        min_silence_ms: int = 800,
        speech_pad_ms: int = 200,
        max_utterance_seconds: float = 30.0,
    ):
        from silero_vad import VADIterator, load_silero_vad

        self.sample_rate = sample_rate
        self.vad = VADIterator(
            load_silero_vad(onnx=True),
            threshold=threshold,
            sampling_rate=sample_rate,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        pre_roll_frames = max(1, int((speech_pad_ms / 1000) * sample_rate / 512))
        self.pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_frames)
        self.active = False
        self.buffers: list[np.ndarray] = []
        self.buffered_samples = 0
        self.total_samples = 0
        self.utterance_start_sample = 0
        self.max_samples = int(max_utterance_seconds * sample_rate)

    def push(self, frame: np.ndarray) -> AudioUtterance | None:
        frame = np.asarray(frame, dtype=np.float32).reshape(-1)
        self.total_samples += len(frame)

        if not self.active:
            self.pre_roll.append(frame.copy())

        event = self.vad(frame)
        just_started = bool(event and "start" in event and not self.active)
        if just_started:
            self.active = True
            self.buffers = list(self.pre_roll)
            buffered_samples = sum(len(chunk) for chunk in self.buffers)
            self.buffered_samples = buffered_samples
            self.utterance_start_sample = max(0, self.total_samples - buffered_samples)
        elif self.active:
            self.buffers.append(frame.copy())
            self.buffered_samples += len(frame)

        ended = bool(event and "end" in event and self.active)
        forced = self.active and self.buffered_samples >= self.max_samples
        if not ended and not forced:
            return None

        samples = np.concatenate(self.buffers).astype(np.float32, copy=False)
        start_ms = int(self.utterance_start_sample * 1000 / self.sample_rate)
        end_ms = int(self.total_samples * 1000 / self.sample_rate)
        self.active = False
        self.buffers = []
        self.buffered_samples = 0
        self.pre_roll.clear()
        if forced:
            self.vad.reset_states()
        return AudioUtterance(samples=samples, start_ms=start_ms, end_ms=end_ms)


def input_devices() -> list[tuple[int, str, int]]:
    import sounddevice as sd

    devices: list[tuple[int, str, int]] = []
    for index, device in enumerate(sd.query_devices()):
        channels = int(device["max_input_channels"])
        if channels > 0:
            devices.append((index, str(device["name"]), channels))
    return devices
