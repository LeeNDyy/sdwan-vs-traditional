#!/usr/bin/env bash
# строгий режим выполнения скрипта
set -euo pipefail

# учебный стенд sd-wan на базе linux namespaces и veth пар
# требуются права root для создания пространств имён, интерфейсов, маршрутов и правил tc

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SETUP] $*"
}

cleanup() {
  log "Cleaning previous lab (if exists)..."
  ip netns del branch_a 2>/dev/null || true
  ip netns del branch_b 2>/dev/null || true
  ip netns del inet     2>/dev/null || true
}

create_topology() {
  log "Creating namespaces"
  ip netns add branch_a
  ip netns add branch_b
  ip netns add inet

  log "Creating veth pairs (fiber + satellite + lan)"
  ip link add a_fiber type veth peer name b_fiber
  ip link add a_sat   type veth peer name b_sat
  ip link add a_lan   type veth peer name inet_a
  ip link add b_lan   type veth peer name inet_b

  log "Moving interfaces to namespaces"
  ip link set a_fiber netns branch_a
  ip link set a_sat   netns branch_a
  ip link set a_lan   netns branch_a

  ip link set b_fiber netns branch_b
  ip link set b_sat   netns branch_b
  ip link set b_lan   netns branch_b

  ip link set inet_a netns inet
  ip link set inet_b netns inet
}

configure_ips() {
  log "Configuring IP addresses"

  # оптический канал
  ip -n branch_a addr add 10.0.10.1/30 dev a_fiber
  ip -n branch_b addr add 10.0.10.2/30 dev b_fiber

  # спутниковый канал
  ip -n branch_a addr add 10.0.20.1/30 dev a_sat
  ip -n branch_b addr add 10.0.20.2/30 dev b_sat

  # LAN-интерфейсы филиалов
  ip -n branch_a addr add 172.16.1.2/24 dev a_lan
  ip -n branch_b addr add 172.16.2.2/24 dev b_lan

  # шлюзы в «интернет»-неймспейсе
  ip -n inet addr add 172.16.1.1/24 dev inet_a
  ip -n inet addr add 172.16.2.1/24 dev inet_b

  log "Bringing interfaces + loopbacks up"
  for ns in branch_a branch_b inet; do
    ip -n "$ns" link set lo up
  done

  for dev in a_fiber a_sat a_lan; do
    ip -n branch_a link set "$dev" up
  done

  for dev in b_fiber b_sat b_lan; do
    ip -n branch_b link set "$dev" up
  done

  ip -n inet link set inet_a up
  ip -n inet link set inet_b up
}

configure_routes() {
  log "Setting routes"

  # branch_a → branch_b LAN: оптика приоритетнее (metric 10 vs 100)
  ip -n branch_a route replace 172.16.2.0/24 via 10.0.10.2 dev a_fiber metric 10
  ip -n branch_a route replace 172.16.2.0/24 via 10.0.20.2 dev a_sat   metric 100

  # branch_b → branch_a LAN
  ip -n branch_b route replace 172.16.1.0/24 via 10.0.10.1 dev b_fiber metric 10
  ip -n branch_b route replace 172.16.1.0/24 via 10.0.20.1 dev b_sat   metric 100

  # default gateway для выхода «в интернет»
  ip -n branch_a route replace default via 172.16.1.1 dev a_lan
  ip -n branch_b route replace default via 172.16.2.1 dev b_lan
}

enable_forwarding() {
  # ВАЖНО: без этого namespace inet не будет пересылать пакеты между
  # подсетями 172.16.1.0/24 и 172.16.2.0/24
  log "Enabling IP forwarding in inet namespace"
  ip netns exec inet sysctl -qw net.ipv4.ip_forward=1
}

apply_satellite_impairment() {
  log "Applying satellite emulation: delay 200ms jitter 30ms loss 3%"
  # деградация симметричная — на исходящих интерфейсах обоих филиалов
  ip netns exec branch_a tc qdisc replace dev a_sat root netem delay 200ms 30ms loss 3%
  ip netns exec branch_b tc qdisc replace dev b_sat root netem delay 200ms 30ms loss 3%
}

show_status() {
  log "Branch A routes:"
  ip -n branch_a route show
  log "Branch B routes:"
  ip -n branch_b route show
}

run_controller() {
  log "Starting SD-WAN controller in branch_a namespace"
  log "(Press Ctrl+C to stop)"
  # запускаем контроллер внутри namespace branch_a
  # интерфейсы здесь называются a_fiber и a_sat (не eth1/eth2 как в Docker)
  PEER_FIBER_IP=10.0.10.2 \
  PEER_SAT_IP=10.0.20.2   \
  PEER_BRANCH_NET=172.16.2.0/24 \
  ip netns exec branch_a python3 "$(dirname "$0")/main_ns.py"
}

case "${1:-up}" in
  up)
    cleanup
    create_topology
    configure_ips
    configure_routes
    enable_forwarding
    apply_satellite_impairment
    show_status
    log "Lab is ready. Run 'sudo bash setup_env.sh ctrl' to start the controller."
    ;;
  ctrl)
    run_controller
    ;;
  down)
    cleanup
    log "Lab removed"
    ;;
  *)
    echo "Usage: $0 [up|ctrl|down]"
    exit 1
    ;;
esac