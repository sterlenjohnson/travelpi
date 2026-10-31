"use strict";
(function () {
    "use strict";
    var HELPER = "/usr/local/libexec/travelpi-cockpit";
    var EMPTY = "—";
    var root;
    var MUTATIONS = TravelPiMutations;
    var mutationState = MUTATIONS.createState();
    var confirmationMeta = null;
    var pendingMeta = {};
    var statusInFlight = false;
    var statusStartedAt = 0;
    var statusQueued = false;
    var statusCallbacks = [];
    var probeInFlight = false;
    var statusPollTimer = null;
    var statusPollFailures = 0;
    var freshnessTimer = null;
    var lastStatusAt = 0;
    var lastReadiness = null;
    var lastView = null;
    var wanQualityHistory = [];
    var ACTION_COMMANDS = Object.keys(MUTATIONS.descriptors).reduce(function (result, action) {
        if (MUTATIONS.allowed(action)) {
            result[action] = true;
        }
        return result;
    }, {});
    function byId(id) {
        return TravelPiTyped.byId(id);
    }
    function setText(id, value) {
        TravelPiTyped.setText(id, String(value));
    }
    function setAdguardLink() {
        var link = byId("adguard-link");
        var hostname;
        if (!link || !window.location.hostname) {
            return;
        }
        hostname = window.location.hostname;
        if (hostname.indexOf(":") !== -1 && hostname.charAt(0) !== "[") {
            hostname = "[" + hostname + "]";
        }
        link.href = "http://" + hostname + "/";
    }
    function setHidden(id, hidden) {
        TravelPiTyped.setHidden(id, Boolean(hidden));
    }
    function setState(id, state) {
        TravelPiTyped.setState(id, state);
    }
    function setBadge(id, text, state) {
        TravelPiTyped.setBadge(id, text, state || "neutral");
    }
    function setSwitch(id, checked) {
        TravelPiTyped.setSwitch(id, Boolean(checked));
    }
    function showNotice(message, isError) {
        TravelPiTyped.showNotice(message, Boolean(isError));
    }
    function clientCount(value) {
        if (Array.isArray(value)) {
            return String(value.length);
        }
        if (TravelPiTyped.isRecord(value)) {
            return TravelPiTyped.displayValue(TravelPiTyped.firstValue(value, ["count", "number", "connected"], null), EMPTY);
        }
        return TravelPiTyped.displayValue(value, EMPTY);
    }
    // A MAC with the locally-administered bit (0x02 of the first octet) set is
    // a randomized/"private" address, not a vendor-assigned one.
    function isPrivateMac(mac) {
        var match = typeof mac === "string" ? mac.match(/^([0-9a-f]{2})(?::[0-9a-f]{2}){5}$/i) : null;
        return Boolean(match) && (parseInt(match[1], 16) & 2) === 2;
    }
    function renderClients(value) {
        var table = byId("client-rows");
        var items = Array.isArray(value) ? value : (TravelPiTyped.isRecord(value) && Array.isArray(value.items) ? value.items : []);
        var index;
        var row;
        var cell;
        var item;
        var badge;
        if (!table) {
            return;
        }
        table.textContent = "";
        if (!items.length) {
            row = document.createElement("tr");
            cell = document.createElement("td");
            cell.colSpan = 5;
            cell.className = "muted";
            cell.textContent = "No connected devices reported.";
            row.appendChild(cell);
            table.appendChild(row);
            return;
        }
        for (index = 0; index < items.length; index += 1) {
            item = items[index];
            row = document.createElement("tr");
            [item.hostname && item.hostname !== "*" ? item.hostname : item.name, item.ip, item.mac, item.signal_dbm ? item.signal_dbm + " dBm" : "\u2014",
                (item.tx_bitrate || item.rx_bitrate) ?
                    (item.tx_bitrate || "\u2014") + " / " + (item.rx_bitrate || "\u2014") : "\u2014"].forEach(function (cellValue, column) {
                cell = document.createElement("td");
                cell.textContent = TravelPiTyped.displayValue(cellValue);
                if (column === 2 && isPrivateMac(item.mac)) {
                    badge = document.createElement("span");
                    badge.className = "status-badge status-badge-neutral private-mac-badge";
                    badge.textContent = "Private MAC";
                    cell.textContent += " ";
                    cell.appendChild(badge);
                }
                row.appendChild(cell);
            });
            table.appendChild(row);
        }
    }
    var BAND_ORDER = ["2.4ghz", "5ghz", "6ghz"];
    var bandTouched = { wan: false, lan: false };
    function bandLabel(band) {
        return band === "2.4ghz" ? "2.4 GHz" : (band === "5ghz" ? "5 GHz" : (band === "6ghz" ? "6 GHz" : String(band)));
    }
    // Bands a radio reports from `iw phy info`; nothing is assumed when the
    // inventory is missing or the radio is absent.
    function reportedBands(record) {
        if (!TravelPiTyped.isRecord(record) || record.present === false) {
            return [];
        }
        var bands = TravelPiTyped.firstValue(record, ["bands"], []);
        if (!Array.isArray(bands)) {
            return [];
        }
        return BAND_ORDER.filter(function (band) { return bands.indexOf(band) !== -1; });
    }
    function fillBandSelect(select, options, wanted, keepPrevious) {
        var previous = select.value;
        select.innerHTML = "";
        options.forEach(function (entry) {
            var opt = document.createElement("option");
            opt.value = entry.value;
            opt.textContent = entry.label;
            select.appendChild(opt);
        });
        var offered = options.map(function (entry) { return entry.value; });
        if (keepPrevious && offered.indexOf(previous) !== -1) {
            select.value = previous;
        }
        else if (offered.indexOf(wanted) !== -1) {
            select.value = wanted;
        }
        else {
            select.value = offered[0];
        }
    }
    function renderRadioBands(view) {
        var wanField = byId("wan-band-field");
        var lanField = byId("lan-band-field");
        var wanSelect = byId("wan-band-select");
        var lanSelect = byId("lan-band-select");
        if (!wanField || !lanField || !wanSelect || !lanSelect) {
            return;
        }
        var hardware = TravelPiTyped.isRecord(view && view.hardware) ? view.hardware : {};
        var wanRadio = TravelPiTyped.section(hardware, ["wan", "wlan0"]);
        var lanRadio = TravelPiTyped.section(hardware, ["ap", "wlan1"]);
        var wanBands = reportedBands(wanRadio);
        var lanBands = reportedBands(lanRadio);
        var wanName = TravelPiTyped.displayValue(TravelPiTyped.firstValue(wanRadio, ["label"], null), "WAN radio");
        var lanName = TravelPiTyped.displayValue(TravelPiTyped.firstValue(lanRadio, ["label"], null), "LAN radio");
        setText("radio-roles-line", "WAN: " + wanName + " (wlan0) · LAN: " + lanName + " (wlan1). Swapping the roles is not available.");
        var roleSwitch = TravelPiTyped.section(view && view.readiness, ["role_switch"]);
        var wanState = TravelPiTyped.displayValue(TravelPiTyped.firstValue(view && view.status, ["wan_state"], null), "unknown");
        setText("role-swap-reason", "Role swap unavailable: " + TravelPiTyped.displayValue(TravelPiTyped.firstValue(roleSwitch, ["reason"], null), "needs a verified wired LAN uplink (ADR 0002)") + ".");
        setHidden("role-swap-reason", TravelPiTyped.firstValue(roleSwitch, ["available"], false) === true);
        setHidden("wan-band-reason", wanBands.length === 0 || wanState === "connected" || wanState === "up");
        setText("wan-band-label", "WAN radio: " + wanName + " (wlan0) band");
        setText("lan-band-label", "LAN radio: " + lanName + " (wlan1) band");
        wanField.hidden = wanBands.length === 0;
        lanField.hidden = lanBands.length === 0;
        setHidden("radio-bands-unavailable", wanBands.length > 0 || lanBands.length > 0);
        if (wanBands.length > 0) {
            var wanOptions = [{ value: "auto", label: "Automatic" }].concat(wanBands.map(function (band) {
                return { value: band, label: bandLabel(band) };
            }));
            fillBandSelect(wanSelect, wanOptions, TravelPiTyped.firstValue(view && view.wan, ["band_setting"], "auto"), bandTouched.wan);
        }
        if (lanBands.length > 0) {
            fillBandSelect(lanSelect, lanBands.map(function (band) {
                return { value: band, label: bandLabel(band) };
            }), TravelPiTyped.firstValue(view && view.ap, ["band"], null), bandTouched.lan);
        }
    }
    var sparkTemps = [];
    var sparkSignals = [];
    var sparkTune = [];
    function appendSpark(list, value, dedupe) {
        var n = Number(value);
        if (value === null || value === undefined || isNaN(n)) {
            return;
        }
        if (dedupe && list.length && list[list.length - 1] === n) {
            return;
        }
        list.push(n);
        if (list.length > 24) {
            list.shift();
        }
    }
    function renderSparkline(id, values) {
        var element = TravelPiTyped.byId(id);
        if (!element) {
            return;
        }
        if (values.length < 2) {
            element.innerHTML = "";
            return;
        }
        var min = Math.min.apply(null, values);
        var max = Math.max.apply(null, values);
        var span = max - min || 1;
        var pts = [];
        for (var i = 0; i < values.length; i += 1) {
            pts.push(Math.round(i * 120 / (values.length - 1)) + "," +
                Math.round(22 - ((values[i] - min) / span) * 20));
        }
        element.innerHTML = '<svg viewBox="0 0 120 24" preserveAspectRatio="none" class="spark-svg" aria-hidden="true">' +
            '<polyline points="' + pts.join(" ") + '" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';
    }
    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }
    function renderWakePeers(vpnTunnel) {
        var container = byId("vpn-wake-peers");
        if (!container) {
            return;
        }
        var peers = Array.isArray(vpnTunnel.peers) ? vpnTunnel.peers : [];
        var online = [];
        for (var i = 0; i < peers.length; i += 1) {
            if (peers[i] && peers[i].online && peers[i].name) {
                online.push(peers[i]);
            }
        }
        var signature = online.map(function (p) { return p.name; }).join(",");
        if (container.getAttribute("data-sig") === signature) {
            return;
        }
        container.setAttribute("data-sig", signature);
        if (!online.length) {
            container.innerHTML = '<li class="wake-peer-offline">No online tailnet peers reported.</li>';
            return;
        }
        container.innerHTML = online.map(function (p) {
            return '<li><span class="wake-peer-name">' + escapeHtml(p.name) + "</span>" +
                '<button class="button button-secondary" type="button" data-action="wake_peer"' +
                ' data-target="' + escapeHtml(p.name) + '">Wake</button></li>';
        }).join("");
        var buttons = container.querySelectorAll("[data-action]");
        for (var b = 0; b < buttons.length; b += 1) {
            buttons[b].addEventListener("click", handleAction);
        }
    }
    function renderVitals(view) {
        var status = view.status;
        var internetState = TravelPiTyped.displayValue(status.wan_state, "unknown");
        var wanSignal = status.wan_signal;
        var internetOnline = internetState === "connected" || internetState === "up" || internetState === "online";
        var portal = TravelPiTyped.isRecord(TravelPiTyped.firstValue(view.health, ["portal"], null)) ?
            TravelPiTyped.firstValue(view.health, ["portal"], {}) : {};
        var portalDetected = TravelPiTyped.displayValue(TravelPiTyped.firstValue(portal, ["state"], null), "") === "portal";
        setText("vitals-internet", (portalDetected ? "Internet portal" :
            (internetOnline ? "Internet online" : "Internet " + internetState)) +
            (wanSignal !== null && wanSignal !== undefined ? " · " + wanSignal + " dBm" : ""));
        setState("vitals-internet", portalDetected ? "warning" : (internetOnline ? "online" : "offline"));
        var apState = TravelPiTyped.displayValue(status.ap_state, "unknown");
        var apCarrier = TravelPiTyped.firstValue(view.ap, ["carrier"], null);
        var vitalsClients = Number(status.client_count) || 0;
        var apOnline = apState === "up" && apCarrier !== false;
        setText("vitals-ap", apCarrier === false ? "AP no carrier" :
            (apOnline ? "AP on · " + vitalsClients + " client" + (vitalsClients === 1 ? "" : "s") : "AP " + apState));
        setState("vitals-ap", apOnline ? "online" : "offline");
        var vitalsDns = TravelPiTyped.displayValue(TravelPiTyped.firstValue(view.dnsStack, ["service"], null), "unknown");
        setText("vitals-dns", vitalsDns === "active" ? "DNS active" :
            (vitalsDns === "degraded" ? "DNS up · no upstream" : "DNS " + vitalsDns));
        setState("vitals-dns", vitalsDns === "active" ? "online" : "offline");
        var memUsedPercent = TravelPiTyped.firstValue(view.health, ["memory_used_percent"], null);
        var swapUsedPercent = TravelPiTyped.firstValue(view.health, ["swap_used_percent"], null);
        var memPressured = TravelPiTyped.firstValue(view.health, ["pressured"], false) === true;
        setText("vitals-mem", memUsedPercent !== null && memUsedPercent !== undefined ?
            "Mem " + Math.round(memUsedPercent) + "%" +
                (swapUsedPercent !== null && swapUsedPercent !== undefined ? " · swap " + Math.round(swapUsedPercent) + "%" : "") :
            "Mem unavailable");
        setState("vitals-mem", memUsedPercent === null || memUsedPercent === undefined ? "neutral" :
            (memPressured ? "warning" : "online"));
        var vitalsPower = TravelPiTyped.section(view.health, ["power"]);
        var vitalsPowerSignal = TravelPiTyped.displayValue(TravelPiTyped.firstValue(vitalsPower, ["signal"], null), "unavailable");
        var vitalsTemp = TravelPiTyped.firstValue(view.health, ["temperature_c", "temperature"], null);
        setText("vitals-power", (vitalsPowerSignal === "clean" ? "Power OK" : "Power " + vitalsPowerSignal) +
            (vitalsTemp !== null && vitalsTemp !== undefined ? " · " + vitalsTemp + "°C" : ""));
        setState("vitals-power", vitalsPowerSignal === "clean" ? "online" :
            (vitalsPowerSignal === "unavailable" ? "neutral" : "warning"));
    }
    function renderStatus(rawStatus) {
        var view = TravelPiTyped.statusViewModel(rawStatus);
        lastReadiness = view.readiness;
        lastView = view;
        setAdguardLink();
        renderVitals(view);
        appendSpark(sparkTemps, TravelPiTyped.firstValue(view.health, ["temperature_c", "temperature"], null));
        appendSpark(sparkSignals, TravelPiTyped.firstValue(view.wan, ["signal"], null));
        appendSpark(sparkTune, TravelPiTyped.firstValue(TravelPiTyped.section(view.cake, ["autotune"]), ["applied_down_mbit"], null), true);
        renderSparkline("spark-signal", sparkSignals);
        renderSparkline("spark-temp", sparkTemps);
        renderSparkline("spark-tune", sparkTune);
        renderRadioBands(view);
        renderWan(view);
        renderPortalRow(view);
        renderAp(view);
        renderApProfile(view);
        renderApIdentity(view);
        renderNetwork(view);
        renderDnsPrivacy(view);
        renderVpn(view);
        renderHealth(view);
        renderFreshness(view);
    }
    function renderWan(view) {
        var status = view.status;
        var wan = view.wan;
        var hardware = view.hardware;
        var canonicalGateway = view.canonicalGateway;
        var wanHardware = TravelPiTyped.section(hardware, ["wan", "wlan0"]);
        var wanPresent = TravelPiTyped.firstValue(wanHardware, ["present"], true) !== false;
        var wanState = TravelPiTyped.displayValue(status.wan_state, "unknown");
        var wanOnline = wanState === "connected" || wanState === "up";
        var wanSignal = status.wan_signal;
        setHidden("internet-card", !wanPresent);
        setText("wan-state", wanState);
        setText("preferred-wan-label", TravelPiTyped.displayValue(TravelPiTyped.firstValue(wanHardware, ["label"], null), "Hotel Wi-Fi (WAN)"));
        setText("preferred-wan-interface", TravelPiTyped.displayValue(TravelPiTyped.firstValue(wan, ["interface"], "wlan0")));
        setText("wan-hardware", TravelPiTyped.displayValue(TravelPiTyped.firstValue(wanHardware, ["model"], null), "Hardware not detected") + " · " +
            TravelPiTyped.displayValue(TravelPiTyped.firstValue(wanHardware, ["transport"], null), "unknown"));
        setText("wan-chip-text", wanOnline ? "Online" : "Offline");
        setState("wan-chip", wanOnline ? "online" : "offline");
        setState("topo-wan-icon", wanOnline ? "online" : "offline");
        setText("topo-wan-label", wanOnline ? TravelPiTyped.displayValue(status.wan_ssid, "Hotel Wi-Fi") : "No Internet");
        setText("topo-wan-detail", wanOnline ? TravelPiTyped.displayValue(status.wan_address, "—") : "Not connected");
        setState("topo-line-wan", wanOnline ? "online" : "offline");
        setText("wan-ssid", TravelPiTyped.displayValue(status.wan_ssid));
        setText("wan-address", TravelPiTyped.displayValue(status.wan_address));
        setText("wan-signal", TravelPiTyped.displayValue(wanSignal));
        if (byId("wan-signal-bars")) {
            byId("wan-signal-bars").setAttribute("data-level", String(signalLevel(wanSignal)));
        }
        setText("wan-gateway", TravelPiTyped.displayValue(canonicalGateway));
        setText("detail-wan-gateway", TravelPiTyped.displayValue(canonicalGateway));
        setText("detail-wan-frequency", TravelPiTyped.displayValue(status.wan_frequency, EMPTY) +
            (status.wan_frequency ? " MHz" : ""));
        var scanResults = byId("wifi-scan-results");
        var scanButton = byId("scan-wifi");
        if (scanResults && scanButton) {
            // No host scan is spawned from the render path: the Wi-Fi scan is
            // a privileged command, so the user starts it from the button.
            scanResults.hidden = wanOnline;
            if (scanButton) {
                scanButton.textContent = wanOnline ? "Scan wlan0" : "Scan Wi-Fi networks";
            }
        }
    }
    function renderAp(view) {
        var status = view.status;
        var wan = view.wan;
        var ap = view.ap;
        var hardware = view.hardware;
        var apHardware = TravelPiTyped.section(hardware, ["ap", "wlan1"]);
        var apPresent = TravelPiTyped.firstValue(apHardware, ["present"], true) !== false;
        var apBands = TravelPiTyped.firstValue(apHardware, ["bands"], []);
        var apHasBandData = Array.isArray(apBands) && apBands.length > 0;
        var ap24Option = byId("ap-profile-24");
        var ap5Option = byId("ap-profile-5");
        if (apHasBandData) {
            if (ap24Option) {
                ap24Option.hidden = apBands.indexOf("2.4ghz") < 0;
                ap24Option.disabled = ap24Option.hidden;
                if (ap24Option.parentNode) {
                    ap24Option.parentNode.hidden = ap24Option.hidden;
                }
            }
            if (ap5Option) {
                ap5Option.hidden = apBands.indexOf("5ghz") < 0;
                ap5Option.disabled = ap5Option.hidden;
                if (ap5Option.parentNode) {
                    ap5Option.parentNode.hidden = ap5Option.hidden;
                }
            }
        }
        setHidden("private-card", !apPresent);
        var apState = TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["state", "status", "connection"], TravelPiTyped.firstValue(status, ["ap_state", "ap_status", "wlan1_state"], null)), "unknown");
        // Carrier evidence outranks the unit's claim: hostapd "active" with a
        // NO-CARRIER radio serves no clients (2026-10-27 incident).
        var apService = apState;
        if (TravelPiTyped.firstValue(ap, ["carrier"], null) === false) {
            apState = "no-carrier";
        }
        var apFrequency = TravelPiTyped.firstValue(ap, ["freq"], 0);
        var apBandLabel = apFrequency >= 5925 ? "6 GHz / Wi-Fi 6E" : (apFrequency >= 5000 ? "5 GHz / Wi-Fi 6" : "2.4 GHz");
        setText("ap-state", apState === "up" ? "Active" :
            (apState === "no-carrier" ? "Down — no carrier (radio link lost)" : apState));
        setText("ap-band", apBandLabel);
        setText("ap-interface", TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["interface"], "wlan1")));
        setText("ap-hardware", TravelPiTyped.displayValue(TravelPiTyped.firstValue(apHardware, ["model"], null), "Hardware not detected") + " · " +
            TravelPiTyped.displayValue(TravelPiTyped.firstValue(apHardware, ["transport"], null), "unknown"));
        setText("ap-chip-text", apState === "up" ? "ON" : (apState === "no-carrier" ? "NO CARRIER" : apState));
        setState("ap-chip", apState === "up" ? "online" : "offline");
        setSwitch("ap-enabled-toggle", apService === "up");
        setText("ap-ssid", TravelPiTyped.displayValue(status.ap_ssid));
        setText("ap-channel", TravelPiTyped.displayValue(status.ap_channel));
        var apClients = status.client_count;
        setText("ap-clients", clientCount(apClients));
        setText("detail-ap-frequency", TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["freq", "frequency"], null), EMPTY) +
            (TravelPiTyped.firstValue(ap, ["freq", "frequency"], null) ? " MHz" : ""));
        setText("detail-ap-width", TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["width", "channel_width"], null)));
        setText("detail-ap-txpower", TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["txpower_dbm", "tx_power"], null), EMPTY) +
            (TravelPiTyped.firstValue(ap, ["txpower_dbm", "tx_power"], null) ? " dBm" : ""));
        setText("detail-wan-rates", TravelPiTyped.displayValue(TravelPiTyped.firstValue(wan, ["tx_bitrate"], null)) + " / " +
            TravelPiTyped.displayValue(TravelPiTyped.firstValue(wan, ["rx_bitrate"], null)));
        setText("ap-wifi6", TravelPiTyped.firstValue(ap, ["wifi6"], false) ? "Yes" : "No");
        setText("topo-ap-detail", TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["ssid", "network", "name"], "TravelPi"), "TravelPi") + " • ch" + TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["channel"], null), "—"));
        setText("topo-clients-label", clientCount(status.client_count) + " Clients");
        setText("topo-clients-detail", TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["ip", "address"], "192.168.200.1"), "192.168.200.1"));
        setState("topo-line-lan", apState === "up" ? "online" : "offline");
        setText("client-summary", clientCount(status.client_count) + " clients");
        renderClients(status.clients);
    }
    function renderNetwork(view) {
        var status = view.status;
        var cake = view.cake;
        var services = view.services;
        var canonicalGateway = view.canonicalGateway;
        setText("network-wan-interface", TravelPiTyped.displayValue(status.route_device));
        setText("network-wan-gateway", TravelPiTyped.displayValue(canonicalGateway));
        var systemDns = status.dns;
        setText("network-dns", Array.isArray(systemDns) && systemDns.length ? systemDns.join(", ") : "No DNS reported");
        setText("network-forwarding", TravelPiTyped.displayValue(status.forwarding));
        setText("network-summary", TravelPiTyped.displayValue(status.route_device, "Read-only"));
        setText("route-default", TravelPiTyped.displayValue(status.route_default));
        setText("route-device", TravelPiTyped.displayValue(status.route_device));
        setText("cake-kind", TravelPiTyped.displayValue(status.cake_kind));
        var cakeActive = TravelPiTyped.firstValue(cake, ["state"], "inactive") === "active";
        var cakeModeRaw = TravelPiTyped.displayValue(TravelPiTyped.firstValue(cake, ["mode"], null), null);
        var cakeUiMode = !cakeActive ? "off" : (cakeModeRaw === "pinned" ? "manual" : "auto");
        var cakeRateValue = status.cake_rate;
        setText("cake-rate", TravelPiTyped.displayValue(cakeRateValue, "\u2014") + " \u00b7 " + cakeUiMode);
        setBadge("cake-enabled-toggle", cakeActive ? "CAKE / SQM active" : "CAKE / SQM unavailable", cakeActive ? "online" : "warning");
        var cakeRateInput = byId("cake-rate-input");
        var cakeRateButton = byId("stage-cake-rate");
        if (cakeRateInput) {
            var rateDigits = cakeRateValue === null ? null : String(cakeRateValue).match(/^(\d+(?:\.\d+)?)/);
            if (rateDigits && document.activeElement !== cakeRateInput && cakeRateInput.value !== rateDigits[1]) {
                cakeRateInput.value = rateDigits[1];
            }
            cakeRateInput.disabled = cakeUiMode !== "manual";
            setText("cake-mode-help", cakeUiMode === "auto"
                ? "Auto mode tunes this rate from the measured uplink, so editing is paused. Switch Traffic shaping to Manual in Quick Settings to set it yourself."
                : (cakeUiMode === "manual"
                    ? "Manual mode: this rate stays until you change it. Switch back to Auto in Quick Settings to resume auto-tuning."
                    : "Shaping is off. Switch Traffic shaping to Auto or Manual in Quick Settings to shape WAN traffic."));
        }
        if (cakeRateButton) {
            cakeRateButton.disabled = cakeUiMode !== "manual";
        }
        setText("service-hostapd", TravelPiTyped.displayValue(TravelPiTyped.firstValue(services, ["hostapd"], TravelPiTyped.firstValue(status, ["hostapd", "service_hostapd"], null))));
        setText("service-dnsmasq", TravelPiTyped.displayValue(TravelPiTyped.firstValue(services, ["dnsmasq"], TravelPiTyped.firstValue(status, ["dnsmasq", "service_dnsmasq"], null))));
        setText("service-sqm", TravelPiTyped.displayValue(TravelPiTyped.firstValue(services, ["sqm", "sqm-scripts", "sqm_scripts"], TravelPiTyped.firstValue(status, ["sqm", "service_sqm", "sqm_status"], null))));
    }
    function renderDnsPrivacy(view) {
        function markModeButtons(pairs, active) {
            for (var i = 0; i < pairs.length; i += 1) {
                var el = byId(pairs[i][0]);
                if (!el) {
                    continue;
                }
                if (pairs[i][1] === active) {
                    el.classList.add("is-active");
                    el.setAttribute("aria-pressed", "true");
                }
                else {
                    el.classList.remove("is-active");
                    el.setAttribute("aria-pressed", "false");
                }
            }
        }
        var status = view.status;
        var dnsStack = view.dnsStack;
        var ipv6 = view.ipv6;
        var mac = view.mac;
        var cake = view.cake;
        var dnsService = TravelPiTyped.displayValue(TravelPiTyped.firstValue(dnsStack, ["service"], null), "unknown");
        var dnsMode = TravelPiTyped.displayValue(TravelPiTyped.firstValue(dnsStack, ["mode"], null), "unknown");
        var ipv6State = TravelPiTyped.displayValue(TravelPiTyped.firstValue(ipv6, ["state"], null), "unavailable");
        var sqmState = TravelPiTyped.displayValue(TravelPiTyped.firstValue(cake, ["state"], null), "unknown");
        var identity = TravelPiTyped.displayValue(TravelPiTyped.firstValue(status, ["currentWanMac"], TravelPiTyped.firstValue(mac, ["address", "mac", "value"], null)), "Unknown");
        var cloned = Boolean(TravelPiTyped.firstValue(status.wanMacClone, ["active"], false));
        var stackMode = TravelPiTyped.displayValue(TravelPiTyped.firstValue(dnsStack, ["stack_mode"], null), "adguard");
        setText("quick-dns-state", stackMode === "unbound" ? "Plain recursive (Unbound on :53)" :
            (dnsService === "active" ? "Filtered (AdGuard Home)" :
                (dnsService === "degraded" ? "AdGuard Home running · upstream DNS not answering" : "AdGuard Home unavailable")));
        setText("quick-dns-detail", TravelPiTyped.displayValue(TravelPiTyped.firstValue(dnsStack, ["upstream"], null), "DNS upstream not reported"));
        setBadge("quick-dns-chip", stackMode === "unbound" ? "Recursive" : (dnsService === "active" ? "Filtered" :
            (dnsService === "degraded" ? "No upstream" : "Unavailable")), stackMode === "unbound" || dnsService === "degraded" ? "warning" : (dnsService === "active" ? "online" : "offline"));
        markModeButtons([["dns-mode-adguard", "adguard"], ["dns-mode-unbound", "unbound"]], stackMode);
        setHidden("dns-mode-reason", dnsService === "active" || dnsService === "degraded");
        setText("quick-dns-mode-note", stackMode === "unbound"
            ? "Unfiltered: no ad blocking and tailnet name resolution are inactive in recursive mode."
            : (dnsService === "active" || dnsService === "degraded"
                ? "AdGuard blocks ads, resolves tailnet/home names, and falls back to Unbound."
                : "AdGuard is not running, so connected devices are not getting filtered DNS right now."));
        var unboundState = TravelPiTyped.displayValue(TravelPiTyped.firstValue(status, ["services", "unbound"], "unknown"), "unknown");
        var unboundOnline = unboundState === "active";
        setText("quick-unbound-state", unboundOnline ? "Active" : "Inactive");
        setText("quick-unbound-detail", unboundOnline ? "Recursive resolver on 127.0.0.1:5335" : "Unbound not running");
        setBadge("quick-unbound-chip", unboundOnline ? "Active" : "Inactive", unboundOnline ? "online" : "offline");
        var ipv6Labels = { active: "Active", "ula-only": "ULA only", "off": "Off", unavailable: "Off" };
        var ipv6Label = TravelPiTyped.displayValue(ipv6Labels[ipv6State], ipv6State);
        setText("quick-ipv6-state", ipv6Label);
        setText("quick-ipv6-detail", TravelPiTyped.displayValue(TravelPiTyped.firstValue(ipv6, ["detail"], null), "IPv6 state not reported."));
        setText("quick-ipv6-mode-note", ipv6State === "active"
            ? "Devices on this router get global IPv6 addresses as well as private ones."
            : (ipv6State === "ula-only"
                ? "Devices get private (ULA) IPv6 only: reachable over the tailnet, but no global address."
                : "IPv6 is off: connected devices use IPv4 only."));
        setBadge("quick-ipv6-chip", ipv6Label, ipv6State === "active" ? "online" : (ipv6State === "ula-only" ? "warning" : "neutral"));
        markModeButtons([["ipv6-on", "on"], ["ipv6-off", "off"]], (ipv6State === "active" || ipv6State === "ula-only") ? "on" : "off");
        var cakeMode = TravelPiTyped.displayValue(TravelPiTyped.firstValue(cake, ["mode"], null), null);
        var sqmMode = cakeMode === "off" ? "off" : (cakeMode === "pinned" ? "manual" : "auto");
        setText("quick-sqm-state", sqmState === "active" ? "CAKE " + sqmMode : "CAKE off");
        setText("quick-sqm-detail", TravelPiTyped.displayValue(TravelPiTyped.firstValue(cake, ["rate"], null), "Rate not reported"));
        setBadge("quick-sqm-chip", sqmState === "active" ? sqmMode : "off", sqmState === "active" ? (sqmMode === "auto" ? "online" : "warning") : "neutral");
        markModeButtons([["sqm-mode-auto", "auto"], ["sqm-mode-manual", "manual"], ["sqm-mode-off", "off"]], sqmMode);
        var autoTune = TravelPiTyped.section(cake, ["autotune"]);
        var autoState = TravelPiTyped.displayValue(TravelPiTyped.firstValue(autoTune, ["state"], null), "off");
        var autoNote = "Auto-tune has not measured the link yet.";
        if (autoState === "pinned") {
            autoNote = "Auto-tune off — rate pinned from the dashboard.";
        }
        else if (autoState === "probe-failed") {
            autoNote = "Auto-tune probe failed (offline or captive portal?).";
        }
        else if (autoState === "stale") {
            autoNote = "Auto-tune stale — no measurement in the last 6 hours.";
        }
        else if (autoState === "active") {
            var autoAge = Number(TravelPiTyped.firstValue(autoTune, ["age_s"], 0));
            var ageNote = autoAge < 3600 ? Math.round(autoAge / 60) + "m ago" : Math.round(autoAge / 3600) + "h ago";
            autoNote = "Auto-tuned " + TravelPiTyped.displayValue(TravelPiTyped.firstValue(autoTune, ["applied_down_mbit"], null), "?") +
                " down / " + TravelPiTyped.displayValue(TravelPiTyped.firstValue(autoTune, ["applied_up_mbit"], null), "?") +
                " Mbit \u2022 " + ageNote;
        }
        setText("quick-sqm-autotune", autoNote);
        setBadge("mac-clone-chip", cloned ? "Cloned" : "Ready", cloned ? "warning" : "neutral");
        var macIdentityAddress = TravelPiTyped.firstValue(status, ["currentWanMac"], TravelPiTyped.firstValue(mac, ["address", "mac", "value"], null));
        setText("mac-clone-current", TravelPiTyped.displayValue(TravelPiTyped.firstValue(status.wanMacClone, ["address"], macIdentityAddress), "&mdash;"));
        setText("mac-clone-status", cloned ? "Cloned MAC active on wlan0" : "No clone active (using hardware MAC)");
    }
    function renderVpn(view) {
        var vpn = view.vpn;
        var vpnProvider = TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpn, ["selected"], null), "tailscale");
        var vpnStates = TravelPiTyped.firstValue(vpn, ["states"], {});
        var vpnProviders = TravelPiTyped.firstValue(vpn, ["providers"], {});
        var vpnTunnel = TravelPiTyped.isRecord(vpnProviders[vpnProvider]) ? vpnProviders[vpnProvider] : {};
        var vpnState = TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpnTunnel, ["state"], TravelPiTyped.firstValue(vpnStates, [vpnProvider], null)), "unknown");
        var vpnActive = Array.isArray(TravelPiTyped.firstValue(vpn, ["active"], [])) ? TravelPiTyped.firstValue(vpn, ["active"], []) : [];
        setText("vpn-chip", vpnActive.length ? TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpn, ["summary"], null), "Active") : "Off");
        setState("vpn-chip", vpnActive.length ? "online" : "neutral");
        setText("vpn-detail", vpnActive.length ? "Managed secure tunnel status." : "No secure tunnel is active.");
        setText("vpn-tunnel", vpnProvider + " " + vpnState);
        setText("vpn-endpoint", TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpnTunnel, ["transport", "endpoint"], null), vpnActive.length ? "Service-managed" : "Off"));
        setText("vpn-addresses", Array.isArray(vpnTunnel.addresses) ? vpnTunnel.addresses.join(", ") : "—");
        setText("vpn-exit-node", TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpnTunnel, ["exit_node"], null), "None reported"));
        setText("vpn-peers", TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpnTunnel, ["peer_count"], null), "Not reported"));
        renderWakePeers(vpnTunnel);
        setText("vpn-routes", Array.isArray(vpnTunnel.routes) && vpnTunnel.routes.length ? vpnTunnel.routes.join(", ") : "None reported");
        setText("vpn-handshake", TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpnTunnel, ["latest_handshake"], null), "Not reported"));
        if (byId("vpn-provider")) {
            byId("vpn-provider").value = vpnProvider;
        }
        if (byId("vpn-toggle")) {
            byId("vpn-toggle").textContent = vpnState === "active" ? "Turn off " + vpnProvider : "Turn on " + vpnProvider;
            byId("vpn-toggle").setAttribute("data-vpn-active", vpnState === "active" ? "true" : "false");
            byId("vpn-toggle").setAttribute("data-vpn-tailscale", TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpnStates, ["tailscale"], null), "unknown"));
            byId("vpn-toggle").setAttribute("data-vpn-wireguard", TravelPiTyped.displayValue(TravelPiTyped.firstValue(vpnStates, ["wireguard"], null), "unknown"));
        }
        var tsProvider = TravelPiTyped.isRecord(vpnProviders.tailscale) ? vpnProviders.tailscale : {};
        var tsNeedsLogin = tsProvider.needs_login === true || (typeof tsProvider.backend_state === "string" && tsProvider.backend_state !== "Running");
        var authSection = byId("tailscale-auth");
        if (authSection) {
            if (tsNeedsLogin) {
                var authUrl = tsProvider.auth_url;
                var authLink = byId("tailscale-auth-url");
                if (authLink) {
                    if (authUrl) {
                        authLink.setAttribute("href", authUrl);
                        authLink.hidden = false;
                    }
                    else {
                        authLink.hidden = true;
                    }
                }
                authSection.hidden = false;
            }
            else {
                authSection.hidden = true;
            }
        }
    }
    function renderHealth(view) {
        var health = view.health;
        var power = TravelPiTyped.section(health, ["power"]);
        var temperature = TravelPiTyped.firstValue(power, ["temperature_c"], null);
        var load = TravelPiTyped.firstValue(health, ["load_1m"], null);
        var swap = TravelPiTyped.firstValue(health, ["swap_used_mb"], null);
        var warnings = [];
        var throttle = TravelPiTyped.firstValue(power, ["throttled", "throttle", "throttling"], null);
        var disk = TravelPiTyped.firstValue(health, ["disk_used_percent", "disk_percent"], null);
        if (Number(temperature) >= 80) {
            warnings.push("High temperature");
        }
        if (Number(load) >= 4) {
            warnings.push("High load");
        }
        if (Number(swap) > 0) {
            warnings.push("Swap in use");
        }
        var throttleFlags = typeof throttle === "string" && /^0x[0-9a-f]+$/i.test(throttle) ? parseInt(throttle, 16) : null;
        var underVoltNow = TravelPiTyped.firstValue(power, ["under_volt_now"], null);
        var underVoltHistory = TravelPiTyped.firstValue(power, ["under_volt_history"], null);
        if (underVoltHistory === true) {
            warnings.push("Under-voltage since boot");
        }
        if (underVoltNow === true) {
            warnings.push("Under-voltage now");
        }
        if (TravelPiTyped.firstValue(power, ["unexpected_shutdown"], null) === true) {
            warnings.push("Power-loss shutdown (previous boot ended abruptly)");
        }
        if (TravelPiTyped.firstValue(power, ["clock_synced"], null) === false) {
            warnings.push("Clock unsynced (NTP pending)");
        }
        var storageRisk = TravelPiTyped.firstValue(power, ["storage_risk"], null);
        var powerLosses = Number(TravelPiTyped.firstValue(power, ["power_loss_count"], 0));
        if (storageRisk === "high") {
            warnings.push("Storage risk high (filesystem errors logged)");
        }
        else if (storageRisk === "elevated") {
            warnings.push("Storage risk elevated (power losses: " + powerLosses + ")");
        }
        var portalInfo = TravelPiTyped.isRecord(TravelPiTyped.firstValue(health, ["portal"], null)) ?
            TravelPiTyped.firstValue(health, ["portal"], {}) : {};
        if (TravelPiTyped.firstValue(portalInfo, ["state"], null) === "portal") {
            var portalUrl = TravelPiTyped.firstValue(portalInfo, ["portal_url"], null);
            warnings.push("Captive portal detected" + (portalUrl ? " (" + portalUrl + ")" : "") +
                " — open http://neverssl.com on your device to sign in");
        }
        var overlaps = TravelPiTyped.firstValue(health, ["subnet_overlaps"], null);
        if (Array.isArray(overlaps)) {
            overlaps.forEach(function (item) { if (typeof item === "string" && item) {
                warnings.push(item);
            } });
        }
        var radioResets = Number(TravelPiTyped.firstValue(health, ["radio_reset_events"], 0));
        if (radioResets > 0) {
            warnings.push("Radio resets: " + radioResets);
        }
        var radioLinkEvents = Number(TravelPiTyped.firstValue(health, ["radio_link_events"], 0));
        if (radioLinkEvents > 0) {
            warnings.push("Radio link failures: " + radioLinkEvents);
        }
        var radioRecoveries = Number(TravelPiTyped.firstValue(health, ["radio_recovery_events"], 0));
        var watchdog = TravelPiTyped.firstValue(health, ["radio_watchdog"], null);
        if (watchdog === "stale") {
            warnings.push("Radio watchdog stale");
        }
        else if (watchdog === "absent") {
            warnings.push("Radio watchdog not installed");
        }
        if (radioRecoveries > 0) {
            var lastRecovery = Number(TravelPiTyped.firstValue(health, ["last_radio_recovery"], 0));
            var recoveryNote = "Radio auto-recoveries: " + radioRecoveries;
            if (lastRecovery > 0) {
                recoveryNote += " (last " + new Date(lastRecovery * 1000).toISOString()
                    .replace("T", " ").slice(0, 16) + " UTC)";
            }
            warnings.push(recoveryNote);
        }
        var memGuardEvents = Number(TravelPiTyped.firstValue(health, ["mem_guard_events"], 0));
        var memWatchdog = TravelPiTyped.firstValue(health, ["mem_watchdog"], null);
        if (memWatchdog === "stale") {
            warnings.push("Memory guard stale");
        }
        else if (memWatchdog === "absent") {
            warnings.push("Memory guard not installed");
        }
        if (memGuardEvents > 0) {
            var lastGuardAction = TravelPiTyped.firstValue(health, ["last_mem_guard_action"], null);
            var lastGuardEvent = TravelPiTyped.displayValue(TravelPiTyped.firstValue(health, ["last_mem_guard_event"], null), "");
            var guardNote = "Memory guard actions: " + memGuardEvents;
            if (lastGuardAction) {
                guardNote += " (last: " + lastGuardAction +
                    (lastGuardEvent ? " " + String(lastGuardEvent).replace("T", " ").slice(0, 16) + " UTC" : "") + ")";
            }
            warnings.push(guardNote);
        }
        if (throttle === true || throttle === "yes" || throttle === "throttled" || (throttleFlags !== null && throttleFlags !== 0)) {
            warnings.push("Power throttling detected");
        }
        if (Number(disk) >= 90) {
            warnings.push("Disk nearly full");
        }
        setText("issue-banner", warnings.length
            ? warnings.length + " open issue" + (warnings.length === 1 ? "" : "s") + ": " + warnings.join(" · ")
            : "No open issues.");
        setState("issue-banner", warnings.length ? "warning" : "ok");
        setText("quick-health-state", temperature === null ? "Power telemetry unavailable" : "" + temperature + "°C · load " + TravelPiTyped.displayValue(load, "—"));
        setText("quick-health-detail", TravelPiTyped.displayValue(TravelPiTyped.firstValue(power, ["detail"], null), "No power status reported.") + (swap === null ? "" : " Swap used: " + swap + " MB."));
        var memAvail = TravelPiTyped.firstValue(health, ["memory_available_mb"], null);
        var memTotal = TravelPiTyped.firstValue(health, ["memory_total_mb"], null);
        var swapFree = TravelPiTyped.firstValue(health, ["swap_free_mb"], null);
        var swapTotal = TravelPiTyped.firstValue(health, ["swap_total_mb"], null);
        setText("quick-memory-detail", (memAvail === null || !memTotal) ? "Memory not reported."
            : "RAM " + memAvail + " MB free of " + memTotal + " MB · Swap "
                + (swapFree === null || swapTotal === null ? "not reported" : swapFree + " MB free of " + swapTotal + " MB")
                + " — clearing caches frees page cache only; swap frees as processes exit.");
        setBadge("quick-health-chip", TravelPiTyped.displayValue(TravelPiTyped.firstValue(power, ["state"], null), "Unknown"), TravelPiTyped.firstValue(power, ["state"], "unknown") === "ok" ? "online" : "warning");
        renderPower(power, throttleFlags);
    }
    function renderPower(power, throttleFlags) {
        var governor = TravelPiTyped.displayValue(TravelPiTyped.firstValue(power, ["governor"], null), null);
        var governorIndex = { conservative: 0, ondemand: 1, performance: 2 };
        setText("quick-governor-state", governor === null ? "Governor unknown" : "Governor: " + governor);
        var govSlider = byId("governor-slider");
        if (govSlider && governor !== null && governorIndex[governor] !== undefined
            && String(governorIndex[governor]) !== govSlider.value) {
            govSlider.value = String(governorIndex[governor]);
        }
        var powerSignal = TravelPiTyped.firstValue(power, ["signal"], null);
        var powerLabels = {
            clean: "Power OK",
            "undervolt-now": "Under-voltage NOW",
            "undervolt-history": "Under-voltage history",
            "throttle-now": "Throttling",
            "throttle-history": "Throttled earlier",
            "temperature-now": "Thermal",
            "temperature-history": "Thermal",
            unavailable: "No telemetry"
        };
        var powerStates = {
            clean: "online",
            "undervolt-now": "warning",
            "undervolt-history": "warning",
            "throttle-now": "warning",
            "throttle-history": "warning",
            "temperature-now": "warning",
            "temperature-history": "warning",
            unavailable: "neutral"
        };
        var coreVolts = TravelPiTyped.firstValue(power, ["core_volts"], null);
        var currentMa = TravelPiTyped.firstValue(power, ["current_ma"], null);
        var powerWatts = TravelPiTyped.firstValue(power, ["power_w"], null);
        var usbDevices = TravelPiTyped.firstValue(power, ["usb_devices"], null);
        var unexpectedShutdown = TravelPiTyped.firstValue(power, ["unexpected_shutdown"], null) === true;
        var powerFacts = [];
        if (unexpectedShutdown) {
            powerFacts.push("power-loss shutdown");
        }
        if (typeof coreVolts === "number" && !isNaN(coreVolts)) {
            powerFacts.push(coreVolts.toFixed(2) + " V core");
        }
        if (typeof currentMa === "number" && !isNaN(currentMa)) {
            powerFacts.push(currentMa + " mA" + (typeof powerWatts === "number" && !isNaN(powerWatts) ? " · " + powerWatts.toFixed(2) + " W" : ""));
        }
        else if (power.current_ma !== undefined || power.power_w !== undefined) {
            powerFacts.push("no current sensor (INA219 optional)");
        }
        if (power.usb_otg_present === true) {
            var otgFacts = ["OTG port up"];
            if (usbDevices === 0) {
                otgFacts.push("no devices");
            }
            else if (typeof usbDevices === "number") {
                otgFacts.push(usbDevices + " USB devices");
            }
            var usbDemand = TravelPiTyped.firstValue(power, ["usb_demand_ma"], null);
            if (typeof usbDemand === "number" && !isNaN(usbDemand) && usbDemand > 0) {
                otgFacts.push("~" + usbDemand + " mA demand");
            }
            powerFacts.push(otgFacts.join(" · "));
        }
        else if (power.usb_otg_present === false) {
            powerFacts.push("OTG port inactive");
        }
        if (throttleFlags !== null) {
            powerFacts.push("flags " + throttleFlags.toString(16));
        }
        var powerLabel = powerLabels[powerSignal] || TravelPiTyped.displayValue(powerSignal, "Unknown");
        var powerState = powerStates[powerSignal] || "neutral";
        if (unexpectedShutdown && (powerState === "online" || powerState === "neutral")) {
            powerLabel = "Power loss shutdown";
            powerState = "warning";
        }
        setText("quick-power-state", powerLabel);
        setBadge("quick-power-chip", powerLabel, powerState);
        setText("quick-power-detail", powerFacts.length ? powerFacts.join(" · ") : EMPTY);
    }
    function renderFreshness(view) {
        var value = TravelPiTyped.firstValue(view.status, ["updated", "timestamp", "last_updated", "generated_at"], null);
        lastStatusAt = Date.now();
        setText("last-updated", TravelPiTyped.displayValue(value, new Date().toLocaleString()));
        setText("freshness-state", "(fresh)");
    }
    var DEGRADED_MESSAGE = /still reported|did not restart|failed|could not/i;
    function parseHelperJson(raw) {
        var value = raw;
        if (typeof value === "string") {
            try {
                value = JSON.parse(value.trim());
            }
            catch (error) {
                return null;
            }
        }
        return TravelPiTyped.isRecord(value) ? value : null;
    }
    // cockpit.spawn rejects with (error, data): data holds the helper's stdout,
    // which carries {ok:false,error:{code,message}} for a refused action.
    function helperFailureMessage(error, data, fallback) {
        var problem = error && typeof error === "object" ? error.problem : null;
        var helperResponse = parseHelperJson(data);
        var helperError = helperResponse && TravelPiTyped.isRecord(helperResponse.error) ? helperResponse.error : null;
        var code = helperError && typeof helperError.code === "string" ? helperError.code : "";
        if (problem === "access-denied" || code === "not_privileged") {
            return "Administrative access is required: enable Administrative access in Cockpit, then try again.";
        }
        if (helperError && typeof helperError.message === "string" && helperError.message) {
            return helperError.message;
        }
        if (problem === "terminated" || problem === "disconnected") {
            return "Connection dropped while applying; reload and check status.";
        }
        return fallback;
    }
    function observeProcess(process, onSuccess, onFailure) {
        if (process && typeof process.then === "function") {
            process.then(onSuccess, onFailure);
            return;
        }
        if (process && typeof process.done === "function" && typeof process.fail === "function") {
            process.done(onSuccess).fail(onFailure);
            return;
        }
        if (onFailure) {
            onFailure();
        }
    }
    function scheduleStatusRefresh(delay) {
        var wait = delay;
        if (statusPollTimer) {
            window.clearTimeout(statusPollTimer);
            statusPollTimer = null;
        }
        if (typeof document !== "undefined" && document.hidden) {
            return;
        }
        if (wait === undefined || wait === null) {
            wait = statusPollFailures ? Math.min(240000, 30000 * Math.pow(2, Math.min(statusPollFailures - 1, 3))) : 90000;
        }
        statusPollTimer = window.setTimeout(function () {
            statusPollTimer = null;
            if (!mutationState.busy && !mutationState.confirmation) {
                refreshStatus();
            }
            else {
                scheduleStatusRefresh(5000);
            }
        }, wait);
    }
    function finishStatus(success, callback) {
        var callbacks;
        var index;
        statusInFlight = false;
        if (success) {
            statusPollFailures = 0;
        }
        else {
            statusPollFailures += 1;
        }
        if (statusQueued) {
            statusQueued = false;
            refreshStatus();
            return;
        }
        callbacks = statusCallbacks;
        statusCallbacks = [];
        for (index = 0; index < callbacks.length; index += 1) {
            callbacks[index](success);
        }
        if (callback) {
            callback(success);
        }
        scheduleStatusRefresh();
    }
    function refreshStatus(callback) {
        var process;
        var status;
        if (callback) {
            statusCallbacks.push(callback);
        }
        if (statusInFlight) {
            statusQueued = true;
            return;
        }
        statusInFlight = true;
        statusStartedAt = Date.now();
        showNotice("Loading TravelPi status…", false);
        try {
            process = cockpit.spawn([HELPER, "status"], { superuser: "try" });
        }
        catch (error) {
            showNotice("Unable to read TravelPi status.", true);
            finishStatus(false);
            return;
        }
        observeProcess(process, function (output) {
            try {
                status = typeof output === "string" ? JSON.parse(output) : output;
                if (!TravelPiTyped.isRecord(status)) {
                    throw new Error("invalid status");
                }
                renderStatus(status);
                showNotice("", false);
                finishStatus(true);
            }
            catch (error) {
                showNotice("TravelPi returned invalid status data.", true);
                finishStatus(false);
            }
        }, function () {
            showNotice("Unable to read TravelPi status.", true);
            finishStatus(false);
        });
    }
    function renderProbe(response) {
        var result = TravelPiTyped.probeState(response);
        var detail;
        var httpStatus = result.probe.http_status;
        var visualState;
        switch (result.state) {
            case "ASSOCIATED":
                detail = "wlan0 is associated.";
                break;
            case "ASSOCIATION_FAILED":
                detail = "wlan0 is not associated with the hotel network.";
                break;
            case "NO_DHCP":
                detail = "wlan0 is associated but has no DHCP address.";
                break;
            case "NO_ROUTE":
                detail = "wlan0 has an address but no default route.";
                break;
            case "CAPTIVE_PORTAL":
                detail = "The fixed HTTP check was intercepted; sign-in may be required.";
                break;
            case "NO_DNS":
                detail = "DNS resolution for " + (result.probe.target || "the target") + " failed; the Pi cannot resolve the host via wlan0.";
                break;
            case "INTERNET_OK":
                detail = "The Pi received the expected HTTP response via wlan0.";
                break;
            default:
                detail = result.probe.associated === false ?
                    "wlan0 is not associated." : "The fixed HTTP check did not reach the Internet.";
                break;
        }
        if (httpStatus !== undefined && httpStatus !== null) {
            detail += " HTTP " + httpStatus + ".";
        }
        visualState = result.state === "INTERNET_OK" ? "online" :
            (result.state === "CAPTIVE_PORTAL" ? "warning" : "offline");
        setText("wan-probe-status", result.state);
        setState("wan-probe-status", visualState);
        setText("wan-probe-detail", detail);
        var quality = result.probe.duration_ms || result.probe.quality_ms || result.probe.latency_ms || result.probe.rtt_ms;
        if (Number.isFinite(Number(quality))) {
            wanQualityHistory.push(Number(quality));
            if (wanQualityHistory.length > 60) {
                wanQualityHistory.shift();
            }
            setText("wan-quality-history", "Quality: " + wanQualityHistory[wanQualityHistory.length - 1] + " ms · " + wanQualityHistory.length + " samples (min " + Math.min.apply(null, wanQualityHistory) + " / max " + Math.max.apply(null, wanQualityHistory) + " ms)");
        }
        return result.state;
    }
    function setProbeUnavailable(message) {
        setText("wan-probe-status", "Unavailable");
        setState("wan-probe-status", "offline");
        setText("wan-probe-detail", message);
        probeInFlight = false;
        if (byId("probe-wan")) {
            byId("probe-wan").disabled = false;
        }
    }
    function sanitizeProbeTarget(value) {
        value = (value || "").trim().toLowerCase();
        if (!value) {
            return "google.com";
        }
        if (value.indexOf("http://") === 0) {
            value = value.slice(7);
        }
        else if (value.indexOf("https://") === 0) {
            value = value.slice(8);
        }
        value = value.replace(/[/].*$/, "").replace(/:\d+$/, "");
        if (!/^[a-z0-9.\-]{1,253}$/.test(value)) {
            return "google.com";
        }
        return value;
    }
    function probeWan() {
        var process;
        var targetInput = byId("probe-target");
        var target = sanitizeProbeTarget(targetInput ? targetInput.value : "");
        if (probeInFlight || mutationState.busy || mutationState.confirmation) {
            return;
        }
        probeInFlight = true;
        if (byId("probe-wan")) {
            byId("probe-wan").disabled = true;
        }
        setText("wan-probe-status", "CHECKING");
        setState("wan-probe-status", "neutral");
        setText("wan-probe-detail", "Testing " + target + " from the Pi via wlan0…");
        showNotice("Running WAN probe to " + target + "…", false);
        try {
            process = cockpit.spawn([HELPER, "probe", target], { superuser: "try" });
        }
        catch (error) {
            setProbeUnavailable("Unable to start the WAN probe.");
            showNotice("Unable to start the WAN probe.", true);
            return;
        }
        observeProcess(process, function (output) {
            var response;
            var state;
            try {
                response = typeof output === "string" ? JSON.parse(output) : output;
                if (!TravelPiTyped.isRecord(response) || response.ok !== true) {
                    throw new Error("invalid probe response");
                }
                state = renderProbe(response);
                showNotice("WAN probe completed: " + state + ".", false);
            }
            catch (error) {
                setProbeUnavailable("TravelPi returned invalid probe data.");
                showNotice("TravelPi returned invalid probe data.", true);
            }
            probeInFlight = false;
            if (byId("probe-wan")) {
                byId("probe-wan").disabled = false;
            }
        }, function (error, data) {
            var probeMessage = helperFailureMessage(error, data, "The WAN probe could not complete.");
            setProbeUnavailable(probeMessage);
            showNotice(probeMessage, true);
        });
    }
    function mutationControls() {
        if (!root) {
            return [];
        }
        return root.querySelectorAll("#hotel-form input, #hotel-form button, #probe-wan, " +
            "#mac-form input, #mac-form button, #ap-form input, #ap-form button, " +
            "#ap-identity-form input, #ap-identity-form button, " +
            "#cake-form input, #cake-form button, [data-action]");
    }
    function setMutationBusy(busy) {
        var controls = mutationControls();
        var index;
        if (root) {
            root.setAttribute("aria-busy", busy ? "true" : "false");
        }
        for (index = 0; index < controls.length; index += 1) {
            controls[index].disabled = busy;
        }
    }
    function setDialogVisible(visible) {
        var dialog = byId("confirm-dialog");
        if (!dialog) {
            return;
        }
        if (visible) {
            dialog.hidden = false;
            dialog.setAttribute("aria-hidden", "false");
            if (typeof dialog.showModal === "function") {
                try {
                    if (!dialog.open) {
                        dialog.showModal();
                    }
                }
                catch (error) {
                    dialog.setAttribute("open", "open");
                }
            }
            else {
                dialog.setAttribute("open", "open");
            }
            return;
        }
        if (typeof dialog.close === "function" && dialog.open) {
            try {
                dialog.close();
            }
            catch (error) {
                dialog.removeAttribute("open");
            }
        }
        else {
            dialog.removeAttribute("open");
        }
        dialog.hidden = true;
        dialog.setAttribute("aria-hidden", "true");
    }
    function cancelConfirmation() {
        if (!mutationState.confirmation) {
            setDialogVisible(false);
            return;
        }
        mutationState = MUTATIONS.cancel(mutationState);
        confirmationMeta = null;
        setDialogVisible(false);
        showNotice("Action cancelled.", false);
    }
    function pendingChangeLabel(change) {
        var command = change && (change.command || change.action);
        var payload = change && change.payload;
        var band = payload && typeof payload.band === "string" ? payload.band : "";
        var rate = payload && typeof payload.rate_kbit === "number" && Number.isFinite(payload.rate_kbit) ? payload.rate_kbit : null;
        if (command === "connect_hotel") {
            return "Connect to hotel Wi-Fi";
        }
        if (command === "apply_mac_clone") {
            return "Apply WAN MAC clone";
        }
        if (command === "set_ap_radio") {
            return band === "2.4ghz" || band === "5ghz" || band === "6ghz" ? "Set AP radio profile: " + band : "Set AP radio profile";
        }
        if (command === "set_wan_band") {
            return band === "auto" ? "Set WAN band: automatic" :
                (band === "2.4ghz" || band === "5ghz" || band === "6ghz" ? "Set WAN band: " + band : "Set WAN band");
        }
        if (command === "set_ap_identity") {
            // Name only: the passphrase must never reach any label.
            return payload && typeof payload.ssid === "string" ? "Set AP identity: " + payload.ssid : "Set AP password";
        }
        if (command === "set_cake_rate") {
            return rate === null ? "Set CAKE rate" : "Set CAKE rate: " + (rate / 1000) + " Mbps";
        }
        return "Queued router change";
    }
    function updatePendingBar() {
        var bar = byId("pending-bar");
        var summary = byId("pending-summary");
        var list = byId("pending-list");
        var hint = byId("pending-hint");
        var index;
        var item;
        if (!bar || !summary) {
            return;
        }
        var pending = mutationState.pending;
        bar.hidden = pending.length === 0;
        summary.textContent = pending.length === 1 ? "1 change waiting to apply" : (pending.length ? pending.length + " changes waiting to apply" : "None");
        if (hint) {
            hint.textContent = pending.length ? "Review the staged changes below. Nothing has been applied yet." : "Nothing has been applied yet.";
        }
        if (!list) {
            return;
        }
        while (list.firstChild) {
            list.removeChild(list.firstChild);
        }
        for (index = 0; index < pending.length; index += 1) {
            item = document.createElement("li");
            item.textContent = pendingChangeLabel(pending[index]);
            (function (removeAction) {
                var remove = document.createElement("button");
                remove.type = "button";
                remove.className = "button button-quiet";
                remove.textContent = "Remove";
                remove.setAttribute("aria-label", "Remove " + pendingChangeLabel(pending[index]));
                remove.addEventListener("click", function () {
                    mutationState = MUTATIONS.removePending(mutationState, removeAction);
                    delete pendingMeta[removeAction];
                    updatePendingBar();
                    showNotice("Pending change removed; the router was not changed.", false);
                });
                item.appendChild(remove);
            }(pending[index].action));
            list.appendChild(item);
        }
    }
    function acceptConfirmation() {
        if (!mutationState.confirmation) {
            return;
        }
        setDialogVisible(false);
        var result = MUTATIONS.confirm(mutationState);
        mutationState = result.state;
        if (result.code === "staged") {
            pendingMeta[result.action] = confirmationMeta;
            updatePendingBar();
            showNotice("Change staged. Press Apply changes to commit it.", false);
        }
        else if (result.code === "execute") {
            driveExecute(result.action, result.payload, confirmationMeta);
        }
        confirmationMeta = null;
    }
    function driveExecute(action, payload, successMessage) {
        runMutation(action, payload, successMessage, function (success) {
            mutationState = MUTATIONS.finishApply(mutationState, success).state;
            if (!mutationState.pending.length) {
                updatePendingBar();
            }
        });
    }
    function requestConfirmation(command, payload) {
        var dialog = byId("confirm-dialog");
        var accepted;
        var spec = MUTATIONS.describe(command, payload || {});
        if (mutationState.busy || mutationState.confirmation) {
            return;
        }
        if (!spec) {
            showNotice(TravelPiTyped.displayValue(TravelPiTyped.firstValue(lastReadiness, ["role_switch.reason"], null), "That action is unavailable on this host."), true);
            return;
        }
        var result = MUTATIONS.request(mutationState, command, spec.payload);
        if (!result.ok) {
            showNotice(result.code === "busy" ? "An action is already in progress." : "That action is unavailable.", true);
            return;
        }
        mutationState = result.state;
        confirmationMeta = spec.success;
        setText("confirm-title", spec.title);
        setText("confirm-message", spec.message);
        if (dialog) {
            setDialogVisible(true);
            return;
        }
        accepted = typeof window !== "undefined" && typeof window.confirm === "function" &&
            window.confirm(spec.title + "\n\n" + spec.message);
        if (accepted) {
            acceptConfirmation();
        }
        else {
            cancelConfirmation();
        }
    }
    function showProgressNotice(command) {
        var notice = byId("notice");
        showNotice(command === "connect_hotel"
            ? "Connecting to hotel Wi-Fi… this can take up to a minute."
            : "Applying…", false);
        if (!notice || typeof notice.getBoundingClientRect !== "function" || typeof notice.scrollIntoView !== "function") {
            return;
        }
        var box = notice.getBoundingClientRect();
        var viewport = typeof window !== "undefined" && window.innerHeight ? window.innerHeight : 0;
        if (viewport && (box.top < 0 || box.bottom > viewport)) {
            notice.scrollIntoView({ block: "nearest" });
        }
    }
    function runMutation(command, input, successMessage, callback) {
        var process;
        var payload;
        var prepared;
        if (!ACTION_COMMANDS[command]) {
            return;
        }
        setMutationBusy(true);
        try {
            // Validate before spawning so a refusal never leaves a root
            // helper blocked on stdin.
            prepared = MUTATIONS.prepare(command, input);
            if (!prepared.ok) {
                throw new Error("action is unavailable");
            }
            process = cockpit.spawn([HELPER, "action"], { superuser: "try" });
            payload = JSON.stringify(Object.assign({}, prepared.payload, { action: prepared.action, confirm: true })) + "\n";
            if (!process || typeof process.input !== "function") {
                throw new Error("helper does not accept input");
            }
            process.input(payload, false);
            process.input("", true);
            showProgressNotice(command);
        }
        catch (error) {
            if (process && typeof process.close === "function") {
                try {
                    process.close();
                }
                catch (closeError) { /* best effort */ }
            }
            setMutationBusy(false);
            showNotice("TravelPi could not start that action.", true);
            if (callback) {
                callback(false);
            }
            return;
        }
        observeProcess(process, function (output) {
            var shown = successMessage;
            var helperResponse = parseHelperJson(output);
            if (helperResponse && helperResponse.ok === true && typeof helperResponse.message === "string" &&
                DEGRADED_MESSAGE.test(helperResponse.message)) {
                // The action applied but only partly; say what the helper said
                // instead of the canned success text.
                shown = helperResponse.message;
            }
            setMutationBusy(false);
            showNotice("Action completed. Refreshing status…", false);
            refreshStatus(function (statusSuccess) {
                if (statusSuccess) {
                    showNotice(shown, shown !== successMessage);
                }
                else {
                    showNotice(shown + " Status refresh failed.", true);
                }
                if (callback) {
                    callback(statusSuccess);
                }
            });
        }, function (error, data) {
            setMutationBusy(false);
            showNotice(helperFailureMessage(error, data, "TravelPi could not complete that action."), true);
            if (callback) {
                callback(false);
            }
        });
    }
    function applyPendingChanges() {
        if (mutationState.busy || !mutationState.pending.length) {
            return;
        }
        setMutationBusy(true);
        function step() {
            var result = MUTATIONS.beginApply(mutationState);
            if (!result.ok) {
                setMutationBusy(false);
                updatePendingBar();
                return;
            }
            mutationState = result.state;
            var action = result.action;
            var payload = result.payload;
            var meta = pendingMeta[action];
            delete pendingMeta[action];
            runMutation(action, payload, meta, function (success) {
                if (!success) {
                    var fin = MUTATIONS.finishApply(mutationState, false);
                    mutationState = fin.state;
                    setMutationBusy(false);
                    updatePendingBar();
                    return;
                }
                var fin = MUTATIONS.finishApply(mutationState, true);
                mutationState = fin.state;
                if (fin.code === "continue") {
                    step();
                }
                else {
                    setMutationBusy(false);
                    updatePendingBar();
                    showNotice("All pending changes applied.", false);
                    refreshStatus();
                }
            });
        }
        step();
    }
    function rollbackPendingChanges() {
        mutationState = MUTATIONS.clearPending(mutationState);
        pendingMeta = {};
        updatePendingBar();
        showNotice("Pending changes rolled back; the router was not changed.", false);
    }
    function signalLevel(value) {
        var dbm = Number(value);
        if (!Number.isFinite(dbm)) {
            return 0;
        }
        if (dbm >= -55) {
            return 4;
        }
        if (dbm >= -67) {
            return 3;
        }
        if (dbm >= -75) {
            return 2;
        }
        return 1;
    }
    var securedScanSsids = {};
    var blankPasswordWarned = "";
    function renderWifiScan(response) {
        var results = byId("wifi-scan-results");
        var networks = response && Array.isArray(response.networks) ? response.networks : [];
        if (!results) {
            return;
        }
        results.textContent = "";
        results.hidden = false;
        if (!networks.length) {
            results.textContent = "No visible networks found.";
            return;
        }
        securedScanSsids = {};
        networks.forEach(function (network) {
            if (network.ssid && network.security === "secured") {
                securedScanSsids[network.ssid] = true;
            }
            var button = document.createElement("button");
            var signal = network.signal_dbm === null || network.signal_dbm === undefined ? "Unknown" : network.signal_dbm + " dBm";
            var secured = network.security === "secured";
            button.type = "button";
            button.className = "wifi-scan-option";
            button.textContent = network.ssid + " · " + signal + " · " + (network.band || "unknown") +
                (network.channel ? " ch" + network.channel : "") + " · " +
                (secured ? "secured, password required" : "open network");
            button.addEventListener("click", function () {
                if (network.ssid && network.ssid.length > 32) {
                    // The connect form caps SSIDs at 32 chars (the helper
                    // refuses longer names); say so instead of prefilling junk.
                    var scanStatus = byId("scan-wifi-status");
                    if (scanStatus) {
                        scanStatus.textContent = "That network's name is " + network.ssid.length +
                            " characters; the connect form caps at 32.";
                    }
                    return;
                }
                var input = byId("hotel-ssid");
                if (input) {
                    input.value = network.ssid;
                }
                var hiddenBox = byId("hotel-hidden");
                if (hiddenBox) {
                    hiddenBox.checked = false;
                }
                var help = byId("hotel-password-help");
                if (help) {
                    help.textContent = secured ?
                        "Secured network: enter this network's WPA password." :
                        "Leave blank for an open network or captive portal.";
                }
                var password = byId("hotel-password");
                if (password && secured && typeof password.focus === "function") {
                    try {
                        password.focus();
                    }
                    catch (error) { /* focus is best-effort */ }
                }
                try {
                    window.localStorage.setItem("travelpi-remembered-ssid", network.ssid);
                }
                catch (error) { /* storage is optional */ }
            });
            results.appendChild(button);
        });
    }
    function renderPortalRow(view) {
        var row = byId("portal-row");
        if (!row) {
            return;
        }
        var portal = TravelPiTyped.isRecord(TravelPiTyped.firstValue(view.health, ["portal"], null)) ?
            TravelPiTyped.firstValue(view.health, ["portal"], {}) : {};
        var state = TravelPiTyped.displayValue(TravelPiTyped.firstValue(portal, ["state"], null), "");
        var url = TravelPiTyped.firstValue(portal, ["portal_url"], null);
        var open = byId("portal-open");
        var note = byId("portal-row-text");
        setHidden("portal-steps", state !== "portal");
        if (state !== "portal") {
            row.hidden = true;
            return;
        }
        row.hidden = false;
        // Display-only affordance (guardrail: never automate portal login).
        // Only http/https portal URLs from the helper's private-host check
        // get a link; anything else is shown as text.
        var safeUrl = typeof url === "string" && /^https?:\/\/[^\s]+$/i.test(url) ? url : null;
        if (open) {
            if (safeUrl) {
                open.setAttribute("href", safeUrl);
                open.hidden = false;
            }
            else {
                open.removeAttribute("href");
                open.hidden = true;
            }
        }
        if (note) {
            note.textContent = safeUrl ?
                "Captive portal detected (" + safeUrl + "). Sign in on the portal page, then re-check." :
                "Captive portal detected. Open http://neverssl.com on your device to sign in, then re-check.";
        }
    }
    function recheckPortal() {
        var note = byId("portal-row-text");
        var process;
        if (note) {
            note.textContent = "Re-checking the hotel portal…";
        }
        try {
            process = cockpit.spawn([HELPER, "portal", "fresh"], { superuser: "try" });
        }
        catch (error) {
            if (note) {
                note.textContent = "Portal re-check could not start.";
            }
            return;
        }
        observeProcess(process, function () {
            refreshStatus();
        }, function (error, data) {
            if (note) {
                note.textContent = helperFailureMessage(error, data, "Portal re-check failed; showing the last known state.");
            }
        });
    }
    function describePdProbe(response) {
        var pd = response && TravelPiTyped.isRecord(response.pd) ? response.pd : null;
        var detail;
        if (!pd || typeof pd.state !== "string") {
            return "Prefix delegation check returned invalid data.";
        }
        detail = typeof pd.detail === "string" && pd.detail ? pd.detail : "No detail reported.";
        if (pd.state === "offered") {
            return detail + " Router offers /" + String(pd.prefix_len) + " — AP delegation is not implemented yet.";
        }
        if (pd.state === "not_offered") {
            return detail + " See README: Global IPv6 for AP clients.";
        }
        return detail;
    }
    function checkPrefixDelegation() {
        var process;
        var status = byId("pd-check-status");
        var button = byId("pd-check");
        if (status) {
            status.textContent = "Checking…";
        }
        if (button) {
            button.disabled = true;
        }
        try {
            process = cockpit.spawn([HELPER, "pd"], { superuser: "try" });
        }
        catch (error) {
            if (button) {
                button.disabled = false;
            }
            if (status) {
                status.textContent = "Prefix delegation check could not start.";
            }
            return;
        }
        observeProcess(process, function (output) {
            if (button) {
                button.disabled = false;
            }
            try {
                if (status) {
                    status.textContent = describePdProbe(parseHelperJson(output));
                }
            }
            catch (error) {
                if (status) {
                    status.textContent = "Prefix delegation check returned invalid data.";
                }
            }
        }, function (error, data) {
            if (button) {
                button.disabled = false;
            }
            if (status) {
                status.textContent = helperFailureMessage(error, data, "Prefix delegation check failed.");
            }
        });
    }
    function scanWifi() {
        var process;
        var status = byId("scan-wifi-status");
        if (mutationState.busy || !byId("scan-wifi")) {
            return;
        }
        if (status) {
            status.textContent = "Scanning wlan0…";
        }
        try {
            process = cockpit.spawn([HELPER, "scan"], { superuser: "try" });
        }
        catch (error) {
            if (status) {
                status.textContent = "Wi-Fi scan could not start.";
            }
            return;
        }
        observeProcess(process, function (output) {
            try {
                renderWifiScan(typeof output === "string" ? JSON.parse(output) : output);
                if (status) {
                    status.textContent = "Select a network; the password is never stored.";
                }
            }
            catch (error) {
                if (status) {
                    status.textContent = "Wi-Fi scan returned invalid data.";
                }
            }
        }, function (error, data) { if (status) {
            status.textContent = helperFailureMessage(error, data, "Wi-Fi scan failed.");
        } });
    }
    function submitHotel(event) {
        var ssidInput = byId("hotel-ssid");
        var passwordInput = byId("hotel-password");
        var ssid;
        var password;
        event.preventDefault();
        if (mutationState.busy || mutationState.confirmation || !ssidInput || !passwordInput) {
            return;
        }
        ssid = String(ssidInput.value || "").trim();
        password = String(passwordInput.value || "");
        if (!ssid) {
            showNotice("Enter the hotel SSID.", true);
            return;
        }
        if (!password && securedScanSsids[ssid] && blankPasswordWarned !== ssid) {
            blankPasswordWarned = ssid;
            showNotice("The scan marked " + ssid + " as secured. Enter its password, or press Connect again to try a remembered profile without one.", true);
            return;
        }
        blankPasswordWarned = "";
        passwordInput.value = "";
        try {
            window.localStorage.setItem("travelpi-remembered-ssid", ssid);
        }
        catch (error) { /* storage is optional */ }
        var hiddenCheckbox = byId("hotel-hidden");
        var hotelPayload = { ssid: ssid, password: password };
        if (hiddenCheckbox && hiddenCheckbox.checked) {
            hotelPayload.hidden = true;
        }
        requestConfirmation("connect_hotel", hotelPayload);
    }
    function submitMac(event) {
        var input = byId("clone-mac");
        var mac;
        event.preventDefault();
        if (mutationState.busy || mutationState.confirmation || !input) {
            return;
        }
        mac = String(input.value || "").trim();
        if (!/^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(mac)) {
            showNotice("Enter a valid MAC address, for example 02:11:22:33:44:55.", true);
            return;
        }
        requestConfirmation("apply_mac_clone", { mac: mac.toLowerCase() });
    }
    function apSelectedBand() {
        var form = byId("ap-form");
        var selected = form && form.querySelector ? form.querySelector('input[name="ap-profile"]:checked') : null;
        return (selected && selected.value) || "2.4ghz";
    }
    function renderApProfile(view) {
        var select = byId("ap-channel-select");
        var six = byId("ap-profile-6-option");
        var hardware = TravelPiTyped.isRecord(view && view.hardware) ? view.hardware : {};
        var ap = TravelPiTyped.isRecord(hardware.ap) ? hardware.ap : {};
        var channels = TravelPiTyped.isRecord(TravelPiTyped.firstValue(ap, ["supported_channels"], null)) ?
            TravelPiTyped.firstValue(ap, ["supported_channels"], {}) : {};
        var sixList = TravelPiTyped.firstValue(channels, ["6ghz"], null);
        if (six) {
            six.hidden = !(Array.isArray(sixList) && sixList.length > 0);
        }
        // Reason beside the missing 6 GHz option: only hardware evidence offers it.
        setHidden("ap-6ghz-reason", Array.isArray(sixList) && sixList.length > 0);
        if (!select) {
            return;
        }
        var list = TravelPiTyped.firstValue(channels, [apSelectedBand()], null);
        var previous = select.value;
        select.innerHTML = "";
        var defaultOption = document.createElement("option");
        defaultOption.value = "";
        defaultOption.textContent = "Default for band";
        select.appendChild(defaultOption);
        if (Array.isArray(list) && list.length > 0) {
            list.forEach(function (channel) {
                var opt = document.createElement("option");
                opt.value = String(channel);
                opt.textContent = "Channel " + channel;
                select.appendChild(opt);
            });
            select.disabled = false;
            // Poll re-renders must not silently drop the channel the user
            // picked; restore it when it is still offered, else fall back.
            if (previous) {
                var keep = list.some(function (channel) { return String(channel) === previous; });
                select.value = keep ? previous : "";
            }
        }
        else {
            // The radio has not reported channels (no iw read): stay on the
            // canonical profile channels rather than inventing a picker.
            select.disabled = true;
        }
    }
    function submitApProfile(event) {
        var form = byId("ap-form");
        var selected;
        var profile;
        event.preventDefault();
        if (mutationState.busy || mutationState.confirmation || !form) {
            return;
        }
        selected = form.querySelector('input[name="ap-profile"]:checked');
        profile = selected && selected.value;
        if (profile !== "2.4ghz" && profile !== "5ghz" && profile !== "6ghz") {
            showNotice("Choose the 2.4 GHz, 5 GHz, or (when the radio proves it) 6 GHz AP profile.", true);
            return;
        }
        var apPayload = { band: profile };
        var apChannel = byId("ap-channel-select");
        var channelValue = apChannel && apChannel.value ? parseInt(apChannel.value, 10) : null;
        if (channelValue !== null && !isNaN(channelValue)) {
            apPayload.channel = channelValue;
        }
        requestConfirmation("set_ap_radio", apPayload);
    }
    function submitApIdentity(event) {
        var ssidInput = byId("ap-identity-ssid");
        var passInput = byId("ap-identity-pass");
        var payload = {};
        var ssid;
        var passphrase;
        event.preventDefault();
        if (mutationState.busy || mutationState.confirmation) {
            return;
        }
        ssid = ssidInput && ssidInput.value ? ssidInput.value.trim() : "";
        passphrase = passInput && passInput.value ? passInput.value : "";
        if (!ssid && !passphrase) {
            showNotice("Enter a new AP name, a new password, or both.", true);
            return;
        }
        if (ssid.length > 32) {
            showNotice("AP name must be 1-32 characters.", true);
            return;
        }
        if (passphrase && (passphrase.length < 8 || passphrase.length > 63)) {
            showNotice("AP password must be 8-63 characters.", true);
            return;
        }
        if (ssid) {
            payload.ssid = ssid;
        }
        if (passphrase) {
            payload.passphrase = passphrase;
        }
        requestConfirmation("set_ap_identity", payload);
        // Password fields clear as soon as the coordinator has the payload.
        if (passInput) {
            passInput.value = "";
        }
    }
    function renderApIdentity(view) {
        var input = byId("ap-identity-ssid");
        if (!input) {
            return;
        }
        var ap = TravelPiTyped.isRecord(view && view.ap) ? view.ap : {};
        var ssid = TravelPiTyped.displayValue(TravelPiTyped.firstValue(ap, ["ap_ssid", "ssid"], null), "");
        // The current name is shown as the placeholder only: an empty field
        // means "keep the name", and the password is never shown anywhere.
        if (ssid) {
            input.placeholder = ssid;
        }
    }
    function submitCakeRate(event) {
        var input = byId("cake-rate-input");
        var rate;
        var match;
        event.preventDefault();
        if (mutationState.busy || mutationState.confirmation || !input) {
            return;
        }
        rate = String(input.value || "").trim();
        match = /^(\d+(?:\.\d+)?)(?:\s*(kbit|mbit|gbit|kbps|mbps|gbps))?$/i.exec(rate);
        if (!match || Number(match[1]) <= 0) {
            showNotice("Enter a positive CAKE rate, such as 20 or 20mbit.", true);
            return;
        }
        // The field reads as Mbps, and an explicit suffix is honored rather
        // than dropped: "20 kbit" must not become 20 Mbit.
        var factors = { kbit: 1, kbps: 1, mbit: 1000, mbps: 1000, gbit: 1000000, gbps: 1000000 };
        var perMbit = factors[(match[2] || "mbit").toLowerCase()] || 1000;
        requestConfirmation("set_cake_rate", { rate_kbit: Math.round(Number(match[1]) * perMbit) });
    }
    // Payload construction is presentation: read the control, validate the
    // shape, and hand the coordinator the payload. Every confirmation string
    // comes from MUTATIONS.describe (travelpi-mutations.js).
    function payloadFor(action, target) {
        switch (action) {
            case "restart_services":
                return target === "sqm" || target === "ap" ? { targets: [target] } : null;
            case "wake_peer":
                return target ? { target: target } : null;
            case "set_dns_stack":
                return target === "adguard" || target === "unbound" ? { service: target } : null;
            case "set_ipv6":
                return target === "on" || target === "off" ? { mode: target } : null;
            case "set_sqm_mode":
                return target === "auto" || target === "manual" || target === "off" ? { mode: target } : null;
            case "set_cpu_governor":
                return target === "conservative" || target === "ondemand" || target === "performance"
                    ? { governor: target } : null;
            case "reclaim_memory":
            case "reboot":
                return {};
            default:
                return null;
        }
    }
    function handleAction(event) {
        var action = event.currentTarget.getAttribute("data-action");
        var target = event.currentTarget.getAttribute("data-target");
        event.preventDefault();
        if (!action || !ACTION_COMMANDS[action]) {
            return;
        }
        var payload = payloadFor(action, target);
        if (!payload) {
            return;
        }
        requestConfirmation(action, payload);
    }
    function bindEvents() {
        var hotelForm = byId("hotel-form");
        var macForm = byId("mac-form");
        var apForm = byId("ap-form");
        var cakeForm = byId("cake-form");
        var refresh = byId("refresh");
        var cancel = byId("confirm-cancel");
        var accept = byId("confirm-accept");
        var dialog = byId("confirm-dialog");
        var actions;
        var index;
        // Cockpit-managed navigation: raw href navigation inside the app frame
        // makes the frame load the shell (doubled System/Help/Session bars on
        // phones). cockpit.jump asks the shell to switch pages cleanly.
        var navLinks = root.querySelectorAll("a.text-link[href^=\"/travelpi\"]");
        for (index = 0; index < navLinks.length; index += 1) {
            navLinks[index].addEventListener("click", function (event) {
                var href = event.currentTarget.getAttribute("href");
                if (href && href.indexOf("#") === 0) {
                    return;
                }
                if (typeof cockpit !== "undefined" && cockpit && typeof cockpit.jump === "function") {
                    event.preventDefault();
                    cockpit.jump(href);
                }
            });
        }
        if (hotelForm) {
            hotelForm.addEventListener("submit", submitHotel);
            try {
                var rememberedSsid = window.localStorage.getItem("travelpi-remembered-ssid");
                if (rememberedSsid && byId("hotel-ssid")) {
                    byId("hotel-ssid").value = rememberedSsid;
                }
            }
            catch (error) { /* storage is optional */ }
        }
        if (byId("scan-wifi")) {
            byId("scan-wifi").addEventListener("click", function (event) { event.preventDefault(); scanWifi(); });
        }
        if (byId("pd-check")) {
            byId("pd-check").addEventListener("click", function (event) { event.preventDefault(); checkPrefixDelegation(); });
        }
        if (byId("portal-recheck")) {
            byId("portal-recheck").addEventListener("click", function (event) { event.preventDefault(); recheckPortal(); });
        }
        ["ap-profile-24", "ap-profile-5", "ap-profile-6"].forEach(function (id) {
            var radio = byId(id);
            if (radio) {
                radio.addEventListener("change", function () { renderApProfile(lastView); });
            }
        });
        var autoChannel = byId("ap-channel-auto");
        if (autoChannel) {
            autoChannel.addEventListener("click", function (event) {
                event.preventDefault();
                var select = byId("ap-channel-select");
                // Auto = no explicit channel: the helper applies the band's
                // default (2.4 -> 6, 5 GHz -> 36, 6 GHz -> best available).
                if (select) {
                    select.value = "";
                }
            });
        }
        if (byId("clone-mac-random")) {
            byId("clone-mac-random").addEventListener("click", function (event) {
                event.preventDefault();
                if (mutationState.busy || mutationState.confirmation) {
                    return;
                }
                requestConfirmation("apply_mac_clone", { mode: "random" });
            });
        }
        if (byId("clone-mac-default")) {
            byId("clone-mac-default").addEventListener("click", function (event) {
                event.preventDefault();
                if (mutationState.busy || mutationState.confirmation) {
                    return;
                }
                requestConfirmation("apply_mac_clone", { mode: "default" });
            });
        }
        if (macForm) {
            macForm.addEventListener("submit", submitMac);
        }
        if (apForm) {
            apForm.addEventListener("submit", submitApProfile);
        }
        var apIdentityForm = byId("ap-identity-form");
        if (apIdentityForm) {
            apIdentityForm.addEventListener("submit", submitApIdentity);
        }
        if (cakeForm) {
            cakeForm.addEventListener("submit", submitCakeRate);
        }
        if (refresh) {
            refresh.addEventListener("click", function (event) {
                event.preventDefault();
                refreshStatus();
            });
        }
        if (byId("probe-wan")) {
            byId("probe-wan").addEventListener("click", function (event) {
                event.preventDefault();
                probeWan();
            });
        }
        if (byId("probe-target")) {
            byId("probe-target").addEventListener("change", function () { probeWan(); });
            byId("probe-target").addEventListener("keydown", function (event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    probeWan();
                }
            });
        }
        if (byId("vpn-provider") && byId("vpn-toggle")) {
            byId("vpn-provider").addEventListener("change", function () {
                var provider = byId("vpn-provider").value;
                var active = byId("vpn-toggle").getAttribute("data-vpn-" + provider) === "active";
                byId("vpn-toggle").textContent = active ? "Turn off " + provider : "Turn on " + provider;
                byId("vpn-toggle").setAttribute("data-vpn-active", active ? "true" : "false");
            });
        }
        if (byId("vpn-toggle")) {
            byId("vpn-toggle").addEventListener("click", function (event) {
                var provider = (byId("vpn-provider") || {}).value || "tailscale";
                var button = byId("vpn-toggle");
                var enabled = button.getAttribute("data-vpn-active") !== "true";
                event.preventDefault();
                requestConfirmation("vpn_toggle", { provider: provider, enabled: enabled });
            });
        }
        if (byId("tailscale-auth-btn")) {
            byId("tailscale-auth-btn").addEventListener("click", function (event) {
                var keyInput = byId("tailscale-authkey");
                var authkey = keyInput ? keyInput.value : "";
                event.preventDefault();
                requestConfirmation("tailscale_auth", { authkey: authkey });
            });
        }
        if (cancel) {
            cancel.addEventListener("click", function (event) {
                event.preventDefault();
                cancelConfirmation();
            });
        }
        if (accept) {
            accept.addEventListener("click", function (event) {
                event.preventDefault();
                acceptConfirmation();
            });
        }
        if (dialog) {
            dialog.addEventListener("cancel", function (event) {
                event.preventDefault();
                cancelConfirmation();
            });
        }
        if (byId("apply-pending")) {
            byId("apply-pending").addEventListener("click", applyPendingChanges);
        }
        if (byId("rollback-pending")) {
            byId("rollback-pending").addEventListener("click", rollbackPendingChanges);
        }
        if (byId("repair-radios")) {
            byId("repair-radios").addEventListener("click", function () {
                requestConfirmation("reset_radios", {});
            });
        }
        if (byId("ap-switch-5ghz")) {
            byId("ap-switch-5ghz").addEventListener("click", function () {
                requestConfirmation("set_ap_radio", { band: "5ghz" });
            });
        }
        if (byId("ap-switch-2ghz")) {
            byId("ap-switch-2ghz").addEventListener("click", function () {
                requestConfirmation("set_ap_radio", { band: "2.4ghz" });
            });
        }
        if (byId("wan-band-select")) {
            byId("wan-band-select").addEventListener("change", function () { bandTouched.wan = true; });
        }
        if (byId("lan-band-select")) {
            byId("lan-band-select").addEventListener("change", function () { bandTouched.lan = true; });
        }
        if (byId("apply-wan-band")) {
            byId("apply-wan-band").addEventListener("click", function () {
                var select = byId("wan-band-select");
                var chosen = select ? select.value : "";
                if (chosen !== "auto" && BAND_ORDER.indexOf(chosen) === -1) {
                    showNotice("Choose a WAN band first.", true);
                    return;
                }
                bandTouched.wan = false;
                requestConfirmation("set_wan_band", { band: chosen });
            });
        }
        if (byId("apply-lan-band")) {
            byId("apply-lan-band").addEventListener("click", function () {
                var select = byId("lan-band-select");
                var chosen = select ? select.value : "";
                if (BAND_ORDER.indexOf(chosen) === -1) {
                    showNotice("Choose a LAN band first.", true);
                    return;
                }
                bandTouched.lan = false;
                requestConfirmation("set_ap_radio", { band: chosen });
            });
        }
        if (byId("copy-mac-clone")) {
            byId("copy-mac-clone").addEventListener("click", function () {
                var field = byId("mac-clone-current");
                var input = field && field.tagName === "INPUT" ? field : (field ? field.querySelector("input") : null);
                var val = input ? input.value : "";
                if (!val || val === "—") {
                    showNotice("No WAN MAC is available to copy yet.", true);
                    return;
                }
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(val).then(function () {
                        showNotice("WAN MAC copied to the clipboard.", false);
                    }, function () {
                        showNotice("Select the MAC field and copy it manually.", true);
                    });
                }
            });
        }
        if (byId("governor-slider")) {
            byId("governor-slider").addEventListener("change", function () {
                var names = ["conservative", "ondemand", "performance"];
                var name = names[Number(byId("governor-slider").value)] || "ondemand";
                if (mutationState.busy || mutationState.confirmation) {
                    return;
                }
                requestConfirmation("set_cpu_governor", { governor: name });
            });
        }
        if (byId("view-clients") && byId("clients-details")) {
            byId("view-clients").addEventListener("click", function () {
                var details = byId("clients-details");
                details.open = !details.open;
                byId("view-clients").setAttribute("aria-expanded", details.open ? "true" : "false");
                if (details.open) {
                    details.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            });
        }
        updatePendingBar();
        actions = root.querySelectorAll("[data-action]");
        for (index = 0; index < actions.length; index += 1) {
            actions[index].addEventListener("click", handleAction);
        }
    }
    function init() {
        root = byId("travelpi-app");
        if (!root) {
            return;
        }
        if (typeof cockpit === "undefined" || !cockpit || typeof cockpit.spawn !== "function") {
            showNotice("Cockpit API is unavailable.", true);
            return;
        }
        setDialogVisible(false);
        bindEvents();
        lastStatusAt = Date.now();
        function refreshFreshness() {
            var age;
            if (freshnessTimer) {
                window.clearTimeout(freshnessTimer);
                freshnessTimer = null;
            }
            if (document.hidden) {
                return;
            }
            if (lastStatusAt) {
                age = Math.round((Date.now() - lastStatusAt) / 1000);
                setText("freshness-state", age > 45 ? "(stale · " + age + "s ago)" : "(" + age + "s ago)");
                setState("freshness-state", age > 45 ? "warning" : "neutral");
            }
            // Bridge-stall recovery: the Cockpit shell can unpaint this frame when its
            // WS session tears down (init race), leaving spawn promises unresolved
            // forever. Release the wedged poll, then reload if the link stays dead.
            if (statusInFlight && statusStartedAt && Date.now() - statusStartedAt > 60000) {
                statusInFlight = false;
                statusPollFailures += 1;
                showNotice("Status bridge stalled; reconnecting.", true);
                scheduleStatusRefresh(3000);
            }
            if (lastStatusAt && Date.now() - lastStatusAt > 600000) {
                location.reload();
            }
            freshnessTimer = window.setTimeout(refreshFreshness, 5000);
        }
        refreshFreshness();
        document.addEventListener("visibilitychange", function () {
            if (document.hidden) {
                if (freshnessTimer) {
                    window.clearTimeout(freshnessTimer);
                    freshnessTimer = null;
                }
                scheduleStatusRefresh();
            }
            else {
                refreshFreshness();
                refreshStatus();
            }
        });
        refreshStatus();
        probeWan();
        window.setInterval(probeWan, 120000);
    }
    if (typeof document === "undefined") {
        return;
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    }
    else {
        init();
    }
}());
