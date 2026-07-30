from datetime import datetime, timezone
from typing import Dict, List, Optional
import asyncio
from pydantic import BaseModel, Field

from apps.gateway.providers.registry import ProviderRegistry
from packages.plugin_sdk import ProviderHealthResponse
from packages.shared.logging.logger import get_logger

logger = get_logger("provider_health_monitor")


class ProviderHealthMetric(BaseModel):
    """Health metrics for an individual LLM Provider."""

    provider_name: str
    status: str = "online"  # "online", "degraded", "offline"
    latency_ms: Optional[float] = 0.0
    success_rate: float = 100.0  # 0.0 - 100.0%
    error_rate: float = 0.0  # 0.0 - 100.0%
    availability_score: float = 100.0  # 0.0 - 100.0%
    total_requests: int = 0
    total_errors: int = 0
    total_successes: int = 0
    last_successful_request: Optional[datetime] = None
    rate_limit_remaining: Optional[int] = 1000
    is_rate_limited: bool = False
    last_checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProviderHealthMonitor:
    """Background monitor and metrics recorder for LLM Provider health & routing decisions."""

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry
        self._metrics: Dict[str, ProviderHealthMetric] = {}
        self._is_running: bool = False
        self._monitor_task: Optional[asyncio.Task] = None

    def get_metrics(self, provider_name: str) -> ProviderHealthMetric:
        """Get metric snapshot for a given provider."""
        key = provider_name.lower()
        if key not in self._metrics:
            self._metrics[key] = ProviderHealthMetric(provider_name=key)
        return self._metrics[key]

    def record_request_result(
        self,
        provider_name: str,
        success: bool,
        latency_ms: float,
        is_rate_limit: bool = False,
    ) -> None:
        """Record real-time execution outcome for dynamic error/success rate and rate limit tracking."""
        key = provider_name.lower()
        metric = self.get_metrics(key)
        now = datetime.now(timezone.utc)

        metric.total_requests += 1
        metric.latency_ms = round((metric.latency_ms + latency_ms) / 2, 2) if metric.latency_ms else latency_ms
        metric.last_checked_at = now

        if success:
            metric.total_successes += 1
            metric.last_successful_request = now
        else:
            metric.total_errors += 1

        if is_rate_limit:
            metric.is_rate_limited = True
            metric.status = "degraded"
        else:
            metric.is_rate_limited = False

        # Calculate error rate & success rate
        err_fraction = metric.total_errors / metric.total_requests
        metric.error_rate = round(err_fraction * 100.0, 2)
        metric.success_rate = round(100.0 - metric.error_rate, 2)
        metric.availability_score = metric.success_rate

        if metric.error_rate > 50.0:
            metric.status = "offline"
        elif metric.error_rate > 10.0 or metric.is_rate_limited:
            metric.status = "degraded"
        else:
            metric.status = "online"

    async def run_health_check_round(self) -> Dict[str, ProviderHealthMetric]:
        """Perform a background polling round across all providers."""
        health_responses = await self.registry.check_all_health()

        for name, response in health_responses.items():
            metric = self.get_metrics(name)
            metric.last_checked_at = datetime.now(timezone.utc)

            if response.status == "ok":
                metric.status = "online" if metric.error_rate < 10.0 else metric.status
                if response.latency_ms is not None:
                    metric.latency_ms = response.latency_ms
            elif response.status == "degraded":
                metric.status = "degraded"
            else:
                metric.status = "offline"

        logger.info(f"Health check round completed for {len(health_responses)} providers.")
        return self._metrics

    def get_healthiest_provider(self, candidates: List[str]) -> Optional[str]:
        """Select the healthiest provider from candidates based on status, error rate, and latency."""
        eligible = []
        for name in candidates:
            key = name.lower()
            if not self.registry.is_enabled(key):
                continue
            metric = self.get_metrics(key)
            if metric.status != "offline" and not metric.is_rate_limited:
                eligible.append((key, metric.error_rate, metric.latency_ms or 9999.0))

        if not eligible:
            return None

        eligible.sort(key=lambda x: (x[1], x[2]))
        return eligible[0][0]

    async def start_background_monitoring(self, interval_seconds: int = 30) -> None:
        """Start recurring background monitoring task."""
        self._is_running = True

        async def _loop():
            while self._is_running:
                try:
                    await self.run_health_check_round()
                except Exception as e:
                    logger.error(f"Error in health monitor background loop: {e}")
                await asyncio.sleep(interval_seconds)

        self._monitor_task = asyncio.create_task(_loop())
        logger.info(f"Started provider health monitoring background loop (interval={interval_seconds}s)")

    def stop_background_monitoring(self) -> None:
        """Stop background monitoring task."""
        self._is_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            logger.info("Stopped provider health monitoring background loop")
