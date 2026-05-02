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
    # формат Ubuntu: rtt min/avg/max/mdev = 0.123/0.456/0.789/0.100 ms
    RTT_PATTERN = re.compile(r"rtt [^=]+=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)")
    LOSS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)%\s*packet\s*loss")

    def __init__(self, count: int = 4, timeout_sec: int = 3) -> None:
        # count  — количество ICMP-пакетов за одну серию
        # timeout_sec — deadline на ВСЮ серию (флаг -w в iputils-ping Ubuntu)
        #               для 4 пакетов с интервалом 0.2s на спутнике (200ms RTT)
        #               нужно минимум ~2.5s; берём 3 с запасом
        self.count = count
        self.timeout_sec = timeout_sec

    def collect(self, target: ProbeTarget) -> LinkMetrics:
        # -I  — привязка к конкретному исходящему интерфейсу
        # -c  — количество пакетов
        # -i  — интервал между пакетами (0.2s ускоряет серию)
        # -w  — deadline в секундах для всей команды (iputils-ping / Ubuntu)
        # -W  — timeout ожидания ответа на каждый пакет в секундах
        cmd = (
            f"ping -I {shlex.quote(target.interface)}"
            f" -c {self.count}"
            f" -i 0.2"
            f" -W {self.timeout_sec}"
            f" -w {self.count * self.timeout_sec}"
            f" {shlex.quote(target.probe_ip)}"
        )
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            return LinkMetrics(target.name, 9999.0, 100.0, False, f"ping exception: {exc}")

        output = (proc.stdout or "") + (proc.stderr or "")
        rtt = self._parse_rtt_avg(output)
        loss = self._parse_loss(output)

        if rtt is None:
            rtt = 9999.0
        if loss is None:
            loss = 100.0

        return LinkMetrics(
            name=target.name,
            rtt_avg_ms=rtt,
            loss_pct=loss,
            is_up=proc.returncode == 0 and loss < 100.0,
            raw_output=output.strip(),
        )

    def _parse_rtt_avg(self, output: str) -> float | None:
        # берём второе число (avg) из строки "rtt min/avg/max/mdev = ..."
        match = self.RTT_PATTERN.search(output)
        return float(match.group(2)) if match else None

    def _parse_loss(self, output: str) -> float | None:
        match = self.LOSS_PATTERN.search(output)
        return float(match.group(1)) if match else None