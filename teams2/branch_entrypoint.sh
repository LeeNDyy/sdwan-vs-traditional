#!/usr/bin/env bash
set -euo pipefail

BRANCH_NAME="${BRANCH_NAME:-branch_a}"
PEER_FIBER_IP="${PEER_FIBER_IP:-172.31.10.2}"
PEER_SAT_IP="${PEER_SAT_IP:-172.31.20.2}"
PEER_BRANCH_NET="${PEER_BRANCH_NET:-172.31.200.0/24}"

# собственные IP на fiber/sat — нужны чтобы найти интерфейс по адресу
if [[ "$BRANCH_NAME" == "branch_a" ]]; then
  OWN_FIBER_IP="172.31.10.1"
  OWN_SAT_IP="172.31.20.1"
else
  OWN_FIBER_IP="172.31.10.2"
  OWN_SAT_IP="172.31.20.2"
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$BRANCH_NAME] $*"; }

# Найти имя интерфейса по IP-адресу.
# Docker не гарантирует порядок ethX, поэтому хардкодить нельзя.
find_iface_by_ip() {
  local target_ip="$1"
  ip -o addr show | awk -v ip="$target_ip" '$4 ~ "^" ip "/" {print $2}' | head -1
}

setup_routes() {
  log "Bringing up interfaces"
  ip link set lo up || true
  for iface in $(ip -o link show | awk -F': ' '{print $2}' | grep -E '^eth[1-9]$'); do
    ip link set "$iface" up 2>/dev/null || true
  done

  log "Discovering interfaces by IP"
  local retries=10
  while [[ $retries -gt 0 ]]; do
    FIBER_IFACE=$(find_iface_by_ip "$OWN_FIBER_IP")
    SAT_IFACE=$(find_iface_by_ip "$OWN_SAT_IP")
    [[ -n "$FIBER_IFACE" && -n "$SAT_IFACE" ]] && break
    log "Waiting for IPs... ($retries)"
    sleep 1
    retries=$((retries - 1))
  done

  if [[ -z "${FIBER_IFACE:-}" || -z "${SAT_IFACE:-}" ]]; then
    log "ERROR: interfaces not found. Address table:"
    ip -o addr show
    exit 1
  fi

  log "FIBER_IFACE=$FIBER_IFACE  SAT_IFACE=$SAT_IFACE"
  export FIBER_IFACE SAT_IFACE

  log "Setting routes to $PEER_BRANCH_NET"
  ip route replace "$PEER_BRANCH_NET" via "$PEER_FIBER_IP" dev "$FIBER_IFACE" metric 10
  ip route replace "$PEER_BRANCH_NET" via "$PEER_SAT_IP"  dev "$SAT_IFACE"   metric 100

  log "Routing table:"
  ip route show
}

apply_satellite_emulation() {
  log "tc netem on $SAT_IFACE: delay 200ms jitter 30ms loss 3%"
  tc qdisc replace dev "$SAT_IFACE" root netem delay 200ms 30ms loss 3%
}

run_controller_if_needed() {
  if [[ "$BRANCH_NAME" == "branch_a" ]]; then
    log "Launching SD-WAN controller"
    exec python3 /opt/sdwan/main.py
  fi
  log "Passive branch ready"
  tail -f /dev/null
}

log "=== Init ==="
setup_routes
apply_satellite_emulation
run_controller_if_needed