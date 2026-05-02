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
    # Имена интерфейсов и IP шлюзов передаются из branch_entrypoint.sh через env.
    # Это важно: Docker не гарантирует порядок ethX, поэтому нельзя хардкодить.
    fiber_iface  = os.environ.get("FIBER_IFACE",   "eth1")
    sat_iface    = os.environ.get("SAT_IFACE",     "eth2")
    peer_fiber   = os.environ.get("PEER_FIBER_IP", "172.31.10.2")
    peer_sat     = os.environ.get("PEER_SAT_IP",   "172.31.20.2")
    peer_net     = os.environ.get("PEER_BRANCH_NET","172.31.200.0/24")

    logging.info("[CTRL] fiber=%s via %s | satellite=%s via %s | dst=%s",
                 fiber_iface, peer_fiber, sat_iface, peer_sat, peer_net)

    return {
        "fiber": LinkDefinition(
            name="fiber",
            probe=ProbeTarget(name="fiber", interface=fiber_iface, probe_ip=peer_fiber),
            route=RouteTarget(interface=fiber_iface, gateway_ip=peer_fiber, route_metric=10),
        ),
        "satellite": LinkDefinition(
            name="satellite",
            probe=ProbeTarget(name="satellite", interface=sat_iface, probe_ip=peer_sat),
            route=RouteTarget(interface=sat_iface, gateway_ip=peer_sat, route_metric=100),
        ),
    }, peer_net


def run() -> None:
    links, peer_net = build_links()
    collector = MetricCollector(count=4, timeout_sec=3)
    engine = DecisionEngine(
        max_latency_ms=400.0,
        max_loss_pct=10.0,
        cooldown_sec=15,
        preferred_primary="fiber",
    )
    net = NetworkManager(destination_cidr=peer_net)
    applied: str | None = None

    logging.info("[CTRL] Team2 SD-WAN controller started")
    while True:
        try:
            metrics = {name: collector.collect(ld.probe) for name, ld in links.items()}

            for metric in metrics.values():
                logging.info(
                    "[METRIC] %-10s up=%-5s rtt=%7.1fms loss=%.1f%%",
                    metric.name, metric.is_up, metric.rtt_avg_ms, metric.loss_pct,
                )

            decision = engine.decide(metrics)
            chosen = decision.chosen_link

            if chosen is None:
                logging.warning("[DECISION] no path available — %s", decision.reason)
            elif applied != chosen:
                if net.apply_route(links[chosen].route):
                    logging.warning("[DECISION] *** switch => %s (%s) ***",
                                    chosen.upper(), decision.reason)
                    applied = chosen
            else:
                logging.info("[DECISION] keep %-10s (%s)", chosen.upper(), decision.reason)

        except Exception as exc:
            logging.exception("[CTRL] loop exception: %s", exc)

        time.sleep(5)


if __name__ == "__main__":
    configure_logging()
    run()