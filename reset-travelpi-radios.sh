#!/bin/bash
HOTEL_PROFILE="${HOTEL_PROFILE:-HotelWiFi}"
# Reset TravelPi radios to the known-good state:
#   AP  -> USB radio (wlan1), 5 GHz, 192.168.200.1
#   WAN -> internal radio (wlan0), hotel station (profile name in HOTEL_PROFILE)
#
# Safe to run over the AP connection: it detaches via setsid so a brief AP
# blip (hostapd restart) will not kill the script. The Pi ends in a working
# state: reconnect to the TravelPi AP afterwards.
#
# Usage:  bash reset-travelpi-radios.sh
set -u

if [ "$(id -u)" -ne 0 ]; then
  exec sudo "$0" "$@"
fi

if [ -z "${_RESET_DETACHED:-}" ]; then
  _RESET_DETACHED=1 setsid bash "$0" "$@" >/tmp/travelpi-reset.log 2>&1 &
  echo "Reset running detached. Reconnect to the TravelPi AP in ~10s, then:"
  echo "  tail -f /tmp/travelpi-reset.log"
  exit 0
fi

AP=wlan1
WAN=wlan0
LOG=/tmp/travelpi-reset.log
log() { echo "$(date '+%H:%M:%S') $*" | tee -a "$LOG"; }

log "Starting TravelPi radio reset (AP=$AP, WAN=$WAN)"

# 1) Back up and rewrite hostapd: AP on the USB radio, 5 GHz.
cp -f /etc/hostapd/hostapd.conf /etc/hostapd/hostapd.conf.travelpi-reset-bak 2>/dev/null
sed -i \
  -e "s/^interface=.*/interface=$AP/" \
  -e "s/^hw_mode=.*/hw_mode=a/" \
  -e "s/^channel=.*/channel=36/" \
  -e "s/^ieee80211ac=.*/ieee80211ac=1/" \
  -e "s/^ieee80211ax=.*/ieee80211ax=1/" \
  /etc/hostapd/hostapd.conf
log "hostapd.conf -> interface=$AP (5 GHz)"

# 2) dnsmasq on the AP radio.
sed -i "s/^interface=.*/interface=$AP/" /etc/dnsmasq.d/travelpi.conf
log "dnsmasq -> interface=$AP"

# 3) Radio ownership: WAN radio back to NetworkManager, AP radio to hostapd/dnsmasq.
nmcli device set "$WAN" managed yes 2>&1 | log || true
ip addr flush dev "$WAN" 2>/dev/null || true
nmcli device set "$AP" managed no 2>&1 | log || true
ip link set "$AP" up 2>&1 | log || true
ip addr flush dev "$AP" 2>/dev/null || true
ip addr replace 192.168.200.1/24 dev "$AP" 2>&1 | log
log "radios configured"

# 4) WAN station: (re)bind the hotel connection to the internal radio and bring it up.
nmcli connection modify "$HOTEL_PROFILE" connection.interface-name "$WAN" 2>&1 | log || true
nmcli connection up "$HOTEL_PROFILE" ifname "$WAN" 2>&1 | log || true

# 5) Restart AP services last (brief AP blip; reconnect afterward).
systemctl restart hostapd 2>&1 | log
systemctl restart dnsmasq 2>&1 | log

sleep 3
if systemctl is-active --quiet hostapd; then
  log "RESET OK: hostapd active on $AP, WAN on $WAN"
else
  log "hostapd did not come up; restoring previous hostapd.conf"
  cp -f /etc/hostapd/hostapd.conf.travelpi-reset-bak /etc/hostapd/hostapd.conf
  systemctl restart hostapd 2>&1 | log
fi
log "Done. See $LOG"
