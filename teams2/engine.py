"""движок принятия решений с гистерезисом против флаппинга"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Dict

from collector import LinkMetrics


@dataclass
class Decision:
    # результат работы движка: выбранный канал и текстовое обоснование
    chosen_link: str | None
    reason: str


class DecisionEngine:
    def __init__(
        self,
        max_latency_ms: float,
        max_loss_pct: float,
        cooldown_sec: int,
        preferred_primary: str,
    ) -> None:
        # задаем пороговые значения качества и параметры стабильности
        self.max_latency_ms = max_latency_ms
        self.max_loss_pct = max_loss_pct
        self.cooldown_sec = cooldown_sec
        self.preferred_primary = preferred_primary
        # состояние: текущий активный канал и время последнего переключения
        self.active_link: str | None = None
        self.last_switch_ts: float = 0.0

    def decide(self, metrics: Dict[str, LinkMetrics]) -> Decision:
        now = time.time()
        health = {name: self._is_healthy(m) for name, m in metrics.items()}

        if self.active_link is None:
            first = self._pick_best(metrics, health)
            if first:
                self._mark_switch(first, now)
                return Decision(first, "initial selection")
            return Decision(None, "no links discovered")

        current_healthy = health.get(self.active_link, False)

        if current_healthy:
            if now - self.last_switch_ts < self.cooldown_sec:
                return Decision(self.active_link, "cooldown hold")
            # если на резерве, но основной ожил — возвращаемся
            if self.active_link != self.preferred_primary and health.get(self.preferred_primary, False):
                self._mark_switch(self.preferred_primary, now)
                return Decision(self.preferred_primary, "primary restored")
            return Decision(self.active_link, "active healthy")

        # текущий канал деградировал, но cooldown ещё не вышел — не дёргаемся
        if now - self.last_switch_ts < self.cooldown_sec:
            return Decision(self.active_link, "active unhealthy but cooldown hold")

        # ищем лучшую альтернативу
        candidate = self._pick_best(metrics, health)
        if candidate is None:
            return Decision(self.active_link, "no candidate found")
        if candidate != self.active_link:
            self._mark_switch(candidate, now)
            return Decision(candidate, "switched due to degradation")

        return Decision(self.active_link, "unchanged")

    def _is_healthy(self, m: LinkMetrics) -> bool:
        return m.is_up and m.rtt_avg_ms <= self.max_latency_ms and m.loss_pct <= self.max_loss_pct

    def _pick_best(self, metrics: Dict[str, LinkMetrics], health: Dict[str, bool]) -> str | None:
        healthy = [name for name, ok in health.items() if ok]
        if self.preferred_primary in healthy:
            return self.preferred_primary
        if healthy:
            return sorted(healthy)[0]
        # крайний случай: все каналы плохи — выбираем наименее плохой
        worst_case = sorted(metrics.values(), key=lambda x: (x.loss_pct, x.rtt_avg_ms))
        return worst_case[0].name if worst_case else None

    def _mark_switch(self, name: str, ts: float) -> None:
        self.active_link = name
        self.last_switch_ts = ts