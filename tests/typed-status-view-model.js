const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("travelpi-typed.js", "utf8");
class Element {
    constructor() { this.textContent = ""; this.attributes = {}; this.hidden = false; }
    setAttribute(name, value) { this.attributes[name] = value; }
    removeAttribute(name) { delete this.attributes[name]; }
}
class Input extends Element { constructor() { super(); this.value = ""; this.checked = false; } }
const elements = { notice: new Element(), field: new Input(), badge: new Element() };
const context = {
    document: { getElementById: (id) => elements[id] || null },
    HTMLInputElement: Input,
    HTMLTextAreaElement: class extends Input {},
};
vm.runInNewContext(source, context, { filename: "travelpi-typed.js" });

assert.ok(context.TravelPiTyped);
// The classic-script artifact keeps the require seam the Node tests load it
// through; the classic-script guard deliberately allows it.
const required = require("../travelpi-typed.js");
assert.strictEqual(typeof required.statusViewModel, "function");
assert.strictEqual(typeof required.probeState, "function");

const view = context.TravelPiTyped.statusViewModel({
    status: {
        wan: { interface: "wlan0", state: "connected", ssid: "HotelWiFi", signal_dbm: -42, freq: 5180 },
        ap: { interface: "wlan1", state: "up", ssid: "TravelPi", channel: 36 },
        currentWanMac: "02:11:22:33:44:55",
        clients: [{ ip: "192.168.200.10" }, { ip: "192.168.200.11" }],
        readiness: { role_switch: { available: false, reason: "fixture" } },
    },
});

assert.strictEqual(view.wan.ssid, "HotelWiFi");
assert.strictEqual(view.ap.channel, 36);
assert.strictEqual(view.status.wan_ssid, "HotelWiFi");
assert.strictEqual(view.status.wan_signal, -42);
assert.strictEqual(view.status.wan_frequency, 5180);
assert.strictEqual(view.status.currentWanMac, "02:11:22:33:44:55");
assert.strictEqual(view.status.client_count, 2, "client_count normalizes the LAN client list");
assert.strictEqual(view.readiness.role_switch.available, false);
context.TravelPiTyped.setText("field", "typed value");
context.TravelPiTyped.setSwitch("field", true);
context.TravelPiTyped.setBadge("badge", "Ready", "ok");
context.TravelPiTyped.showNotice("Done", false);
assert.strictEqual(elements.field.value, "typed value");
assert.strictEqual(elements.field.checked, true);
assert.strictEqual(elements.badge.attributes["data-state"], "ok");
assert.strictEqual(elements.notice.textContent, "Done");

// Legacy payloads (wlan0/wlan1 sections, no radioInventory) must project into
// the same canonical fields the render code reads.
const historicalShape = context.TravelPiTyped.statusViewModel({
    status: {
        wlan0: { state: "connected", gateway: "192.0.2.1" },
        wlan1: { state: "up" },
        spoofedWanMac: "02:11:22:33:44:55",
        hardware: { wan: { present: true }, ap: { present: false } },
        clients: { count: 3 },
    },
});
assert.strictEqual(historicalShape.status.wan.state, "connected");
assert.strictEqual(historicalShape.status.currentWanMac, "02:11:22:33:44:55");
assert.strictEqual(historicalShape.status.wanMacClone.active, false);
assert.strictEqual(historicalShape.status.hardware.ap.present, false);
assert.strictEqual(historicalShape.status.client_count, 3, "client_count accepts the count-record shape");

const canonical = context.TravelPiTyped.statusViewModel({
    status: {
        wan: { state: "connected" },
        ap: { state: "up" },
        currentWanMac: "aa:bb:cc:dd:ee:ff",
        wanMacClone: { active: true, address: "02:11:22:33:44:55" },
        radioInventory: {
            wan: { interface: "wlan0", role: "wan", present: true, label: "Pi internal Wi-Fi" },
            ap: { interface: "wlan1", role: "ap", present: true, label: "USB Wi-Fi adapter" },
        },
        hardware: { wan: { present: true }, ap: { present: true } },
    },
});
assert.strictEqual(canonical.status.currentWanMac, "aa:bb:cc:dd:ee:ff");
assert.strictEqual(canonical.status.wanMacClone.address, "02:11:22:33:44:55");
assert.notStrictEqual(canonical.status.currentWanMac, canonical.status.wanMacClone.address);
assert.strictEqual(canonical.status.wanMacClone.active, true);
assert.strictEqual(canonical.status.hardware.wan.role, "wan");
assert.strictEqual(canonical.status.hardware.ap.role, "ap");

// The probe response nests its own `status` string; it is not a status payload.
assert.strictEqual(context.TravelPiTyped.probeState({ status: "CAPTIVE_PORTAL", probe: { http_status: 302 } }).state, "CAPTIVE_PORTAL");
assert.strictEqual(context.TravelPiTyped.probeState({ probe: { status: "INTERNET_OK", http_status: 204 } }).state, "INTERNET_OK");

// An empty payload must degrade to a full, readable view model, not throw.
const empty = context.TravelPiTyped.statusViewModel({});
assert.strictEqual(empty.status.wan_state, null);
assert.strictEqual(empty.status.client_count, 0);

console.log("typed status view-model checks passed");
