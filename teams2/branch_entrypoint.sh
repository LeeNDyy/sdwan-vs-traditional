#!/usr/bin/env bash
# строгий режим: выход при ошибках, неопределённых переменных и ошибках в пайпах
set -euo pipefail

# переменные окружения передаются из docker-compose.yaml
BRANCH_NAME="${BRANCH_NAME:-branch_a}"
PEER_FIBER_IP="${PEER_FIBER_IP:-10.10.10.2}"
PEER_SAT_IP="${PEER_SAT_IP:-10.20.20.2}"
PEER_BRANCH_NET="${PEER_BRANCH_NET:-192.168.20.0/24}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$BRANCH_NAME] $*"
}

# базовая настройка сетевого стека
# Docker уже назначил IP-адреса через IPAM, поэтому здесь только поднимаем
# интерфейсы и прописываем маршруты до LAN удалённого филиала.
# eth1 = fiber_net, eth2 = sat_net, eth3 = branch_X_lan (уже настроен Docker)
setup_routes() {
  log "Bringing up interfaces"
  ip link set lo up   || true
  ip link set eth1 up || true
  ip link set eth2 up || true
  # eth0 — Docker default bridge (управление), eth3 — LAN (уже up)

  log "Setting routes to peer LAN: $PEER_BRANCH_NET"
  # оптика — приоритетный маршрут (metric 10)
  ip route replace "$PEER_BRANCH_NET" via "$PEER_FIBER_IP" dev eth1 metric 10  || true
  # спутник — резервный маршрут (metric 100)
  ip route replace "$PEER_BRANCH_NET" via "$PEER_SAT_IP"  dev eth2 metric 100 || true

  log "Routes configured:"
  ip route show
}

# эмуляция деградированного спутникового канала с помощью tc netem
# задержка 200 мс ± 30 мс (джиттер) + 3% потерь пакетов
# применяется на исходящий интерфейс eth2 обоих контейнеров, чтобы деградация
# была симметричной и ping из branch_a корректно показывал плохой RTT
apply_satellite_emulation() {
  if ip link show eth2 &>/dev/null; then
    log "Applying satellite emulation on eth2 (delay 200ms jitter 30ms loss 3%)"
    tc qdisc replace dev eth2 root netem delay 200ms 30ms loss 3%
  else
    log "WARN: eth2 not found, skipping satellite emulation"
  fi
}

# запуск контроллера на branch_a или перевод branch_b в режим ожидания
run_controller_if_needed() {
  if [[ "$BRANCH_NAME" == "branch_a" ]]; then
    log "Launching SD-WAN controller (Team 2)"
    exec python3 /opt/sdwan/main.py
  fi

  log "Passive branch ready — waiting for connections"
  # держим контейнер живым
  tail -f /dev/null
}

# точка входа
log "=== Initializing container ==="
setup_routes
apply_satellite_emulation
run_controller_if_needed