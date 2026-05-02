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
    # интерфейсы в Docker: eth1 = fiber_net, eth2 = sat_net
    # шлюзы берём из docker-compose.yaml (адреса branch_b в каждой сети)
    return {
        "fiber": LinkDefinition(
            name="fiber",
            probe=ProbeTarget(name="fiber", interface="eth1", probe_ip="10.10.10.2"),
            route=RouteTarget(interface="eth1", gateway_ip="10.10.10.2", route_metric=10),
        ),
        "satellite": LinkDefinition(
            name="satellite",
            probe=ProbeTarget(name="satellite", interface="eth2", probe_ip="10.20.20.2"),
            route=RouteTarget(interface="eth2", gateway_ip="10.20.20.2", route_metric=100),
        ),
    }


def run() -> None:
    # инициализация основных компонентов системы
    links = build_links()
    collector = MetricCollector(count=4, timeout_sec=3)

    # параметры движка:
    #   max_latency_ms=400  — оптика обычно <5ms, спутник ~200ms, порог взят с запасом
    #                         чтобы не переключаться на здоровой оптике, но реагировать
    #                         на полный обрыв (9999ms)
    #   max_loss_pct=10     — спутник эмулирует 3% потерь, порог 10% позволяет ему
    #                         считаться «здоровым резервом» при живой оптике
    #   cooldown_sec=15     — защита от флаппинга: после переключения ждём 15 секунд
    #   preferred_primary   — при восстановлении всегда возвращаемся на оптику
    engine = DecisionEngine(
        max_latency_ms=400.0,
        max_loss_pct=10.0,
        cooldown_sec=15,
        preferred_primary="fiber",
    )

    # целевая подсеть branch_b LAN, маршрут до которой контроллер переключает
    net = NetworkManager(destination_cidr="192.168.20.0/24")
    applied: str | None = None

    logging.info("[CTRL] Team2 SD-WAN controller started")
    while True:
        try:
            # опрос всех настроенных каналов для получения свежих метрик
            metrics = {name: collector.collect(ld.probe) for name, ld in links.items()}

            # вывод текущего состояния каналов в консоль
            for metric in metrics.values():
                logging.info(
                    "[METRIC] %-10s up=%-5s rtt=%7.1fms loss=%.1f%%",
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
                logging.warning("[DECISION] no path available — %s", decision.reason)
            elif applied != chosen:
                # выполнение команды переключения если выбор изменился
                if net.apply_route(links[chosen].route):
                    logging.warning(
                        "[DECISION] *** switch => %s (%s) ***",
                        chosen.upper(),
                        decision.reason,
                    )
                    applied = chosen
            else:
                # уведомление что текущий путь остается оптимальным
                logging.info("[DECISION] keep %-10s (%s)", chosen.upper(), decision.reason)

        except Exception as exc:
            # защита от падения всего контроллера при непредвиденных ошибках
            logging.exception("[CTRL] loop exception: %s", exc)

        # задержка перед следующей итерацией мониторинга
        time.sleep(5)


if __name__ == "__main__":
    configure_logging()
    run()