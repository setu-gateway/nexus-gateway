from typing import Dict
import time


class RequestTimeline:
    """Records stage-by-stage elapsed time for a single request (Epic 4.7): received ->
    routed -> provider call -> (streaming started) -> completed. Millisecond offsets
    from request start, not wall-clock timestamps, so the timeline reads directly as
    "how long did each stage take" without the reader doing subtraction."""

    def __init__(self) -> None:
        self._start = time.monotonic()
        self._stages: Dict[str, float] = {}
        self.mark("received")

    def mark(self, stage: str) -> float:
        elapsed_ms = round((time.monotonic() - self._start) * 1000, 2)
        self._stages[stage] = elapsed_ms
        return elapsed_ms

    def as_dict(self) -> Dict[str, float]:
        return dict(self._stages)

    @property
    def total_ms(self) -> float:
        return round((time.monotonic() - self._start) * 1000, 2)
