#!/usr/bin/env python3
"""основной файл запуска контроллера sd-wan для команды 2"""

from __future__ import annotations

from dataclasses import dataclass
import logging
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
    # настройка формата логов с временем для наглядности на демонстрации
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_links() -> dict[str, LinkDefinition]:
    # конфигурация доступных каналов связи: оптика и спутник
    return {
        "fiber": LinkDefinition(
            name="fiber",
            probe=ProbeTarget(name="fiber", interface="a_fiber", probe_ip="10.0.10.2"),
            route=RouteTarget(interface="a_fiber", gateway_ip="10.0.10.2", route_metric=10),
        ),
        "satellite": LinkDefinition(
            name="satellite",
            probe=ProbeTarget(name="satellite", interface="a_sat", probe_ip="10.0.20.2"),
            route=RouteTarget(interface="a_sat", gateway_ip="10.0.20.2", route_metric=100),
        ),
    }


def run() -> None:
    # инициализация основных компонентов системы
    links = build_links()
    collector = MetricCollector(count=4, timeout_sec=2)
    # параметры: rtt 50мс, потери 5%, кулдаун 15с, приоритет у оптики
    engine = DecisionEngine(50.0, 5.0, 15, "fiber")
    net = NetworkManager(destination_cidr="172.16.2.0/24")
    applied: str | None = None

    logging.info("[CTRL] Team2 SD-WAN controller started")
    while True:
        try:
            # опрос всех настроенных каналов для получения свежих метрик
            metrics = {name: collector.collect(ld.probe) for name, ld in links.items()}
            
            # вывод текущего состояния каналов в консоль
            for metric in metrics.values():
                logging.info(
                    "[METRIC] %s up=%s rtt=%.2fms loss=%.2f%%",
                    metric.name,
                    metric.is_up,
                    metric.rtt_avg_ms,
                    metric.loss_pct,
                )
            
            # анализ метрик и выбор оптимального маршрута через движок логики
            decision = engine.decide(metrics)
            chosen = decision.chosen_link
            
            if chosen is None:
                # обработка ситуации когда нет ни одного живого пути
                logging.warning("[DECISION] %s", decision.reason)
            elif applied != chosen:
                # выполнение команды переключения если выбор изменился
                if net.apply_route(links[chosen].route):
                    logging.warning("[DECISION] switch => %s (%s)", chosen.upper(), decision.reason)
                    applied = chosen
            else:
                # уведомление что текущий путь остается оптимальным
                logging.info("[DECISION] keep %s (%s)", chosen.upper(), decision.reason)
        
        except Exception as exc:
            # защита от падения всего контроллера при непредвиденных ошибках
            logging.exception("[CTRL] loop exception: %s", exc)

        # задержка перед следующей итерацией мониторинга
        time.sleep(5)


if __name__ == "__main__":
    configure_logging()
    run()