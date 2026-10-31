const assert = require("assert");
const mutations = require("../travelpi-mutations.js");

assert.strictEqual(mutations.descriptor("connect_hotel").staged, true);
assert.ok(mutations.descriptor("connect_hotel").message({ ssid: "HotelWiFi", hidden: true }).includes("hidden network"));
assert.strictEqual(mutations.descriptor("vpn_toggle").staged, false);
assert.strictEqual(mutations.descriptor("wan_flip").available, false);
assert.deepStrictEqual(mutations.prepare("vpn_toggle", { provider: "tailscale" }), {
    ok: true, action: "vpn_toggle", payload: { provider: "tailscale" }
});

let state = mutations.createState();
let result = mutations.request(state, "set_cake_rate", { rate_kbit: 20000 });
assert.strictEqual(result.code, "awaiting_confirmation");
result = mutations.confirm(result.state);
assert.strictEqual(result.code, "staged");
state = result.state;
assert.deepStrictEqual(state.pending, [{ action: "set_cake_rate", payload: { rate_kbit: 20000 } }]);

result = mutations.request(state, "set_cake_rate", { rate_kbit: 30000 });
state = mutations.confirm(result.state).state;
assert.strictEqual(state.pending.length, 1);
assert.strictEqual(state.pending[0].payload.rate_kbit, 30000);

result = mutations.request(state, "wan_flip", {});
assert.strictEqual(result.code, "unavailable");
assert.strictEqual(result.ok, false);
assert.strictEqual(result.state.confirmation, null);
assert.strictEqual(mutations.allowed("wan_flip"), false);

result = mutations.request(state, "vpn_toggle", { provider: "tailscale", enabled: true });
result = mutations.confirm(result.state);
assert.strictEqual(result.code, "execute");
assert.strictEqual(result.action, "vpn_toggle");
assert.deepStrictEqual(result.payload, { provider: "tailscale", enabled: true });
state = result.state;
assert.strictEqual(state.busy, true);
assert.strictEqual(mutations.request(state, "reboot", {}).code, "busy");

state = mutations.createState();
state = mutations.confirm(mutations.request(state, "set_cake_rate", { rate_kbit: 20000 }).state).state;
state = mutations.confirm(mutations.request(state, "apply_mac_clone", { mac: "02:11:22:33:44:55" }).state).state;
result = mutations.beginApply(state);
assert.strictEqual(result.action, "set_cake_rate");
result = mutations.finishApply(result.state, false);
assert.strictEqual(result.code, "apply_failed");
assert.strictEqual(result.state.busy, false);

// clearPending / removePending
state = mutations.createState();
state = mutations.confirm(mutations.request(state, "set_cake_rate", { rate_kbit: 1000 }).state).state;
state = mutations.confirm(mutations.request(state, "apply_mac_clone", { mac: "02:11:22:33:44:55" }).state).state;
assert.strictEqual(state.pending.length, 2);
state = mutations.removePending(state, "set_cake_rate").state;
assert.strictEqual(state.pending.length, 1);
assert.strictEqual(state.pending[0].action, "apply_mac_clone");
state = mutations.clearPending(state).state;
assert.strictEqual(state.pending.length, 0);

// non-staged execute: confirm sets busy, finishApply clears it
state = mutations.createState();
state = mutations.confirm(mutations.request(state, "vpn_toggle", { provider: "tailscale" }).state).state;
assert.strictEqual(state.busy, true);
state = mutations.finishApply(state, true).state;
assert.strictEqual(state.busy, false);

// full staged apply loop, mirroring travelpi.ts's driving glue with a fake executor
state = mutations.createState();
state = mutations.confirm(mutations.request(state, "set_cake_rate", { rate_kbit: 5000 }).state).state;
state = mutations.confirm(mutations.request(state, "apply_mac_clone", { mac: "02:11:22:33:44:55" }).state).state;
var executed = [];
function runStep() {
    var begin = mutations.beginApply(state);
    state = begin.state;
    executed.push(begin.action);
    var fin = mutations.finishApply(state, true);
    state = fin.state;
    if (fin.code === "continue") { runStep(); }
}
runStep();
assert.deepStrictEqual(executed, ["set_cake_rate", "apply_mac_clone"]);
assert.strictEqual(state.busy, false);
assert.strictEqual(state.pending.length, 0);

// AP profile copy: channel appears when chosen, canonical defaults named
// when not, and 6 GHz is named for what it is (Phase E).
var apCopy = mutations.describe("set_ap_radio", { band: "5ghz", channel: 149 });
assert.ok(apCopy.message.includes("5 GHz / Wi-Fi 6 on channel 149"), apCopy.message);
apCopy = mutations.describe("set_ap_radio", { band: "2.4ghz" });
assert.ok(apCopy.message.includes("2.4 GHz on channel 6"), apCopy.message);
apCopy = mutations.describe("set_ap_radio", { band: "6ghz" });
assert.ok(apCopy.title.includes("6 GHz"), apCopy.title);
assert.ok(apCopy.message.includes("6 GHz / Wi-Fi 6E on the best available channel"), apCopy.message);

// AP identity copy: names the change, never echoes the passphrase (Phase F).
var apId = mutations.describe("set_ap_identity", { ssid: "Camp Van", passphrase: "supersecret12" });
assert.ok(apId.title.includes("name and password"), apId.title);
assert.ok(!apId.message.includes("supersecret12"), "the copy must never echo the passphrase");
assert.ok(apId.message.includes("Camp Van"), apId.message);
apId = mutations.describe("set_ap_identity", { ssid: "Camp Van" });
assert.ok(apId.message.includes("password stays as it is"), apId.message);
apId = mutations.describe("set_ap_identity", { passphrase: "anothersecret9" });
assert.ok(!apId.message.includes("anothersecret9"), "the copy must never echo the passphrase");
assert.ok(apId.message.includes("AP name stays as it is"), apId.message);

console.log("mutation coordinator checks passed");
