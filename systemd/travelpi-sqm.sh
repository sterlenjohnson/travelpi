#!/bin/sh
set -eu
WAN=wlan0
IFB=ifb-wan
RATE=${TRAVELPI_SQM_RATE:-12Mbit}
# Ingress (download) rides the IFB, so it can be tuned independently of the
# egress (upload) rate; the auto-tuner sets both, a manual pin sets RATE.
RATE_DOWN=${TRAVELPI_SQM_RATE_DOWN:-$RATE}

case "${1:-start}" in
start)
  /sbin/modprobe sch_cake
  /sbin/modprobe ifb numifbs=1
  /sbin/ip link show "$IFB" >/dev/null 2>&1 || /sbin/ip link add "$IFB" type ifb
  /sbin/ip link set dev "$IFB" up
  /sbin/tc qdisc replace dev "$WAN" root cake bandwidth "$RATE" diffserv4 nat
  /sbin/tc qdisc replace dev "$IFB" root cake bandwidth "$RATE_DOWN" diffserv4 nat
  /sbin/tc qdisc replace dev "$WAN" handle ffff: ingress
  /sbin/tc filter replace dev "$WAN" parent ffff: protocol all pref 10 u32 match u32 0 0 \
    action mirred egress redirect dev "$IFB"
  ;;
stop)
  /sbin/tc qdisc del dev "$WAN" root 2>/dev/null || true
  /sbin/tc qdisc del dev "$WAN" ingress 2>/dev/null || true
  /sbin/tc qdisc del dev "$IFB" root 2>/dev/null || true
  ;;
status)
  /sbin/tc qdisc show dev "$WAN"
  /sbin/tc qdisc show dev "$IFB" 2>/dev/null || true
  /sbin/tc -s filter show dev "$WAN" parent ffff: 2>/dev/null || true
  ;;
*)
  echo "Usage: $0 {start|stop|status}" >&2
  exit 2
  ;;
esac
