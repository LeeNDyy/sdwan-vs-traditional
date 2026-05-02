#!/usr/bin/env bash
# строгий режим: выход при ошибках, неопределённых переменных и ошибках в пайпах
set -euo pipefail

# переменные окружения передаются из docker-compose.yaml
BRANCH_NAME="${BRANCH_NAME:-branch_a}"
PEER_FIBER_IP="${PEER_FIBER_IP:-10.10.10.2}"
PEER_SAT_IP="${PEER_SAT_IP:-10.20.20.2}"
PEER_BRANCH_NET="${PEER_BRANCH_NET:-192.168.20.0/24}"

# собственные IP на fiber и sat сетях (нужны для поиска интерфейса)
# branch_a: 10.10.10.1 / 10.20.20.1 ; branch_b: 10.10.10.2 / 10.20.20.2
if [[ "$BRANCH_NAME" == "branch_a" ]]; then
  OWN_FIBER_IP="10.10.10.1"
  OWN_SAT_IP="10.20.20.1"
else
  OWN_FIBER_IP="10.10.10.2"
  OWN_SAT_IP="10.20.20.2"
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$BRANCH_NAME] $*"
}

# Найти имя интерфейса по назначенному на него IP-адресу.
# Docker не гарантирует порядок ethX — он зависит от очерёдности attach сетей.
# Поэтому ищем интерфейс через `ip -o addr`, а не хардкодим eth1/eth2.
find_iface_by_ip() {
  local target_ip="$1"
  ip -o addr show | awk -v ip="$target_ip" '$4 ~ "^" ip "/" {print $2}' | head -1
}

# Настройка маршрутов.
# Интерфейсы находим динамически, потом экспортируем как FIBER_IFACE / SAT_IFACE
# чтобы apply_satellite_emulation и run_controller могли их использовать.
setup_routes() {
  log "Bringing up all interfaces"
  ip link set lo up || true
  # поднимаем все ethX кроме eth0 (Docker management bridge)
  for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep '^eth[1-9]'); do
    ip link set "$iface" up || true
  done

  log "Discovering interfaces by IP address"
  # ждём пока ядро присвоит адреса (обычно мгновенно, но на медленных машинах бывает задержка)
  local retries=10
  while [[ $retries -gt 0 ]]; do
    FIBER_IFACE=$(find_iface_by_ip "$OWN_FIBER_IP")
    SAT_IFACE=$(find_iface_by_ip "$OWN_SAT_IP")
    if [[ -n "$FIBER_IFACE" && -n "$SAT_IFACE" ]]; then
      break
    fi
    log "Waiting for IP addresses to appear... ($retries retries left)"
    sleep 1
    retries=$((retries - 1))
  done

  if [[ -z "$FIBER_IFACE" || -z "$SAT_IFACE" ]]; then
    log "ERROR: Could not find interfaces for IPs $OWN_FIBER_IP / $OWN_SAT_IP"
    log "Current address table:"
    ip -o addr show
    exit 1
  fi

  log "Resolved: FIBER_IFACE=$FIBER_IFACE (IP $OWN_FIBER_IP), SAT_IFACE=$SAT_IFACE (IP $OWN_SAT_IP)"
  export FIBER_IFACE SAT_IFACE

  log "Setting routes to peer LAN: $PEER_BRANCH_NET"
  # оптика — приоритетный маршрут (metric 10)
  ip route replace "$PEER_BRANCH_NET" via "$PEER_FIBER_IP" dev "$FIBER_IFACE" metric 10
  # спутник — резервный маршрут (metric 100)
  ip route replace "$PEER_BRANCH_NET" via "$PEER_SAT_IP"  dev "$SAT_IFACE"   metric 100

  log "Routes configured:"
  ip route show
}

# Эмуляция деградированного спутникового канала через tc netem.
# Применяется на исходящий SAT-интерфейс обоих контейнеров — деградация симметрична.
apply_satellite_emulation() {
  log "Applying satellite emulation on $SAT_IFACE (delay 200ms jitter 30ms loss 3%)"
  tc qdisc replace dev "$SAT_IFACE" root netem delay 200ms 30ms loss 3%
}

# Запуск контроллера на branch_a или режим ожидания на branch_b.
# Передаём найденные имена интерфейсов через env, чтобы main.py мог их использовать.
run_controller_if_needed() {
  if [[ "$BRANCH_NAME" == "branch_a" ]]; then
    log "Launching SD-WAN controller (Team 2)"
    exec python3 /opt/sdwan/main.py
  fi

  log "Passive branch ready — waiting for connections"
  tail -f /dev/null
}

# Точка входа
log "=== Initializing container ==="
setup_routes
apply_satellite_emulation
run_controller_if_needed