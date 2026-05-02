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
    # класс для выполнения команд изменения таблицы маршрутизации linux
    def __init__(self, destination_cidr: str) -> None:
        # инициализация менеджера с указанием целевой подсети, для которой будем менять пути
        self.destination_cidr = destination_cidr

    def apply_route(self, target: RouteTarget) -> bool:
        # метод для физической смены маршрута в системе через вызов ip route
        # формируем команду замены маршрута, используя shlex для безопасного экранирования аргументов
        cmd = (
            f"ip route replace {self.destination_cidr} "
            f"via {shlex.quote(target.gateway_ip)} dev {shlex.quote(target.interface)} "
            f"metric {target.route_metric}"
        )
        try:
            # выполняем команду в системной оболочке и перехватываем вывод для анализа
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
        except Exception as exc:
            # обработка системных ошибок, например, если утилита ip отсутствует
            logging.error("[NET] route exception: %s", exc)
            return False

        if proc.returncode != 0:
            # если команда вернула ошибку (например, из-за прав доступа), логируем причину
            logging.error("[NET] route command failed: %s", (proc.stderr or proc.stdout).strip())
            return False
        
        # возвращаем истину при успешном обновлении таблицы маршрутизации
        return True