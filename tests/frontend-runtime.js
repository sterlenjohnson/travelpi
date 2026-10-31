const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("travelpi.js", "utf8");
assert.ok(source.includes("visibilitychange"));
assert.ok(source.includes("Math.min(240000"));
assert.ok(!source.includes("setInterval(function ()"));
// Bridge-stall recovery: poll release + self-heal reload (shell init-race white screens)
assert.ok(source.includes("status bridge stalled") || source.includes("Status bridge stalled"), "stall release missing");
assert.ok(source.includes("location.reload()"), "stall watchdog reload missing");
assert.ok(/lastStatusAt && Date\.now\(\) - lastStatusAt > 600000/.test(source), "watchdog threshold missing");
// Cockpit-managed page navigation (no nested-shell frame navigation)
assert.ok(source.includes("cockpit.jump("), "shell-managed nav jump missing");

// Power telemetry rendering: run the compiled renderHealth/renderPower against a fake DOM,
// following the vm + element harness of tests/typed-status-view-model.js.
function extractFunction(name, text) {
    const start = text.indexOf("function " + name);
    assert.ok(start !== -1, "compiled function " + name + " not found in travelpi.js");
    let depth = 0;
    let end = -1;
    for (let index = start; index < text.length; index += 1) {
        if (text[index] === "{") { depth += 1; }
        else if (text[index] === "}") {
            depth -= 1;
            if (depth === 0) { end = index + 1; break; }
        }
    }
    assert.ok(end !== -1, "unbalanced braces while extracting " + name);
    return text.slice(start, end);
}

// Helper failure messages: cockpit.spawn rejects with (error, data); data is the helper stdout.
{
    const sandbox = { TravelPiTyped: { isRecord: (v) => v !== null && typeof v === "object" && !Array.isArray(v) } };
    vm.createContext(sandbox);
    vm.runInContext(extractFunction("parseHelperJson", source) + "\n" + extractFunction("helperFailureMessage", source), sandbox);
    const msg = (e, d) => sandbox.helperFailureMessage(e, d, "generic");
    assert.strictEqual(msg({ problem: "protocol-error" }, JSON.stringify({ ok: false, error: { code: "x", message: "Helper said no" } })), "Helper said no");
    assert.ok(/Connection dropped/.test(msg({ problem: "terminated" }, "")));
    assert.ok(/Connection dropped/.test(msg({ problem: "disconnected" }, null)));
    assert.ok(/Administrative access/.test(msg({ problem: "access-denied" }, "")));
    assert.ok(/Administrative access/.test(msg({}, JSON.stringify({ ok: false, error: { code: "not_privileged", message: "m" } }))));
    assert.strictEqual(msg({ problem: "internal-error" }, "not json"), "generic");
    assert.strictEqual(msg(undefined, undefined), "generic");
}

class Element {
    constructor() {
        this.textContent = ""; this.attributes = {}; this.hidden = false;
        this.value = "";
        this.children = [];
        this.handlers = {};
        const self = this;
        this._innerHTML = "";
        Object.defineProperty(this, "innerHTML", {
            get: function () { return self._innerHTML; },
            set: function (value) {
                self._innerHTML = value;
                if (value === "") { self.children.length = 0; }
            },
        });
        this._classes = new Set();
        this.classList = {
            add: function (c) { self._classes.add(c); },
            remove: function (c) { self._classes.delete(c); },
            contains: function (c) { return self._classes.has(c); },
        };
    }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
    appendChild(child) { this.children.push(child); }
    addEventListener(name, handler) {
        (this.handlers[name] = this.handlers[name] || []).push(handler);
    }
}
const elements = {
    "quick-health-state": new Element(),
    "quick-health-detail": new Element(),
    "quick-health-chip": new Element(),
    "quick-power-state": new Element(),
    "quick-power-chip": new Element(),
    "quick-power-detail": new Element(),
    "quick-sqm-autotune": new Element(),
    "quick-sqm-detail": new Element(),
    "quick-sqm-state": new Element(),
    "quick-sqm-chip": new Element(),
    "quick-ipv6-state": new Element(),
    "quick-ipv6-detail": new Element(),
    "quick-ipv6-chip": new Element(),
    "quick-dns-state": new Element(),
    "quick-dns-detail": new Element(),
    "quick-dns-chip": new Element(),
    "vitals-internet": new Element(),
    "portal-row": new Element(),
    "portal-row-text": new Element(),
    "portal-open": new Element(),
    "vitals-ap": new Element(),
    "vitals-dns": new Element(),
    "vitals-mem": new Element(),
    "vitals-power": new Element(),
    "issue-banner": new Element(),
    "spark-signal": new Element(),
    "spark-temp": new Element(),
    "spark-tune": new Element(),
    "spark-count": new Element(),
    "quick-memory-detail": new Element(),
    "quick-governor-state": new Element(),
    "governor-slider": new Element(),
    "quick-dns-mode-note": new Element(),
    "dns-mode-adguard": new Element(),
    "dns-mode-unbound": new Element(),
    "ipv6-on": new Element(),
    "ipv6-off": new Element(),
    "sqm-mode-auto": new Element(),
    "sqm-mode-manual": new Element(),
    "sqm-mode-off": new Element(),
    "ap-state": new Element(),
    "ap-chip": new Element(),
    "ap-chip-text": new Element(),
    "ap-band": new Element(),
    "ap-interface": new Element(),
    "ap-hardware": new Element(),
    "ap-ssid": new Element(),
    "ap-channel": new Element(),
    "ap-clients": new Element(),
    "detail-ap-frequency": new Element(),
    "detail-ap-width": new Element(),
    "detail-ap-txpower": new Element(),
    "detail-wan-rates": new Element(),
    "ap-wifi6": new Element(),
    "topo-ap-detail": new Element(),
    "topo-clients-label": new Element(),
    "topo-clients-detail": new Element(),
    "topo-line-lan": new Element(),
    "client-summary": new Element(),
    "cake-kind": new Element(),
    "cake-rate": new Element(),
    "cake-mode-help": new Element(),
    "cake-rate-input": new Element(),
    "stage-cake-rate": new Element(),
    "cake-enabled-toggle": new Element(),
    "wifi-scan-results": new Element(),
    "scan-wifi-status": new Element(),
    "hotel-ssid": new Element(),
    "hotel-password": new Element(),
    "hotel-password-help": new Element(),
    "ap-channel-select": new Element(),
    "ap-profile-6-option": new Element(),
    "ap-identity-ssid": new Element(),
    "ap-identity-pass": new Element(),
    "wan-band-field": new Element(),
    "lan-band-field": new Element(),
    "wan-band-select": new Element(),
    "lan-band-select": new Element(),
    "wan-band-label": new Element(),
    "lan-band-label": new Element(),
    "radio-roles-line": new Element(),
    "radio-bands-unavailable": new Element(),
    "portal-steps": new Element(),
    "hotel-hidden": new Element(),
    "hotel-ssid": new Element(),
    "hotel-password": new Element(),
    "role-swap-reason": new Element(),
    "wan-band-reason": new Element(),
    "ap-6ghz-reason": new Element(),
    "dns-mode-reason": new Element(),
    "quick-ipv6-mode-note": new Element(),
    "client-rows": new Element(),
};
// Fixtures are host-shaped payloads run through the projection, so render*
// sees exactly the normalized view model the app builds at runtime.
const viewModel = (raw) => context.TravelPiTyped.statusViewModel(raw);
const renderView = (name, raw) => context[name](viewModel(raw));

const context = {
    document: {
        getElementById: (id) => elements[id] || null,
        createElement: function () { return new Element(); },
    },
    window: {
        localStorage: {
            store: {},
            setItem: function (key, value) { this.store[key] = value; },
            getItem: function (key) { return (key in this.store) ? this.store[key] : null; },
        },
    },
    HTMLInputElement: class {},
    HTMLTextAreaElement: class {},
    EMPTY: "—",
};
vm.runInNewContext(fs.readFileSync("travelpi-typed.js", "utf8"), context, { filename: "travelpi-typed.js" });
context.setText = function (id, value) { context.TravelPiTyped.setText(id, String(value)); };
context.setState = function (id, state) { context.TravelPiTyped.setState(id, state); };
context.setBadge = function (id, text, state) { context.TravelPiTyped.setBadge(id, text, state || "neutral"); };
context.byId = function (id) { return elements[id] || null; };
context.setHidden = function (id, hidden) { if (elements[id]) { elements[id].hidden = hidden; } };
context.BAND_ORDER = ["2.4ghz", "5ghz", "6ghz"];
context.bandTouched = { wan: false, lan: false };
context.setSwitch = function () {};
context.clientCount = function (value) { return Array.isArray(value) ? value.length : (value || 0); };
context.renderClients = function () {};
vm.runInNewContext(extractFunction("renderPower", source) + "\n" + extractFunction("renderHealth", source) + "\n" + extractFunction("renderAp", source) + "\n" + extractFunction("renderDnsPrivacy", source) + "\n" + extractFunction("renderVitals", source) + "\n" + extractFunction("renderSparkline", source) + "\n" + extractFunction("renderNetwork", source) + "\n" + extractFunction("renderPortalRow", source) + "\n" + extractFunction("renderWifiScan", source) + "\n" + extractFunction("apSelectedBand", source) + "\n" + extractFunction("renderApProfile", source) + "\n" + extractFunction("renderApIdentity", source) + "\n" + extractFunction("submitApIdentity", source) + "\n" + extractFunction("bandLabel", source) + "\n" + extractFunction("reportedBands", source) + "\n" + extractFunction("fillBandSelect", source) + "\n" + extractFunction("renderRadioBands", source),
    context, { filename: "render-health" });

// undervolt-history signal with core voltage, no current sensor, OTG up with 2 devices
renderView('renderHealth', {
    health: {
        memory_available_mb: 150, memory_total_mb: 415, swap_free_mb: 210, swap_total_mb: 249,
        power: {
            state: "warning", temperature_c: 61, throttled: "0x00000006", detail: "Dual-supply rail nominal",
            signal: "undervolt-history", under_volt_now: false, under_volt_history: true, throttle_history: true,
            core_volts: 1.26, current_ma: null, power_w: null, current_sensor: null, governor: "ondemand",
            usb_otg_present: true, usb_devices: 2,
        },
    },
});
assert.strictEqual(elements["quick-power-chip"].textContent, "Under-voltage history");
assert.strictEqual(elements["quick-power-chip"].attributes["data-state"], "warning");
assert.strictEqual(elements["quick-power-state"].textContent, "Under-voltage history");
assert.strictEqual(elements["quick-memory-detail"].textContent,
    "RAM 150 MB free of 415 MB · Swap 210 MB free of 249 MB — clearing caches frees page cache only; swap frees as processes exit.");
assert.strictEqual(elements["quick-governor-state"].textContent, "Governor: ondemand");
assert.strictEqual(elements["governor-slider"].value, "1");
assert.ok(elements["quick-power-detail"].textContent.includes("1.26 V core"));
assert.ok(elements["quick-power-detail"].textContent.includes("2 USB devices"));
assert.ok(elements["quick-power-detail"].textContent.includes("no current sensor (INA219 optional)"));
assert.ok(elements["quick-power-detail"].textContent.includes("flags 6"));
assert.ok(elements["issue-banner"].textContent.includes("Under-voltage since boot"));
assert.ok(elements["issue-banner"].textContent.includes("Power throttling detected"));
assert.strictEqual(elements["issue-banner"].attributes["data-state"], "warning");

// clean signal with a live current sensor
renderView('renderHealth', {
    health: {
        power: {
            state: "ok", temperature_c: 45, throttled: "0x00000000",
            signal: "clean", core_volts: 1.21, current_ma: 142, power_w: 0.71,
            usb_otg_present: true, usb_devices: 1,
        },
    },
});
assert.strictEqual(elements["quick-power-chip"].textContent, "Power OK");
assert.strictEqual(elements["quick-power-chip"].attributes["data-state"], "online");
assert.ok(elements["quick-power-detail"].textContent.includes("142 mA · 0.71 W"));
assert.ok(elements["quick-power-detail"].textContent.includes("OTG port up · 1 USB devices"));
assert.strictEqual(elements["issue-banner"].textContent, "No open issues.");

// unclean shutdown recorded by the boot power recorder overrides a clean signal
renderView('renderHealth', {
    health: {
        power: {
            state: "ok", temperature_c: 44, throttled: "0x00000000",
            signal: "clean", core_volts: 1.26,
            usb_otg_present: true, usb_devices: 2,
            unexpected_shutdown: true,
        },
    },
});
assert.strictEqual(elements["quick-power-chip"].textContent, "Power loss shutdown");
assert.strictEqual(elements["quick-power-chip"].attributes["data-state"], "warning");
assert.ok(elements["quick-power-detail"].textContent.includes("power-loss shutdown"));
assert.ok(elements["issue-banner"].textContent.includes("Power-loss shutdown (previous boot ended abruptly)"));

// USB demand, unsynced clock, elevated storage risk, radio resets
renderView('renderHealth', {
    health: {
        radio_reset_events: 2,
        radio_link_events: 3,
        radio_recovery_events: 2,
        last_radio_recovery: 1761000000,
        radio_watchdog: "armed",
        mem_guard_events: 3,
        last_mem_guard_event: "2026-10-28T11:05:00Z",
        last_mem_guard_action: "kill",
        mem_watchdog: "armed",
        portal: { state: "portal", portal_url: "http://172.20.0.1/portal/login" },
        power: {
            state: "warning", temperature_c: 52, throttled: "0x00010000",
            signal: "undervolt-history", under_volt_history: true,
            core_volts: 1.25, usb_otg_present: true, usb_devices: 3, usb_demand_ma: 300,
            clock_synced: false, storage_risk: "elevated", power_loss_count: 2,
        },
    },
});
assert.ok(elements["quick-power-detail"].textContent.includes("3 USB devices · ~300 mA demand"));
assert.ok(elements["quick-power-detail"].textContent.includes("flags 10000"));
assert.ok(elements["issue-banner"].textContent.includes("Clock unsynced (NTP pending)"));
assert.ok(elements["issue-banner"].textContent.includes("Storage risk elevated (power losses: 2)"));
assert.ok(elements["issue-banner"].textContent.includes("Radio resets: 2"));
assert.ok(elements["issue-banner"].textContent.includes("Radio link failures: 3"));
assert.ok(elements["issue-banner"].textContent.includes("Radio auto-recoveries: 2 (last "));
assert.ok(elements["issue-banner"].textContent.includes("Memory guard actions: 3 (last: kill 2026-10-28 11:05 UTC)"));
assert.ok(elements["issue-banner"].textContent.includes("Captive portal detected (http://172.20.0.1/portal/login)"));
assert.ok(!elements["issue-banner"].textContent.includes("Memory guard stale"));
assert.ok(!elements["issue-banner"].textContent.includes("Memory guard not installed"));
assert.ok(elements["issue-banner"].textContent.includes("9 open issues: Under-voltage since boot"));
assert.ok(elements["issue-banner"].textContent.includes("Radio resets: 2"));
assert.strictEqual(elements["issue-banner"].attributes["data-state"], "warning");
assert.ok(!elements["issue-banner"].textContent.includes("watchdog"));

// AP carrier evidence overrides a unit-active claim (2026-10-27 incident)
renderView('renderAp', {
    clients: [],
    wan: {},
    hardware: {},
    ap: { interface: "wlan1", state: "up", carrier: false, stations: 0, ssid: "TravelPi", channel: 36, freq: 5180, wifi6: true },
});
assert.strictEqual(elements["ap-chip-text"].textContent, "NO CARRIER");
assert.strictEqual(elements["ap-chip"].attributes["data-state"], "offline");
assert.ok(elements["ap-state"].textContent.includes("no carrier"));
assert.strictEqual(elements["topo-line-lan"].attributes["data-state"], "offline");

renderView('renderAp', {
    clients: [],
    wan: {},
    hardware: {},
    ap: { interface: "wlan1", state: "up", carrier: true, stations: 2, ssid: "TravelPi", channel: 36, freq: 5180, wifi6: true },
});
assert.strictEqual(elements["ap-chip-text"].textContent, "ON");
assert.strictEqual(elements["ap-chip"].attributes["data-state"], "online");
assert.strictEqual(elements["topo-line-lan"].attributes["data-state"], "online");

// older helper payload without the additive power keys must degrade gracefully
renderView('renderHealth', { health: { load_1m: 0.4 } });
assert.strictEqual(elements["quick-power-chip"].textContent, "Unknown");
assert.strictEqual(elements["quick-power-chip"].attributes["data-state"], "neutral");
assert.strictEqual(elements["quick-power-detail"].textContent, "—");
assert.strictEqual(elements["issue-banner"].textContent, "No open issues.");
assert.strictEqual(elements["issue-banner"].attributes["data-state"], "ok");

// SQM auto-tune line in the traffic-shaping card
context.showNotice = function () {};
renderView('renderDnsPrivacy', {
    services: { unbound: "active" },
    dnsStack: { service: "active", mode: "off", stack_mode: "adguard", upstream: "Unbound 127.0.0.1:5335" },
    ipv6: { state: "ula-only", detail: "ULA advertised", radvd: true },
    mac: { address: "aa:bb:cc:dd:ee:ff" },
    cake: { state: "active", mode: "auto", rate: "18Mbit",
            autotune: { state: "active", age_s: 7200, applied_down_mbit: 36, applied_up_mbit: 18 } },
});
assert.strictEqual(elements["quick-sqm-detail"].textContent, "18Mbit");
assert.strictEqual(elements["quick-sqm-state"].textContent, "CAKE auto");
assert.strictEqual(elements["quick-ipv6-state"].textContent, "ULA only");
assert.strictEqual(elements["quick-dns-state"].textContent, "Filtered (AdGuard Home)");
assert.strictEqual(elements["dns-mode-adguard"].attributes["aria-pressed"], "true");
assert.strictEqual(elements["ipv6-on"].attributes["aria-pressed"], "true");
assert.ok(elements["dns-mode-adguard"].classList.contains("is-active"));
assert.ok(elements["quick-sqm-autotune"].textContent.includes("Auto-tuned 36 down / 18 Mbit"),
    elements["quick-sqm-autotune"].textContent);
assert.ok(elements["quick-sqm-autotune"].textContent.includes("2h ago"));

renderView('renderDnsPrivacy', {
    dnsStack: {}, ipv6: {}, mac: {},
    cake: { state: "active", mode: "pinned", rate: "25Mbit", autotune: { state: "pinned" } },
});
assert.ok(elements["quick-sqm-autotune"].textContent.includes("pinned"));
assert.strictEqual(elements["quick-sqm-state"].textContent, "CAKE manual");
assert.strictEqual(elements["sqm-mode-manual"].attributes["aria-pressed"], "true");
assert.strictEqual(elements["quick-dns-state"].textContent, "AdGuard Home unavailable");

renderView('renderDnsPrivacy', {
    dnsStack: { stack_mode: "unbound" }, ipv6: { state: "off", radvd: false }, mac: {},
    cake: { state: "inactive", mode: "off", autotune: { state: "off" } },
});
assert.strictEqual(elements["quick-sqm-state"].textContent, "CAKE off");
assert.strictEqual(elements["sqm-mode-off"].attributes["aria-pressed"], "true");
assert.strictEqual(elements["quick-dns-state"].textContent, "Plain recursive (Unbound on :53)");
assert.strictEqual(elements["quick-ipv6-state"].textContent, "Off");
assert.strictEqual(elements["ipv6-off"].attributes["aria-pressed"], "true");

// Advanced CAKE form coherence: rate prefilled from live qdisc, editable only in manual mode
renderView('renderNetwork', {
    wan: { interface: "wlan0" }, route: {},
    cake: { state: "active", mode: "auto", qdisc: "cake", rate: "13Mbit" },
    services: { hostapd: "active", dnsmasq: "active", sqm: "active" },
    gateway: "10.0.0.1",
});
assert.strictEqual(elements["cake-rate"].textContent, "13Mbit · auto");
assert.strictEqual(elements["cake-mode-help"].textContent.slice(0, 18), "Auto mode tunes th");
assert.strictEqual(elements["cake-rate-input"].value, "13");
assert.strictEqual(elements["cake-rate-input"].disabled, true);
assert.strictEqual(elements["stage-cake-rate"].disabled, true);

renderView('renderNetwork', {
    wan: {}, route: {},
    cake: { state: "active", mode: "pinned", qdisc: "cake", rate: "25Mbit" },
    services: {}, canonicalGateway: null,
});
assert.strictEqual(elements["cake-rate"].textContent, "25Mbit · manual");
assert.strictEqual(elements["cake-mode-help"].textContent.slice(0, 13), "Manual mode: ");
assert.strictEqual(elements["cake-rate-input"].value, "25");
assert.strictEqual(elements["cake-rate-input"].disabled, false);
assert.strictEqual(elements["stage-cake-rate"].disabled, false);

renderView('renderNetwork', {
    wan: {}, route: {},
    cake: { state: "inactive", mode: "off", qdisc: "none" },
    services: {}, canonicalGateway: null,
});
assert.strictEqual(elements["cake-rate"].textContent, "— · off");
assert.strictEqual(elements["cake-mode-help"].textContent.slice(0, 15), "Shaping is off.");
assert.strictEqual(elements["cake-rate-input"].disabled, true);
assert.strictEqual(elements["cake-enabled-toggle"].attributes["data-state"], "warning");

// Vitals strip + issue banner
renderView('renderVitals', {
    clients: [{}, {}, {}],
    wan: { state: "connected", signal: -54 },
    ap: { state: "up", carrier: true },
    dnsStack: { service: "active" },
    health: { temperature_c: 56.9, power: { signal: "clean" }, memory_used_percent: 71, swap_used_percent: 47 },
});
assert.strictEqual(elements["vitals-internet"].textContent, "Internet online · -54 dBm");
assert.strictEqual(elements["vitals-internet"].attributes["data-state"], "online");
assert.strictEqual(elements["vitals-ap"].textContent, "AP on · 3 clients");
assert.strictEqual(elements["vitals-dns"].attributes["data-state"], "online");
assert.strictEqual(elements["vitals-power"].textContent, "Power OK · 56.9°C");
assert.strictEqual(elements["vitals-mem"].textContent, "Mem 71% · swap 47%");
assert.strictEqual(elements["vitals-mem"].attributes["data-state"], "online");

renderView('renderVitals', {
    clients: [],
    wan: { state: "disconnected" },
    ap: { state: "up", carrier: false },
    dnsStack: { service: "inactive" },
    health: { power: { signal: "undervolt-now" } },
});
assert.strictEqual(elements["vitals-ap"].textContent, "AP no carrier");
assert.strictEqual(elements["vitals-ap"].attributes["data-state"], "offline");
assert.strictEqual(elements["vitals-dns"].attributes["data-state"], "offline");
assert.strictEqual(elements["vitals-power"].attributes["data-state"], "warning");



// Sparklines: inline SVG polyline from the ring buffer, nothing when sparse
context.renderSparkline("spark-count", [40, 30, 35, 20]);
assert.ok(elements["spark-count"].innerHTML.includes("<polyline points=\"0,2 40,12 80,7 120,22"),
    elements["spark-count"].innerHTML);
context.renderSparkline("spark-count", [40]);
assert.strictEqual(elements["spark-count"].innerHTML, "");

// Change-only DOM writes: identical setText must not touch the element
var counted = new Element();
var writes = 0;
Object.defineProperty(counted, "textContent", {
    get: function () { return counted._value; },
    set: function (v) { writes += 1; counted._value = v; },
});
elements["counted-target"] = counted;
context.TravelPiTyped.setText("counted-target", "same value");
context.TravelPiTyped.setText("counted-target", "same value");
context.TravelPiTyped.setText("counted-target", "same value");
assert.strictEqual(writes, 1);
context.TravelPiTyped.setText("counted-target", "changed");
assert.strictEqual(writes, 2);

// Captive-portal affordance: display-only row with a validated portal link
renderView('renderPortalRow', {
    status: { health: { portal: { state: "portal", portal_url: "http://10.14.25.3/login" } } },
});
assert.strictEqual(elements["portal-row"].hidden, false);
assert.strictEqual(elements["portal-open"].attributes["href"], "http://10.14.25.3/login");
assert.strictEqual(elements["portal-open"].hidden, false);
assert.ok(elements["portal-row-text"].textContent.includes("10.14.25.3/login"));

// Non-http portal URLs never become links (display-only guardrail)
renderView('renderPortalRow', {
    status: { health: { portal: { state: "portal", portal_url: "javascript:alert(1)" } } },
});
assert.strictEqual(elements["portal-row"].hidden, false);
assert.strictEqual(elements["portal-open"].hidden, true);
assert.strictEqual(elements["portal-open"].attributes["href"], undefined);

// Portal guidance checklist shows only in the portal state
assert.strictEqual(elements["portal-steps"].hidden, false);

// Online: row hidden entirely
renderView('renderPortalRow', {
    status: { health: { portal: { state: "online", portal_url: null } } },
});
assert.strictEqual(elements["portal-row"].hidden, true);
assert.strictEqual(elements["portal-steps"].hidden, true);

// Scan pick: rows show band + channel + security, and a click prefills the
// form with security-aware password help (Phase C: scan, pick, connect).
context.renderWifiScan({ networks: [
    { ssid: "HotelNet", signal_dbm: -50, band: "5ghz", channel: 36, security: "secured" },
    { ssid: "OpenGuest", signal_dbm: -70, band: "2.4ghz", channel: 6, security: "open" },
] });
assert.strictEqual(elements["wifi-scan-results"].children.length, 2);
const securedButton = elements["wifi-scan-results"].children[0];
const openButton = elements["wifi-scan-results"].children[1];
assert.ok(securedButton.textContent.includes("5ghz ch36"));
assert.ok(securedButton.textContent.includes("secured, password required"));
assert.ok(openButton.textContent.includes("open network"));
let focused = 0;
elements["hotel-password"].focus = function () { focused += 1; };
securedButton.handlers.click[0]();
assert.strictEqual(elements["hotel-ssid"].value, "HotelNet");
assert.ok(elements["hotel-password-help"].textContent.includes("WPA password"));
assert.strictEqual(focused, 1);
assert.strictEqual(context.window.localStorage.store["travelpi-remembered-ssid"], "HotelNet");
elements["hotel-hidden"].checked = true;
openButton.handlers.click[0]();
assert.strictEqual(elements["hotel-hidden"].checked, false, "picking a scanned network clears the hidden flag");
assert.strictEqual(elements["hotel-ssid"].value, "OpenGuest");
assert.ok(elements["hotel-password-help"].textContent.includes("Leave blank"));
assert.strictEqual(focused, 1, "open networks must not demand a password focus");

// AP profile channels (Phase E): picker follows the radio's reported
// channels, 6 GHz appears only on hardware evidence.
const apForm = new Element();
const apChecked = { value: "5ghz", checked: true };
apForm.querySelector = function () { return apChecked; };
elements["ap-form"] = apForm;
renderView('renderApProfile', {
    status: { radios: { ap: { interface: "wlan1", present: true, supported_channels: {
        "2.4ghz": [1, 6, 11], "5ghz": [36, 40, 149], "6ghz": [1, 37] } } } },
});
assert.strictEqual(elements["ap-profile-6-option"].hidden, false);
assert.strictEqual(elements["ap-channel-select"].children.length, 4);
assert.strictEqual(elements["ap-channel-select"].children[1].textContent, "Channel 36");
assert.strictEqual(elements["ap-channel-select"].disabled, false);

renderView('renderApProfile', { status: { radios: { ap: { interface: "wlan1", present: true } } } });
assert.strictEqual(elements["ap-profile-6-option"].hidden, true);
assert.strictEqual(elements["ap-channel-select"].children.length, 1);
assert.strictEqual(elements["ap-channel-select"].disabled, true);

// Poll re-renders keep the channel the user picked (D4); a channel that
// disappeared from the hardware report falls back to the band default.
elements["ap-channel-select"].value = "40";
renderView('renderApProfile', {
    status: { radios: { ap: { interface: "wlan1", present: true, supported_channels: {
        "2.4ghz": [1, 6, 11], "5ghz": [36, 40, 149], "6ghz": [1, 37] } } } },
});
assert.strictEqual(elements["ap-channel-select"].value, "40");
elements["ap-channel-select"].value = "999";
renderView('renderApProfile', {
    status: { radios: { ap: { interface: "wlan1", present: true, supported_channels: {
        "2.4ghz": [1, 6, 11], "5ghz": [36, 40, 149], "6ghz": [1, 37] } } } },
});
assert.strictEqual(elements["ap-channel-select"].value, "");

// AP identity submission (Phase F): payload built, password field cleared
// right after staging, empty form refused, current name shown as placeholder.
context.mutationState = { busy: false, confirmation: null };
context.apRequests = [];
context.requestConfirmation = function (action, payload) { context.apRequests.push({ action: action, payload: payload }); };
context.showNotice = function () {};
elements["ap-identity-ssid"].value = "Camp Van";
elements["ap-identity-pass"].value = "newsecret123";
context.submitApIdentity({ preventDefault: function () {} });
assert.strictEqual(context.apRequests.length, 1);
assert.strictEqual(context.apRequests[0].action, "set_ap_identity");
assert.strictEqual(context.apRequests[0].payload.ssid, "Camp Van");
assert.strictEqual(context.apRequests[0].payload.passphrase, "newsecret123");
assert.strictEqual(elements["ap-identity-pass"].value, "", "the password field must clear after staging");

elements["ap-identity-ssid"].value = "";
elements["ap-identity-pass"].value = "";
context.submitApIdentity({ preventDefault: function () {} });
assert.strictEqual(context.apRequests.length, 1, "an empty identity form must be refused");

renderView('renderApIdentity', { status: { ap: { ap_ssid: "VanLife" } } });
assert.strictEqual(elements["ap-identity-ssid"].placeholder, "VanLife");

// Radio bands: dropdowns follow the inventory, only reported bands are
// offered, and a side with no usable bands is hidden entirely.
const bandValues = (id) => elements[id].children.map((o) => o.value);
renderView('renderRadioBands', {
    status: {
        wan: { interface: "wlan0", band: "2.4ghz", band_setting: "5ghz" },
        ap: { interface: "wlan1", band: "5ghz" },
        radioInventory: {
            wan: { interface: "wlan0", present: true, label: "Pi internal Wi-Fi", bands: ["2.4ghz", "5ghz"] },
            ap: { interface: "wlan1", present: true, label: "USB Wi-Fi adapter", bands: ["2.4ghz", "5ghz", "6ghz"] },
        },
    },
});
assert.strictEqual(elements["wan-band-field"].hidden, false);
assert.strictEqual(elements["lan-band-field"].hidden, false);
assert.deepStrictEqual(bandValues("wan-band-select"), ["auto", "2.4ghz", "5ghz"]);
assert.deepStrictEqual(bandValues("lan-band-select"), ["2.4ghz", "5ghz", "6ghz"]);
assert.strictEqual(elements["wan-band-select"].value, "5ghz", "WAN pre-selects the pinned band");
assert.strictEqual(elements["lan-band-select"].value, "5ghz", "LAN pre-selects the current AP band");
assert.strictEqual(elements["radio-bands-unavailable"].hidden, true);
assert.ok(elements["radio-roles-line"].textContent.includes("WAN: Pi internal Wi-Fi (wlan0)"));
assert.ok(elements["radio-roles-line"].textContent.includes("LAN: USB Wi-Fi adapter (wlan1)"));

// 2.4 GHz-only WAN radio and an absent LAN radio.
renderView('renderRadioBands', {
    status: {
        radioInventory: {
            wan: { interface: "wlan0", present: true, label: "Pi internal Wi-Fi", bands: ["2.4ghz"] },
            ap: { interface: "wlan1", present: false, bands: ["2.4ghz", "5ghz"] },
        },
    },
});
assert.deepStrictEqual(bandValues("wan-band-select"), ["auto", "2.4ghz"]);
assert.strictEqual(elements["wan-band-field"].hidden, false);
assert.strictEqual(elements["lan-band-field"].hidden, true, "an absent radio hides its dropdown");

// No inventory at all: both hidden, honest notice shown.
renderView('renderRadioBands', { status: {} });
assert.strictEqual(elements["wan-band-field"].hidden, true);
assert.strictEqual(elements["lan-band-field"].hidden, true);
assert.strictEqual(elements["radio-bands-unavailable"].hidden, false);

// Control reasons: role swap (readiness), WAN band without a connection.
renderView('renderRadioBands', {
    status: {
        wan_state: "disconnected",
        radioInventory: { wan: { interface: "wlan0", present: true, bands: ["2.4ghz", "5ghz"] } },
        readiness: { role_switch: { available: false, reason: "Requires wired-uplink evidence" } },
    },
});
assert.strictEqual(elements["role-swap-reason"].hidden, false);
assert.ok(elements["role-swap-reason"].textContent.includes("Requires wired-uplink evidence"));
assert.strictEqual(elements["wan-band-reason"].hidden, false);
renderView('renderRadioBands', {
    status: {
        wan_state: "connected",
        radioInventory: { wan: { interface: "wlan0", present: true, bands: ["2.4ghz", "5ghz"] } },
    },
});
assert.strictEqual(elements["wan-band-reason"].hidden, true, "connected WAN needs no band reason");

// 6 GHz reason follows hardware evidence.
renderView('renderApProfile', { status: { radioInventory: { ap: { present: true, bands: ["2.4ghz"] } } } });
assert.strictEqual(elements["ap-6ghz-reason"].hidden, false);
renderView('renderApProfile', { status: { radioInventory: { ap: { present: true, bands: ["6ghz"], supported_channels: { "6ghz": [1, 5] } } } } });
assert.strictEqual(elements["ap-6ghz-reason"].hidden, true);

// Connected devices: name/IP/MAC, Private MAC badge on the locally-administered bit.
vm.runInNewContext(extractFunction("isPrivateMac", source) + "\n" + extractFunction("renderClients", source), context);
context.renderClients({ count: 2, items: [
    { mac: "02:aa:bb:cc:dd:01", ip: "192.0.2.10", hostname: "phone" },
    { mac: "00:aa:bb:cc:dd:02", ip: "192.0.2.11", hostname: "*" },
] });
const clientRows = elements["client-rows"].children;
assert.strictEqual(clientRows.length, 2);
assert.strictEqual(clientRows[0].children[0].textContent, "phone");
assert.strictEqual(clientRows[0].children[1].textContent, "192.0.2.10");
assert.ok(clientRows[0].children[2].textContent.includes("02:aa:bb:cc:dd:01"));
assert.strictEqual(clientRows[0].children[2].children.length, 1, "private MAC gets a badge");
assert.strictEqual(clientRows[0].children[2].children[0].textContent, "Private MAC");
assert.strictEqual(clientRows[1].children[2].children.length, 0, "vendor MAC gets no badge");
assert.strictEqual(clientRows[1].children[0].textContent, "\u2014", "unknown dnsmasq name is not shown as *");
elements["client-rows"].children.length = 0; // mock textContent does not clear children
context.renderClients({ count: 0, items: [] });
assert.strictEqual(elements["client-rows"].children.length, 1);
assert.ok(elements["client-rows"].children[0].children[0].textContent.includes("No connected devices"));

// IPv6 and DNS one-line mode explanations.
renderView('renderDnsPrivacy', { status: { ipv6: { state: "ula-only" }, dnsStack: { service: "active", stack_mode: "adguard" } } });
assert.ok(elements["quick-ipv6-mode-note"].textContent.includes("no global address"));
assert.strictEqual(elements["dns-mode-reason"].hidden, true);
renderView('renderDnsPrivacy', { status: { ipv6: { state: "active" }, dnsStack: { service: "inactive", stack_mode: "adguard" } } });
assert.ok(elements["quick-ipv6-mode-note"].textContent.includes("global IPv6"));
assert.strictEqual(elements["dns-mode-reason"].hidden, false);
renderView('renderDnsPrivacy', { status: { ipv6: { state: "off" } } });
assert.ok(elements["quick-ipv6-mode-note"].textContent.includes("IPv4 only"));

// Hidden network: submitHotel stages the typed SSID with hidden:true only when checked.
{
    const staged = [];
    const form = { preventDefault() {} };
    const hotelCtx = {
        byId: (id) => elements[id] || null, showNotice() {}, mutationState: { busy: false, confirmation: null },
        securedScanSsids: {}, blankPasswordWarned: "", window: context.window,
        requestConfirmation: (action, payload) => staged.push([action, payload]),
    };
    vm.createContext(hotelCtx);
    vm.runInContext(extractFunction("submitHotel", source), hotelCtx);
    elements["hotel-ssid"].value = "HotelWiFi"; elements["hotel-password"].value = "x";
    elements["hotel-hidden"].checked = true;
    hotelCtx.submitHotel(form);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(staged[0])), ["connect_hotel", { ssid: "HotelWiFi", password: "x", hidden: true }]);
    elements["hotel-ssid"].value = "HotelWiFi"; elements["hotel-password"].value = "x";
    elements["hotel-hidden"].checked = false;
    hotelCtx.submitHotel(form);
    assert.deepStrictEqual(JSON.parse(JSON.stringify(staged[1])), ["connect_hotel", { ssid: "HotelWiFi", password: "x" }]);
}

console.log("frontend runtime checks passed");

// In-progress notice: a started action must never leave the page looking inert.
{
    const notice = new Element();
    const scrolls = [];
    notice.getBoundingClientRect = () => ({ top: 900, bottom: 940 });
    notice.scrollIntoView = (options) => scrolls.push(options);
    const shown = [];
    const sandbox = {
        byId: (id) => (id === "notice" ? notice : null),
        showNotice: (message, isError) => shown.push([message, isError]),
        window: { innerHeight: 600 },
    };
    vm.createContext(sandbox);
    vm.runInContext(extractFunction("showProgressNotice", source), sandbox);
    sandbox.showProgressNotice("connect_hotel");
    assert.strictEqual(JSON.stringify(shown[0]), JSON.stringify(["Connecting to hotel Wi-Fi… this can take up to a minute.", false]));
    assert.strictEqual(JSON.stringify(scrolls), JSON.stringify([{ block: "nearest" }]));
    sandbox.showProgressNotice("set_cake_rate");
    assert.strictEqual(JSON.stringify(shown[1]), JSON.stringify(["Applying…", false]));
    // Already visible: no scroll. Missing notice element or DOM APIs: no throw.
    notice.getBoundingClientRect = () => ({ top: 100, bottom: 140 });
    sandbox.showProgressNotice("set_cake_rate");
    assert.strictEqual(scrolls.length, 2);
    delete notice.scrollIntoView;
    sandbox.showProgressNotice("set_cake_rate");
}

// Prefix-delegation check: button states and the sentences shown for each probe state.
{
    function pdSandbox(spawnImpl) {
        const status = new Element();
        const button = new Element();
        const sandbox = {
            HELPER: "/h",
            TravelPiTyped: { isRecord: (v) => v !== null && typeof v === "object" && !Array.isArray(v) },
            byId: (id) => (id === "pd-check-status" ? status : (id === "pd-check" ? button : null)),
            cockpit: { spawn: spawnImpl },
            observeProcess: (process, ok, fail) => process.then(ok, fail),
        };
        vm.createContext(sandbox);
        vm.runInContext([extractFunction("parseHelperJson", source), extractFunction("helperFailureMessage", source),
            extractFunction("describePdProbe", source), extractFunction("checkPrefixDelegation", source)].join("\n"), sandbox);
        return { sandbox, status, button };
    }
    const reply = (pd) => JSON.stringify({ ok: true, action: "pd_probe", pd: Object.assign({ prefix: null, prefix_len: null, valid_s: null, server: null }, pd) });
    (async () => {
        let argv;
        let ctx = pdSandbox((a) => { argv = a; return Promise.resolve(reply({ state: "offered", prefix: "2001:db8::", prefix_len: 60, detail: "The network offers prefix delegation: 2001:db8::/60." })); });
        ctx.sandbox.checkPrefixDelegation();
        assert.strictEqual(ctx.status.textContent, "Checking…");
        assert.strictEqual(ctx.button.disabled, true);
        assert.strictEqual(JSON.stringify(argv), JSON.stringify(["/h", "pd"]));
        await new Promise((r) => setImmediate(r));
        assert.strictEqual(ctx.button.disabled, false);
        assert.ok(ctx.status.textContent.includes("Router offers /60 — AP delegation is not implemented yet"), ctx.status.textContent);

        ctx = pdSandbox(() => Promise.resolve(reply({ state: "not_offered", detail: "No DHCPv6 server answered." })));
        ctx.sandbox.checkPrefixDelegation();
        await new Promise((r) => setImmediate(r));
        assert.ok(ctx.status.textContent.includes("See README: Global IPv6 for AP clients"));
        assert.ok(!ctx.status.textContent.includes("Router offers"));

        ctx = pdSandbox(() => Promise.resolve(reply({ state: "unavailable", detail: "wlan0 is not connected." })));
        ctx.sandbox.checkPrefixDelegation();
        await new Promise((r) => setImmediate(r));
        assert.strictEqual(ctx.status.textContent, "wlan0 is not connected.");

        ctx = pdSandbox(() => Promise.reject({ problem: "access-denied" }));
        ctx.sandbox.checkPrefixDelegation();
        await new Promise((r) => setImmediate(r));
        assert.ok(/Administrative access/.test(ctx.status.textContent));
        assert.strictEqual(ctx.button.disabled, false);

        ctx = pdSandbox(() => Promise.resolve("not json"));
        ctx.sandbox.checkPrefixDelegation();
        await new Promise((r) => setImmediate(r));
        assert.ok(/invalid data/.test(ctx.status.textContent));
        console.log("pd check runtime checks passed");
    })().catch((error) => { console.error(error); process.exit(1); });
}
