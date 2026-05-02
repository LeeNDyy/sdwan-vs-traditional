#!/usr/bin/env python3
"""основной файл запуска контроллера sd-wan для команды 2"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import time

from collector import MetricCollector, ProbeTarget
from engine import DecisionEngine
from net_manager import NetworkManager, RouteTarget


@dataclass
class LinkDefinition:
    # структура для объединения настроек мониторинга и маршрутизации одного канала
    name: str
    probe: ProbeTarget
    route: RouteTarget


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_links() -> dict[str, LinkDefinition]:
    # Имена интерфейсов определяются в branch_entrypoint.sh по IP-адресу
    # и передаются сюда через переменные окружения FIBER_IFACE / SAT_IFACE.
    # Docker не гарантирует порядок ethX, поэтому хардкодить нельзя.
    fiber_iface = os.environ.get("FIBER_IFACE", "eth1")
    sat_iface   = os.environ.get("SAT_IFACE",   "eth2")

    logging.info("[CTRL] Using interfaces: fiber=%s satellite=%s", fiber_iface, sat_iface)

    return {
        "fiber": LinkDefinition(
            name="fiber",
            probe=ProbeTarget(name="fiber", interface=fiber_iface, probe_ip="10.10.10.2"),
            route=RouteTarget(interface=fiber_iface, gateway_ip="10.10.10.2", route_metric=10),
        ),
        "satellite": LinkDefinition(
            name="satellite",
            probe=ProbeTarget(name="satellite", interface=sat_iface, probe_ip="10.20.20.2"),
            route=RouteTarget(interface=sat_iface, gateway_ip="10.20.20.2", route_metric=100),
        ),
    }


def run() -> None:
    links = build_links()
    collector = MetricCollector(count=4, timeout_sec=3)

    engine = DecisionEngine(
        max_latency_ms=400.0,
        max_loss_pct=10.0,
        cooldown_sec=15,
        preferred_primary="fiber",
    )

    net = NetworkManager(destination_cidr="192.168.20.0/24")
    applied: str | None = None

    logging.info("[CTRL] Team2 SD-WAN controller started")
    while True:
        try:
            metrics = {name: collector.collect(ld.probe) for name, ld in links.items()}

            for metric in metrics.values():
                logging.info(
                    "[METRIC] %-10s up=%-5s rtt=%7.1fms loss=%.1f%%",
                    metric.name,
                    metric.is_up,
                    metric.rtt_avg_ms,
                    metric.loss_pct,
                )

            decision = engine.decide(metrics)
            chosen = decision.chosen_link

            if chosen is None:
                logging.warning("[DECISION] no path available — %s", decision.reason)
            elif applied != chosen:
                if net.apply_route(links[chosen].route):
                    logging.warning(
                        "[DECISION] *** switch => %s (%s) ***",
                        chosen.upper(),
                        decision.reason,
                    )
                    applied = chosen
            else:
                logging.info("[DECISION] keep %-10s (%s)", chosen.upper(), decision.reason)

        except Exception as exc:
            logging.exception("[CTRL] loop exception: %s", exc)

        time.sleep(5)


if __name__ == "__main__":
    configure_logging()
    run()