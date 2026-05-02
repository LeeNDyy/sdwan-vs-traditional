"""менеджер управления сетевыми маршрутами через linux iproute2"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import shlex
import subprocess


@dataclass
class RouteTarget:
    # структура для хранения параметров целевого маршрута: интерфейс, шлюз и метрика
    interface: str
    gateway_ip: str
    route_metric: int


class NetworkManager:
    """выполняет `ip route replace` для переключения активного пути к целевой подсети"""

    def __init__(self, destination_cidr: str) -> None:
        self.destination_cidr = destination_cidr

    def apply_route(self, target: RouteTarget) -> bool:
        cmd = (
            f"ip route replace {self.destination_cidr} "
            f"via {shlex.quote(target.gateway_ip)} "
            f"dev {shlex.quote(target.interface)} "
            f"metric {target.route_metric}"
        )
        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
        except Exception as exc:
            logging.error("[NET] route exception: %s", exc)
            return False

        if proc.returncode != 0:
            logging.error("[NET] route command failed: %s", (proc.stderr or proc.stdout).strip())
            return False

        return True