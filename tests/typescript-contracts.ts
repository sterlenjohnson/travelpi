import type {
    MutationRequest,
    ReadinessStatus,
    StatusResponse,
} from "../travelpi-contracts";

const hotelRequest = {
    action: "connect_hotel",
    confirm: true,
    ssid: "HotelWiFi",
    hidden: true,
} satisfies MutationRequest<"connect_hotel">;

const serviceRequest = {
    action: "restart_services",
    confirm: true,
    targets: ["dnsmasq", "hostapd"],
} satisfies MutationRequest<"restart_services">;

const readiness = {
    wired: {
        interface: "eth0",
        present: true,
        link: true,
        address: "192.0.2.1/24",
        gateway: null,
        verified: false,
        role: "management-only",
        readiness: "wired testing unavailable",
    },
    wifi_scan: { interface: "wlan0", available: true, automatic: false },
    transient_networkmanager: { available: false, reason: "fixture" },
    role_switch: { available: false, reason: "fixture" },
    ap_profiles: { tested: ["2.4ghz", "5ghz"], all_bands: false },
} satisfies ReadinessStatus;

const response = {
    ok: true,
    status: {
        wan: { interface: "wlan0", state: "connected" },
        ap: { interface: "wlan1", state: "up" },
        wired: readiness.wired,
        readiness,
        vpn: { selected: "tailscale", states: {}, active: [], providers: {}, summary: "Off" },
        radioInventory: {},
    },
} satisfies StatusResponse;

void hotelRequest;
void serviceRequest;
void response;

// @ts-expect-error The helper requires explicit confirmation for mutations.
const unconfirmed = { action: "reboot" } satisfies MutationRequest<"reboot">;
void unconfirmed;

const wrongPayload = {
    action: "connect_hotel",
    confirm: true,
    ssid: "HotelWiFi",
    // @ts-expect-error The payload belongs to a different mutation.
    rate_kbit: 30000,
} satisfies MutationRequest<"connect_hotel">;
void wrongPayload;
