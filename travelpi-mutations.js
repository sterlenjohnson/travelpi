(function (root, factory) {
    "use strict";
    if (typeof module !== "undefined" && module.exports) {
        module.exports = factory();
    } else {
        root.TravelPiMutations = factory();
    }
}(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    // Single source of the mutation coordinator's semantics *and* of every
    // user-visible confirmation string. Action names and payload shapes live
    // in travelpi-contracts.ts; the host's allowlist lives in the helper.
    // `title`, `message` and `success` are strings or functions of the payload,
    // so payload-dependent wording stays here and travelpi.ts only builds the
    // payload from the form controls.
    function bandLabel(band) {
        return band === "2.4ghz" ? "2.4 GHz" : (band === "5ghz" ? "5 GHz" : (band === "6ghz" ? "6 GHz" : String(band)));
    }

    var descriptors = {
        connect_hotel: {
            staged: true, refresh: true,
            title: "Connect to hotel Wi-Fi?",
            message: function (p) {
                return 'Connect wlan0 to ' + (p.hidden ? 'hidden network ' : '') + '"' + p.ssid + '"? The password will be sent once and will not be saved.';
            },
            success: "Hotel connection request completed."
        },
        apply_mac_clone: {
            staged: true, refresh: true,
            title: function (p) {
                if (p.mode === "random") { return "Randomize WAN MAC?"; }
                if (p.mode === "default") { return "Reset WAN MAC to hardware default?"; }
                return "Apply WAN MAC clone?";
            },
            message: function (p) {
                if (p.mode === "random") {
                    return "Your hotel Wi-Fi adapter will use a fresh randomized MAC address on this network. The WAN connection restarts briefly.";
                }
                if (p.mode === "default") {
                    return "Any cloned or randomized WAN MAC is cleared; wlan0 uses its burned-in hardware address. The WAN connection restarts briefly, and the previous setting is restored if connectivity breaks.";
                }
                return "Apply " + p.mac + " to wlan0? The WAN connection may briefly restart.";
            },
            success: function (p) {
                if (p.mode === "random") { return "Randomized WAN MAC applied."; }
                if (p.mode === "default") { return "WAN MAC reset to the hardware default."; }
                return "WAN MAC clone request completed.";
            }
        },
        set_ap_radio: {
            staged: true, refresh: true,
            title: function (p) {
                if (p.band === "2.4ghz") { return "Switch TravelPi AP to 2.4 GHz?"; }
                if (p.band === "6ghz") { return "Switch TravelPi AP to 6 GHz?"; }
                return "Switch TravelPi AP to 5 GHz?";
            },
            message: function (p) {
                var defaults = { "2.4ghz": 6, "5ghz": 36 };
                var channel = " on channel " + (p.channel ? p.channel : defaults[p.band]);
                if (p.band === "2.4ghz") {
                    return "Move the TravelPi AP to 2.4 GHz" + channel + ". This is staged until Apply Changes.";
                }
                if (p.band === "6ghz") {
                    return "Move the TravelPi AP to 6 GHz / Wi-Fi 6E" + (p.channel ? channel : " on the best available channel") +
                        ". This is staged until Apply Changes.";
                }
                return "Move the TravelPi AP to 5 GHz / Wi-Fi 6" + channel +
                    ". This is staged until Apply Changes - like GL-iNet Wireless.";
            },
            success: "AP profile switch request completed."
        },
        set_wan_band: {
            staged: true, refresh: true,
            title: function (p) {
                return p.band === "auto" ? "Let the WAN radio pick its band?" : "Pin the WAN radio to " + bandLabel(p.band) + "?";
            },
            message: function (p) {
                var target = p.band === "auto" ? "automatic band selection" : bandLabel(p.band);
                return "Move the hotel Wi-Fi (wlan0) to " + target + ". The WAN connection briefly restarts and the previous band is restored if it does not verify. This is staged until Apply Changes.";
            },
            success: "WAN band request completed."
        },
        set_ap_identity: {
            staged: true, refresh: true,
            title: function (p) {
                if (p.ssid && p.passphrase) { return "Change AP name and password?"; }
                return p.ssid ? "Change the AP name?" : "Change the AP password?";
            },
            message: function (p) {
                // The new passphrase is deliberately not echoed into the copy.
                var bits = [];
                bits.push(p.ssid ? "The AP will broadcast \u201c" + p.ssid + "\u201d" : "The AP name stays as it is");
                bits.push(p.passphrase ? "the WPA password changes (it is never shown back)" : "the password stays as it is");
                return bits.join("; ") + ". Devices connected to the AP will need to reconnect after Apply Changes.";
            },
            success: "AP identity update request completed."
        },
        set_cake_rate: {
            staged: true, refresh: true,
            title: "Set CAKE rate?",
            message: function (p) { return "Set the SQM/CAKE rate to " + (p.rate_kbit / 1000) + " Mbps?"; },
            success: "CAKE rate request completed."
        },
        restart_services: {
            staged: false, refresh: true,
            title: function (p) { return p.targets[0] === "sqm" ? "Restart SQM?" : "Restart the AP?"; },
            message: function (p) {
                return p.targets[0] === "sqm"
                    ? "Restart the SQM/CAKE service and briefly interrupt traffic shaping?"
                    : "Restart hostapd and interrupt connected AP clients?";
            },
            success: function (p) {
                return p.targets[0] === "sqm" ? "SQM restart request completed." : "AP restart request completed.";
            }
        },
        vpn_toggle: {
            staged: false, refresh: true,
            title: function (p) { return (p.enabled ? "Enable " : "Disable ") + p.provider + "?"; },
            message: "This changes only the selected secure tunnel service and may interrupt tunnel clients.",
            success: function (p) { return p.provider + (p.enabled ? " enabled." : " disabled."); }
        },
        tailscale_auth: {
            staged: false, refresh: true,
            title: "Authenticate Tailscale?",
            message: "This starts Tailscale sign-in. Enter an auth key from the Tailscale admin console; a sign-in link, when one is pending, is shown in status.",
            success: "Tailscale authentication requested."
        },
        reboot: {
            staged: false, refresh: false,
            title: "Reboot TravelPi?",
            message: "Reboot the Raspberry Pi now? The Cockpit session will disconnect.",
            success: "Reboot request completed."
        },
        // CONTEXT.md: no role flip until a verified wired management route and
        // rollback testing exist, so this stays unavailable and describe()
        // refuses it. The copy is kept so the future safe swap has one home.
        wan_flip: {
            available: false, staged: false, refresh: true,
            title: "Swap WAN radio",
            message: function (p) {
                return "Move the WAN role to " + p.wan + ". The other Wi-Fi radio becomes the TravelPi AP. " +
                    "Offered only when the host reports a verified wired management route and rollback testing.";
            },
            success: "Radio roles swapped."
        },
        reset_radios: {
            available: true, staged: false, refresh: true,
            title: "Repair radios",
            message: "Restore the canonical layout: the AP moves to the 5 GHz USB radio and the WAN (hotel) uplink uses the internal radio with the required MAC spoof. Safe to run any time.",
            success: "Radios repaired."
        },
        wake_peer: {
            staged: false, refresh: true,
            title: function (p) { return "Wake " + p.target + "?"; },
            message: function (p) {
                return "Send a Tailscale magic packet to wake " + p.target +
                    "? The device must be tailnet-enabled and support wake-on-LAN.";
            },
            success: function (p) { return "Magic packet sent to " + p.target + "."; }
        },
        set_dns_stack: {
            staged: false, refresh: true,
            title: function (p) {
                return p.service === "adguard" ? "Switch to filtered DNS?" : "Switch to plain recursive DNS?";
            },
            message: function (p) {
                return p.service === "adguard"
                    ? "AdGuard Home filters the LAN DNS again (Unbound stays as fallback). Tailscale name splitting requires AdGuard and will be inactive in recursive mode."
                    : "Unbound answers :53 recursively through the hotel nameservers with no ad filtering; AdGuard Home stops. Tailnet name splitting is inactive in this mode.";
            },
            success: "DNS stack request completed."
        },
        set_ipv6: {
            staged: false, refresh: true,
            title: function (p) { return p.mode === "on" ? "Advertise IPv6 on the LAN?" : "Stop IPv6 on the LAN?"; },
            message: function (p) {
                return p.mode === "on"
                    ? "Start router advertisements; LAN devices get private ULA IPv6 addresses via SLAAC."
                    : "Stop router advertisements; LAN devices keep IPv6 disabled.";
            },
            success: "IPv6 request completed."
        },
        set_sqm_mode: {
            staged: false, refresh: true,
            title: function (p) {
                return p.mode === "auto" ? "Auto-tune traffic shaping?"
                    : (p.mode === "manual" ? "Pin the CAKE rate?" : "Turn traffic shaping off?");
            },
            message: function (p) {
                return p.mode === "auto"
                    ? "CAKE re-probes the uplink and keeps 90% headroom; the tuning timer runs on its schedule."
                    : (p.mode === "manual"
                        ? "CAKE keeps the dashboard-pinned rate; the tuning timer stops. Use Set CAKE rate to choose the pinned value."
                        : "Remove the CAKE qdisc entirely. Bufferbloat protection is off until you re-enable auto or manual mode.");
            },
            success: "Traffic shaping request completed."
        },
        set_cpu_governor: {
            staged: false, refresh: true,
            title: function (p) { return "Set the CPU governor to " + p.governor + "?"; },
            message: function (p) {
                return p.governor === "performance"
                    ? "Pinning CPUs at the 700 MHz cap maximizes throughput and rail draw; use it plugged into a strong supply."
                    : (p.governor === "conservative"
                        ? "The most conservative ramp-up: lowest rail draw, sluggish bursts (tunnel crypto suffers)."
                        : "Balanced on-demand ramping - the rail-safe default for the dual 5V supply setup.");
            },
            success: "CPU governor request completed."
        },
        reclaim_memory: {
            staged: false, refresh: true,
            title: "Clear kernel caches?",
            message: "Sync disks and drop kernel page caches to reclaim RAM. Running services and swap are untouched; swap only frees as processes exit.",
            success: "Cache clear completed."
        }
    };

    function copyText(value, payload) {
        return typeof value === "function" ? value(payload || {}) : value;
    }

    function descriptor(action) {
        var value = descriptors[action];
        return value ? Object.assign({ action: action, available: true }, value) : null;
    }

    function allowed(action) {
        var value = descriptor(action);
        return Boolean(value && value.available);
    }

    // The confirmation dialog's full copy for one payload, or null when the
    // action is not available. Presentation reads this; it types no strings.
    function describe(action, payload) {
        var spec = descriptors[action];
        var prepared;
        if (!spec || spec.available === false) {
            return null;
        }
        prepared = Object.assign({}, payload || {});
        return {
            action: action,
            payload: prepared,
            title: copyText(spec.title, prepared),
            message: copyText(spec.message, prepared),
            success: copyText(spec.success, prepared)
        };
    }

    function prepare(action, payload) {
        if (!allowed(action)) {
            return { ok: false, code: "unavailable" };
        }
        return { ok: true, action: action, payload: Object.assign({}, payload || {}) };
    }

    function createState() {
        return { busy: false, confirmation: null, pending: [] };
    }

    function request(state, action, payload) {
        var spec = descriptor(action);
        if (!spec || spec.available === false) {
            return { ok: false, code: "unavailable", state: state };
        }
        if (state.busy || state.confirmation) {
            return { ok: false, code: "busy", state: state };
        }
        return { ok: true, code: "awaiting_confirmation", state: Object.assign({}, state, {
            confirmation: { action: action, payload: Object.assign({}, payload || {}) }
        }) };
    }

    function cancel(state) {
        return Object.assign({}, state, { confirmation: null });
    }

    function confirm(state) {
        var confirmation = state.confirmation;
        var spec;
        var pending;
        var index;
        if (!confirmation) {
            return { ok: false, code: "no_confirmation", state: state };
        }
        spec = descriptor(confirmation.action);
        if (!spec || spec.available === false) {
            return { ok: false, code: "unavailable", state: cancel(state) };
        }
        if (spec.staged) {
            pending = state.pending.slice();
            index = pending.findIndex(function (item) { return item.action === confirmation.action; });
            var entry = { action: confirmation.action, payload: confirmation.payload };
            if (index >= 0) {
                pending[index] = entry;
            } else {
                pending.push(entry);
            }
            return { ok: true, code: "staged", state: Object.assign({}, state, { confirmation: null, pending: pending }) };
        }
        return { ok: true, code: "execute", action: confirmation.action,
            payload: confirmation.payload, state: Object.assign({}, state, { confirmation: null, busy: true }) };
    }

    function beginApply(state) {
        if (!state.pending.length) {
            return { ok: false, code: "busy_or_empty", state: state };
        }
        return { ok: true, code: "execute", action: state.pending[0].action,
            payload: state.pending[0].payload,
            state: Object.assign({}, state, { busy: true }) };
    }

    function finishApply(state, success) {
        if (!success) {
            return { ok: false, code: "apply_failed", state: Object.assign({}, state, { busy: false }) };
        }
        return { ok: true, code: state.pending.length > 1 ? "continue" : "applied",
            state: Object.assign({}, state, { busy: state.pending.length > 1, pending: state.pending.slice(1) }) };
    }

    function clearPending(state) {
        return { ok: true, state: Object.assign({}, state, { pending: [] }) };
    }

    function removePending(state, action) {
        return {
            ok: true,
            state: Object.assign({}, state, {
                pending: state.pending.filter(function (item) { return item.action !== action; })
            })
        };
    }

    return {
        descriptors: descriptors,
        descriptor: descriptor,
        allowed: allowed,
        describe: describe,
        prepare: prepare,
        createState: createState,
        request: request,
        cancel: cancel,
        confirm: confirm,
        beginApply: beginApply,
        finishApply: finishApply,
        clearPending: clearPending,
        removePending: removePending
    };
}));
