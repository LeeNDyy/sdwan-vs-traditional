#!/usr/bin/env bash
# строгий режим выполнения скрипта
set -euo pipefail

# учебный стенд sd-wan на базе linux namespaces и veth пар
# требуются права root для создания пространств имен, интерфейсов, маршрутов и правил tc

log() {
  # вспомогательная функция для вывода сообщений с меткой времени
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SETUP] $*"
}

cleanup() {
  # функция очистки старых сетевых пространств перед новым запуском
  log "Cleaning previous lab (if exists)..."
  # удаляем пространства, игнорируя ошибки, если их не было
  ip netns del branch_a 2>/dev/null || true
  ip netns del branch_b 2>/dev/null || true
  ip netns del inet 2>/dev/null || true
}

create_topology() {
  # создание базовой топологии сети
  log "Creating namespaces"
  # создаем изолированные пространства для филиалов и интернета
  ip netns add branch_a
  ip netns add branch_b
  ip netns add inet

  log "Creating veth pairs (fiber + satellite + lan/inet)"
  # создаем виртуальные кабели (veth пары) для оптики, спутника и связи с интернетом
  ip link add a_fiber type veth peer name b_fiber
  ip link add a_sat type veth peer name b_sat
  ip link add a_lan type veth peer name inet_a
  ip link add b_lan type veth peer name inet_b

  log "Moving interfaces to namespaces"
  # раскидываем концы кабелей по соответствующим пространствам филиалов
  ip link set a_fiber netns branch_a
  ip link set a_sat netns branch_a
  ip link set a_lan netns branch_a

  ip link set b_fiber netns branch_b
  ip link set b_sat netns branch_b
  ip link set b_lan netns branch_b

  # концы для связи с интернетом помещаем в пространство inet
  ip link set inet_a netns inet
  ip link set inet_b netns inet
}

configure_ips() {
  # настройка сетевых адресов
  log "Configuring IP addresses"
  # назначаем ip адреса на концы оптического канала
  ip -n branch_a addr add 10.0.10.1/30 dev a_fiber
  ip -n branch_b addr add 10.0.10.2/30 dev b_fiber

  # назначаем ip адреса на концы спутникового канала
  ip -n branch_a addr add 10.0.20.1/30 dev a_sat
  ip -n branch_b addr add 10.0.20.2/30 dev b_sat

  # назначаем ip адреса для локальных сетей филиалов
  ip -n branch_a addr add 172.16.1.2/24 dev a_lan
  ip -n branch_b addr add 172.16.2.2/24 dev b_lan

  # настраиваем ip адреса шлюзов в пространстве интернета
  ip -n inet addr add 172.16.1.1/24 dev inet_a
  ip -n inet addr add 172.16.2.1/24 dev inet_b

  log "Bringing interfaces + loopbacks up"
  # поднимаем локальные петлевые интерфейсы во всех пространствах
  for ns in branch_a branch_b inet; do
    ip -n "$ns" link set lo up
  done

  # включаем все интерфейсы в первом филиале
  for dev in a_fiber a_sat a_lan; do
    ip -n branch_a link set "$dev" up
  done

  # включаем все интерфейсы во втором филиале
  for dev in b_fiber b_sat b_lan; do
    ip -n branch_b link set "$dev" up
  done

  # включаем интерфейсы в пространстве интернета
  ip -n inet link set inet_a up
  ip -n inet link set inet_b up
}

configure_routes() {
  # настройка таблиц маршрутизации
  log "Setting test routes"
  # настраиваем маршруты из первого филиала во второй с разными метриками приоритета
  ip -n branch_a route replace 172.16.2.0/24 via 10.0.10.2 dev a_fiber metric 10
  ip -n branch_a route replace 172.16.2.0/24 via 10.0.20.2 dev a_sat metric 100

  # настраиваем обратные маршруты из второго филиала в первый
  ip -n branch_b route replace 172.16.1.0/24 via 10.0.10.1 dev b_fiber metric 10
  ip -n branch_b route replace 172.16.1.0/24 via 10.0.20.1 dev b_sat metric 100

  # добавляем шлюзы по умолчанию для выхода в интернет-пространство
  ip -n branch_a route replace default via 172.16.1.1 dev a_lan
  ip -n branch_b route replace default via 172.16.2.1 dev b_lan
}

apply_satellite_impairment() {
  # эмуляция характеристик плохого канала связи
  log "Applying satellite emulation on branch_a:a_sat"
  # добавляем задержку 200мс, джиттер 30мс и 3% потерь на интерфейс a_sat
  ip netns exec branch_a tc qdisc replace dev a_sat root netem delay 200ms 30ms loss 3%

  log "Applying satellite emulation on branch_b:b_sat"
  # применяем те же ухудшения для интерфейса b_sat
  ip netns exec branch_b tc qdisc replace dev b_sat root netem delay 200ms 30ms loss 3%
}

show_status() {
  # вывод текущего состояния маршрутов для проверки
  log "Current Branch A routes"
  ip -n branch_a route show
  log "Current Branch B routes"
  ip -n branch_b route show
}

# обработка аргументов скрипта (по умолчанию выполняется режим up)
case "${1:-up}" in
  up)
    # последовательный вызов всех функций для развертывания стенда
    cleanup
    create_topology
    configure_ips
    configure_routes
    apply_satellite_impairment
    show_status
    log "Lab is ready"
    ;;
  down)
    # режим удаления стенда
    cleanup
    log "Lab removed"
    ;;
  *)
    # подсказка при неверном аргументе запуска
    echo "Usage: $0 [up|down]"
    exit 1
    ;;
esac