# File: examples/pipeline_demo.py
#
# A transaction-level pipeline example for the coroutine simulator.
# This example intentionally avoids per-cycle ticking. Each stage accepts a
# token, schedules a per-token completion task, and becomes ready for the next
# token according to its initiation interval.

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Generator, Optional

from core import HwModule, Signal, Simulator, Task


@dataclass
class Token:
    """A piece of work flowing through the demo pipeline."""

    token_id: int
    payload: int
    mode: str
    done: Signal
    trace: list[tuple[str, str, int | float]] = field(default_factory=list)


class Channel(HwModule):
    """A bounded event-driven channel between pipeline stages."""

    def __init__(
        self,
        name: str,
        sim: Simulator,
        capacity: int,
        parent: Optional[HwModule] = None,
    ):
        super().__init__(name, sim, parent)
        self.capacity = capacity
        self.queue: Deque[Any] = collections.deque()
        self.not_empty = Signal(sim)
        self.not_full = Signal(sim)

        self._register_stat("puts", 0)
        self._register_stat("gets", 0)
        self._register_stat("blocked_puts", 0)
        self._register_stat("blocked_gets", 0)
        self._register_stat("max_occupancy", 0)

    def put(self, item: Any) -> Generator[Any, Any, None]:
        while len(self.queue) >= self.capacity:
            self._increment_stat("blocked_puts")
            yield self.not_full.wait()

        self.queue.append(item)
        self._increment_stat("puts")
        self.stats["max_occupancy"] = max(self.stats["max_occupancy"], len(self.queue))
        self.not_empty.notify_one()

    def get(self) -> Generator[Any, Any, Any]:
        while not self.queue:
            self._increment_stat("blocked_gets")
            yield self.not_empty.wait()

        item = self.queue.popleft()
        self._increment_stat("gets")
        self.not_full.notify_one()
        return item


class PipelineStage(HwModule):
    """A pipelined stage with latency, initiation interval, and in-flight slots."""

    def __init__(
        self,
        name: str,
        sim: Simulator,
        latency: int,
        initiation_interval: int,
        input_channel: Channel,
        output_channel: Optional[Channel],
        transform: Callable[[Token], Token],
        max_inflight: int = 1024,
        parent: Optional[HwModule] = None,
    ):
        super().__init__(name, sim, parent)
        self.latency = latency
        self.initiation_interval = initiation_interval
        self.input_channel = input_channel
        self.output_channel = output_channel
        self.transform = transform
        self.max_inflight = max_inflight
        self.next_accept_time: int | float = 0
        self.inflight: set[int] = set()
        self.slot_available = Signal(sim)

        self._register_stat("accepted", 0)
        self._register_stat("completed", 0)
        self._register_stat("ii_wait_cycles", 0)
        self._register_stat("slot_waits", 0)
        self._register_stat("max_inflight", 0)

    def run(self) -> Generator[Any, Any, None]:
        while True:
            token: Token = yield self.input_channel.get()

            while len(self.inflight) >= self.max_inflight:
                self._increment_stat("slot_waits")
                yield self.slot_available.wait()

            wait_cycles = max(0, self.next_accept_time - self.sim.current_time)
            if wait_cycles:
                self._increment_stat("ii_wait_cycles", wait_cycles)
                yield self.sim.delay(wait_cycles)

            accept_time = self.sim.current_time
            self.next_accept_time = accept_time + self.initiation_interval
            self.inflight.add(token.token_id)
            self.stats["max_inflight"] = max(self.stats["max_inflight"], len(self.inflight))
            self._increment_stat("accepted")
            token.trace.append((self.full_name, "accept", accept_time))

            self.sim.spawn(self._complete_later, token, accept_time)

    def _complete_later(self, token: Token, accept_time: int | float) -> Generator[Any, Any, None]:
        remaining = accept_time + self.latency - self.sim.current_time
        if remaining > 0:
            yield self.sim.delay(remaining)

        token = self.transform(token)
        token.trace.append((self.full_name, "complete", self.sim.current_time))
        self._increment_stat("completed")

        if self.output_channel is None:
            token.done.notify_all(token)
        else:
            yield self.output_channel.put(token)

        self.inflight.remove(token.token_id)
        self.slot_available.notify_one()


class ToyPipelineAccelerator(HwModule):
    """A small three-stage accelerator used as the root demo device."""

    MODES = {
        "fast": {
            "load": (2, 1),
            "compute": (4, 1),
            "store": (2, 1),
        },
        "compact": {
            "load": (2, 2),
            "compute": (6, 3),
            "store": (2, 1),
        },
    }

    def __init__(self, name: str, sim: Simulator, mode: str = "fast"):
        super().__init__(name, sim)
        if mode not in self.MODES:
            raise ValueError(f"unknown mode: {mode}")

        self.mode = mode
        self.input = Channel("input", sim, capacity=4, parent=self)
        self.load_to_compute = Channel("load_to_compute", sim, capacity=2, parent=self)
        self.compute_to_store = Channel("compute_to_store", sim, capacity=2, parent=self)

        load_latency, load_ii = self.MODES[mode]["load"]
        compute_latency, compute_ii = self.MODES[mode]["compute"]
        store_latency, store_ii = self.MODES[mode]["store"]

        self.load = PipelineStage(
            "load",
            sim,
            latency=load_latency,
            initiation_interval=load_ii,
            input_channel=self.input,
            output_channel=self.load_to_compute,
            transform=self._load_transform,
            parent=self,
        )
        self.compute = PipelineStage(
            "compute",
            sim,
            latency=compute_latency,
            initiation_interval=compute_ii,
            input_channel=self.load_to_compute,
            output_channel=self.compute_to_store,
            transform=self._compute_transform,
            parent=self,
        )
        self.store = PipelineStage(
            "store",
            sim,
            latency=store_latency,
            initiation_interval=store_ii,
            input_channel=self.compute_to_store,
            output_channel=None,
            transform=self._store_transform,
            parent=self,
        )

        self._register_stat("submitted", 0)
        self._register_stat("completed", 0)

    def start(self) -> list[Task]:
        return [
            self.sim.spawn(self.load.run),
            self.sim.spawn(self.compute.run),
            self.sim.spawn(self.store.run),
        ]

    def submit(self, token_id: int, payload: int) -> Generator[Any, Any, Token]:
        token = Token(token_id=token_id, payload=payload, mode=self.mode, done=Signal(self.sim))
        token.trace.append((self.full_name, "submit", self.sim.current_time))
        self._increment_stat("submitted")

        yield self.input.put(token)
        finished: Token = yield token.done.wait()

        finished.trace.append((self.full_name, "retire", self.sim.current_time))
        self._increment_stat("completed")
        return finished

    def _load_transform(self, token: Token) -> Token:
        token.payload += 10
        return token

    def _compute_transform(self, token: Token) -> Token:
        token.payload = token.payload * 2
        return token

    def _store_transform(self, token: Token) -> Token:
        token.payload -= 3
        return token


class DemoTestbench:
    """A testbench that exercises burst traffic, joins, signals, and returns."""

    def __init__(
        self,
        sim: Simulator,
        dut: ToyPipelineAccelerator,
        first_wave_tokens: int = 8,
        second_wave_tokens: int = 3,
        gap_cycles: int = 3,
    ):
        self.sim = sim
        self.dut = dut
        self.first_wave_tokens = first_wave_tokens
        self.second_wave_tokens = second_wave_tokens
        self.gap_cycles = gap_cycles

    def run(self) -> Generator[Any, Any, list[Token]]:
        print(f"[t={self.sim.current_time:>4}] [tb] start pipeline demo, mode={self.dut.mode}")
        self.dut.start()

        first_wave = [self._submit_token(i) for i in range(self.first_wave_tokens)]
        first_results: list[Token] = yield first_wave
        print(f"[t={self.sim.current_time:>4}] [tb] first wave joined, count={len(first_results)}")

        yield self.sim.delay(self.gap_cycles)

        base_id = self.first_wave_tokens
        second_wave = [
            self._submit_token(base_id + i) for i in range(self.second_wave_tokens)
        ]
        second_results: list[Token] = yield second_wave
        print(f"[t={self.sim.current_time:>4}] [tb] second wave joined, count={len(second_results)}")

        return first_results + second_results

    def _submit_token(self, token_id: int) -> Task:
        payload = token_id + 1
        return self.sim.spawn(self.dut.submit, token_id=token_id, payload=payload)


def expected_payload(input_payload: int) -> int:
    return (input_payload + 10) * 2 - 3


def format_token_trace(token: Token) -> str:
    parts = [f"{module}:{event}@{time}" for module, event, time in token.trace]
    return " -> ".join(parts)
