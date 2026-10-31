"use strict";
function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
function pathValue(object, path) {
    const parts = typeof path === "string" ? path.split(".") : path;
    let current = object;
    for (const part of parts) {
        if (!isRecord(current) || !Object.prototype.hasOwnProperty.call(current, part)) {
            return undefined;
        }
        current = current[part];
    }
    return current;
}
function firstValue(object, paths, fallback) {
    for (const path of paths) {
        const value = pathValue(object, path);
        if (value !== undefined && value !== null && value !== "") {
            return value;
        }
    }
    return fallback;
}
function section(status, names) {
    const value = firstValue(status, names, null);
    return isRecord(value) ? value : {};
}
function statusViewModel(rawStatus) {
    let source = rawStatus;
    if (isRecord(source) && isRecord(source["data"])) {
        source = source["data"];
    }
    else if (isRecord(source) && isRecord(source["status"])) {
        source = source["status"];
    }
    source = isRecord(source) ? source : {};
    const wan = section(source, ["wan", "wlan0", "wifi_wan"]);
    const ap = section(source, ["ap", "wlan1", "access_point"]);
    const mac = section(source, ["mac", "wan_mac", "spoofed_wan_mac", "mac_clone", "spoofedWanMac"]);
    const route = section(source, ["route", "default_route", "defaultRoute"]);
    const cake = section(source, ["cake", "qdisc", "sqm", "traffic_shaping"]);
    const dnsStack = section(source, ["dnsStack", "dns_stack"]);
    const ipv6 = section(source, ["ipv6", "ipv6_status"]);
    const vpn = section(source, ["vpn", "secure_tunnel"]);
    const hardware = section(source, ["radioInventory", "hardware", "radios"]);
    const health = section(source, ["health", "system_health"]);
    const services = section(source, ["services", "service"]);
    const wired = section(source, ["wired"]);
    const readiness = section(source, ["readiness"]);
    const currentWanMac = firstValue(source, ["currentWanMac", "current_wan_mac", "spoofedWanMac", "spoofed_wan_mac"], firstValue(mac, ["currentWanMac", "address", "mac", "value"], null));
    const clone = section(source, ["wanMacClone", "wan_mac_clone"]);
    const normalized = {
        wan, ap, mac, route, cake, dnsStack, ipv6, vpn, hardware, health, services, wired, readiness,
        clients: firstValue(source, ["clients"], []),
        client_count: (function () {
            const raw = firstValue(source, ["clients"], []);
            if (Array.isArray(raw)) {
                return raw.length;
            }
            if (isRecord(raw)) {
                return Number(firstValue(raw, ["count"], 0)) || 0;
            }
            return 0;
        })(),
        defaultRoute: route,
        currentWanMac,
        wanMacClone: {
            active: Boolean(firstValue(clone, ["active"], false)),
            address: firstValue(clone, ["address"], null),
        },
        spoofedWanMac: currentWanMac,
        wan_state: firstValue(wan, ["state", "status", "connection"], firstValue(source, ["wan_state", "wan_status", "wlan0_state"], null)),
        wan_ssid: firstValue(wan, ["ssid", "network", "name"], firstValue(source, ["wan_ssid", "wlan0_ssid", "connected_ssid"], null)),
        wan_address: firstValue(wan, ["address", "ip", "ipv4", "ip_address"], firstValue(source, ["wan_address", "wan_ip", "wlan0_address"], null)),
        wan_signal: firstValue(wan, ["signal", "signal_dbm", "rssi"], firstValue(source, ["wan_signal", "wlan0_signal"], null)),
        wan_frequency: firstValue(wan, ["freq", "frequency", "channel_frequency"], firstValue(source, ["wan_frequency", "wlan0_frequency"], null)),
        ap_state: firstValue(ap, ["state", "status", "connection"], firstValue(source, ["ap_state", "ap_status", "wlan1_state"], null)),
        ap_ssid: firstValue(ap, ["ssid", "network", "name"], firstValue(source, ["ap_ssid", "wlan1_ssid"], null)),
        ap_channel: firstValue(ap, ["channel", "channel_number"], firstValue(source, ["ap_channel", "wlan1_channel", "channel"], null)),
        ap_address: firstValue(ap, ["address", "ip", "ipv4", "ip_address"], firstValue(source, ["ap_address", "ap_ip", "wlan1_address"], null)),
        cake_kind: firstValue(cake, ["kind", "qdisc", "algorithm", "name"], firstValue(source, ["cake_kind", "qdisc_kind"], null)),
        cake_rate: firstValue(cake, ["rate", "bandwidth", "download", "rate_mbps"], firstValue(source, ["cake_rate", "qdisc_rate"], null)),
        cake_state: firstValue(cake, ["state", "status", "active"], firstValue(source, ["cake_state", "qdisc_state", "sqm_state"], null)),
        mac_address: currentWanMac,
        mac_status: firstValue(mac, ["status", "state", "result"], firstValue(source, ["mac_status", "wan_mac_status", "spoofed_wan_mac_status"], null)),
        route_default: firstValue(route, [["default", "via"], "gateway", "default", "via"], firstValue(source, ["route_default", "default_gateway", "gateway"], null)),
        route_device: firstValue(route, ["device", "dev", "interface", "ifname"], firstValue(source, ["route_device", "default_device"], null)),
        hostapd: firstValue(services, ["hostapd"], firstValue(source, ["hostapd", "service_hostapd"], null)),
        dnsmasq: firstValue(services, ["dnsmasq"], firstValue(source, ["dnsmasq", "service_dnsmasq"], null)),
        sqm: firstValue(services, ["sqm", "sqm-scripts", "sqm_scripts"], firstValue(source, ["sqm", "service_sqm", "sqm_status"], null)),
        dns: firstValue(source, ["dns", "dns_servers"], null),
        forwarding: firstValue(source, ["forwarding", "ip_forward"], null),
        gateway: firstValue(wan, ["gateway"], firstValue(route, ["gateway", "default", "via"], firstValue(source, ["gateway"], null))),
        updated: firstValue(source, ["updated", "timestamp", "last_updated", "generated_at"], null),
    };
    return { status: normalized, wan, ap, mac, route, cake, dnsStack, ipv6, vpn,
        hardware, health, services, wired, readiness, canonicalGateway: normalized["gateway"] };
}
function byId(id) {
    return document.getElementById(id);
}
// Change-only DOM writes: the dashboard polls every 90 s and most text is
// identical poll to poll. On a Pi Zero 2 W (and its Cockpit-rendering
// clients) skipping identical writes removes all steady-state layout work.
const lastWritten = {};
function setText(id, value) {
    const text = String(value);
    if (lastWritten[id] === text) {
        return;
    }
    lastWritten[id] = text;
    const element = byId(id);
    if (!element) {
        return;
    }
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
        element.value = value;
    }
    else {
        element.textContent = value;
    }
}
function setHidden(id, hidden) {
    const element = byId(id);
    if (element) {
        element.hidden = hidden;
    }
}
function setState(id, state) {
    const cacheKey = id + "\u0000state";
    if (lastWritten[cacheKey] === state) {
        return;
    }
    lastWritten[cacheKey] = state;
    const element = byId(id);
    if (element) {
        element.setAttribute("data-state", state);
    }
}
function setBadge(id, text, state = "neutral") {
    const cacheKey = id + "\u0000badge";
    const cacheValue = text + "\u0000" + state;
    if (lastWritten[cacheKey] === cacheValue) {
        return;
    }
    lastWritten[cacheKey] = cacheValue;
    const element = byId(id);
    if (element) {
        element.textContent = text;
        element.setAttribute("data-state", state);
    }
}
function setSwitch(id, checked) {
    const element = byId(id);
    if (element instanceof HTMLInputElement) {
        element.checked = checked;
    }
}
function showNotice(message, isError) {
    const notice = byId("notice");
    if (!notice) {
        return;
    }
    notice.textContent = message || "";
    if (isError) {
        notice.setAttribute("data-state", "error");
    }
    else {
        notice.removeAttribute("data-state");
    }
}
var PROBE_STATES = {
    ASSOCIATED: true,
    ASSOCIATION_FAILED: true,
    NO_DHCP: true,
    NO_ROUTE: true,
    CAPTIVE_PORTAL: true,
    INTERNET_OK: true,
    NO_INTERNET: true,
    NO_DNS: true
};
function probeState(response) {
    var probe = isRecord(response.probe) ? response.probe : {};
    var state = firstValue(probe, ["status", "state", "result"], null);
    if (!state && typeof response.status === "string") {
        state = response.status;
    }
    if (!state && isRecord(response.status)) {
        state = firstValue(response.status, ["probe_status", "status", "state"], null);
    }
    if (!PROBE_STATES[state]) {
        throw new Error("invalid probe status");
    }
    return { state: state, probe: probe };
}
function displayValue(value, fallback) {
    if (value === undefined || value === null || value === "") {
        return fallback || "—";
    }
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }
    if (isRecord(value)) {
        return displayValue(firstValue(value, ["value", "address", "ip", "name", "state", "status"], null), fallback);
    }
    return fallback || "—";
}
var TravelPiTyped = { statusViewModel, byId, setText, setHidden, setState, setBadge, setSwitch, showNotice,
    isRecord, pathValue, firstValue, section, probeState, PROBE_STATES, displayValue };
if (typeof module !== "undefined" && module.exports) {
    module.exports = TravelPiTyped;
}
