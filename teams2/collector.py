"""модуль сбора метрик для контроллера sd-wan"""

from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
import subprocess


@dataclass
class LinkMetrics:
    # структура для хранения результатов измерений канала
    name: str
    rtt_avg_ms: float
    loss_pct: float
    is_up: bool
    raw_output: str = ""


@dataclass
class ProbeTarget:
    # описание цели для проверки через конкретный интерфейс
    name: str
    interface: str
    probe_ip: str


class MetricCollector:
    """сборщик icmp метрик rtt и потерь пакетов через заданный интерфейс"""

    # регулярные выражения для извлечения среднего rtt и процента потерь из вывода ping
    RTT_PATTERN = re.compile(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/")
    LOSS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)%\s*packet\s*loss")

    def __init__(self, count: int = 4, timeout_sec: int = 2) -> None:
        # задаем количество пакетов в серии и время ожидания ответа
        self.count = count
        self.timeout_sec = timeout_sec

    def collect(self, target: ProbeTarget) -> LinkMetrics:
        # формируем безопасную команду ping с жесткой привязкой к выходному интерфейсу
        cmd = (
            f"ping -I {shlex.quote(target.interface)} -c {self.count} "
            f"-W {self.timeout_sec} {shlex.quote(target.probe_ip)}"
        )
        try:
            # выполняем команду в подпроцессе и перехватываем текстовый вывод
            proc = subprocess.run(
                cmd,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            # в случае системной ошибки возвращаем метрики "канал полностью упал"
            return LinkMetrics(target.name, 9999.0, 100.0, False, f"ping exception: {exc}")

        # объединяем стандартный вывод и ошибки для последующего парсинга
        output = (proc.stdout or "") + (proc.stderr or "")
        rtt = self._parse_rtt_avg(output)
        loss = self._parse_loss(output)

        # если данные не удалось извлечь, выставляем максимально плохие значения
        if rtt is None:
            rtt = 9999.0
        if loss is None:
            loss = 100.0

        # формируем итоговый объект с метриками и проверкой доступности канала
        return LinkMetrics(
            name=target.name,
            rtt_avg_ms=rtt,
            loss_pct=loss,
            is_up=proc.returncode == 0 and loss < 100.0,
            raw_output=output.strip(),
        )

    def _parse_rtt_avg(self, output: str) -> float | None:
        # ищем в выводе строку со статистикой времени отклика и берем среднее значение
        match = self.RTT_PATTERN.search(output)
        return float(match.group(2)) if match else None

    def _parse_loss(self, output: str) -> float | None:
        # ищем строку с процентом потерянных пакетов
        match = self.LOSS_PATTERN.search(output)
        return float(match.group(1)) if match else None