#!/usr/bin/env bash
# строгий режим: выход при ошибках, неопределенных переменных и ошибках в пайпах
set -euo pipefail

# задаем переменные окружения по умолчанию для гибкости настройки
BRANCH_NAME="${BRANCH_NAME:-branch_a}"
PEER_FIBER_IP="${PEER_FIBER_IP:-10.10.10.2}"
PEER_SAT_IP="${PEER_SAT_IP:-10.20.20.2}"
PEER_BRANCH_NET="${PEER_BRANCH_NET:-192.168.20.0/24}"

# вспомогательная функция для логирования с меткой времени и именем узла
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$BRANCH_NAME] $*"
}

# функция базовой настройки сетевого стека внутри контейнера
setup_base() {
  # поднимаем локальную петлю
  ip link set lo up

  # назначаем ip адреса на интерфейсы в зависимости от того, какой это филиал
  if [[ "$BRANCH_NAME" == "branch_a" ]]; then
    # адреса для первого филиала
    ip addr add 10.10.10.1/30 dev eth1
    ip addr add 10.20.20.1/30 dev eth2
    ip addr add 192.168.10.2/24 dev eth3
  else
    # адреса для второго филиала
    ip addr add 10.10.10.2/30 dev eth1
    ip addr add 10.20.20.2/30 dev eth2
    ip addr add 192.168.20.2/24 dev eth3
  fi

  # переводим все интерфейсы в состояние up
  ip link set eth1 up
  ip link set eth2 up
  ip link set eth3 up

  # настраиваем первичные маршруты: оптика (metric 10) приоритетнее спутника (metric 100)
  ip route replace "$PEER_BRANCH_NET" via "$PEER_FIBER_IP" dev eth1 metric 10
  ip route replace "$PEER_BRANCH_NET" via "$PEER_SAT_IP" dev eth2 metric 100
}

# функция для эмуляции характеристик плохого канала связи
apply_satellite_emulation() {
  # добавляем задержку 200мс с джиттером 30мс и 3% потерь на спутниковый интерфейс
  tc qdisc replace dev eth2 root netem delay 200ms 30ms loss 3%
}

# логика запуска управляющего скрипта или переход в режим ожидания
run_controller_if_needed() {
  if [[ "$BRANCH_NAME" == "branch_a" ]]; then
    # если это первый филиал, запускаем основной python контроллер sd-wan
    log "Launching Team2 controller"
    exec python3 /opt/sdwan/main.py
  fi

  # если это пассивный филиал, просто держим контейнер запущенным
  log "Passive branch ready"
  tail -f /dev/null
}

# основной цикл выполнения скрипта инициализации
log "Initializing container"
setup_base
apply_satellite_emulation
run_controller_if_needed