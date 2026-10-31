/** Canonical browser/helper contracts. Runtime code remains plain JavaScript. */

export const mutationActions = [
    "connect_hotel",
    "apply_mac_clone",
    "set_ap_radio",
    "set_wan_band",
    "set_ap_identity",
    "set_cake_rate",
    "restart_services",
    "vpn_toggle",
    "tailscale_auth",
    "reboot",
    "wan_flip",
    "reset_radios",
    "wake_peer",
    "set_dns_stack",
    "set_ipv6",
    "set_sqm_mode",
    "set_cpu_governor",
    "reclaim_memory",
] as const;

export type RadioBand = "2.4ghz" | "5ghz" | "6ghz";

export type MutationAction = (typeof mutationActions)[number];
export type AvailableMutationAction = Exclude<MutationAction, "wan_flip">;

export interface MutationPayloadMap {
    connect_hotel: { ssid: string; password?: string; hidden?: boolean };
    apply_mac_clone: { mac?: string; mode?: "random" | "default" };
    set_ap_radio: { band: RadioBand; channel?: number };
    set_wan_band: { band: "auto" | RadioBand };
    set_ap_identity: { ssid?: string; passphrase?: string };
    set_cake_rate: { rate_kbit: number };
    restart_services: { targets: string[] };
    vpn_toggle: { provider: "tailscale" | "wireguard"; enabled: boolean };
    tailscale_auth: { authkey?: string };
    reboot: Record<string, never>;
    wan_flip: Record<string, never>;
    reset_radios: Record<string, never>;
    wake_peer: { target: string };
    set_dns_stack: { service: "adguard" | "unbound"; upstream?: string };
    set_ipv6: { mode: "on" | "off" };
    set_sqm_mode: { mode: "auto" | "manual" | "off" };
    set_cpu_governor: { governor: "conservative" | "ondemand" | "performance" };
    reclaim_memory: Record<string, never>;
}

export type MutationPayload<A extends MutationAction = MutationAction> =
    A extends MutationAction ? MutationPayloadMap[A] : never;

export type MutationRequest<A extends MutationAction = MutationAction> = {
    [K in A]: { action: K; confirm: true } & MutationPayloadMap[K]
}[A];

export interface WanStatus {
    interface: "wlan0" | string;
    state: string;
    ssid?: string;
    ip?: string;
    gateway?: string;
    signal_dbm?: number;
    freq?: number;
    tx_bitrate?: string;
    rx_bitrate?: string;
    band?: RadioBand | null;
    band_setting?: "auto" | "2.4ghz" | "5ghz" | null;
}

export interface ApStatus {
    interface: "wlan1" | string;
    state: string;
    ssid?: string;
    channel?: number;
    freq?: number;
    width?: string;
    band?: RadioBand | null;
    txpower_dbm?: string;
    ip?: string;
    wifi6?: boolean;
    carrier?: boolean | null;
    stations?: number | null;
}

export interface WiredStatus {
    interface: "eth0" | string;
    present: boolean;
    link: boolean;
    address: string | null;
    gateway: string | null;
    verified: boolean;
    role: "management-only" | "wan" | string;
    readiness: string;
}

export interface ReadinessStatus {
    wired: WiredStatus;
    wifi_scan: { interface: "wlan0" | string; available: boolean; automatic: boolean };
    transient_networkmanager: { available: boolean; reason: string };
    role_switch: { available: boolean; reason: string };
    ap_profiles: { tested: string[]; all_bands: boolean };
}

export interface VpnProviderStatus {
    provider: "tailscale" | "wireguard" | "openvpn" | string;
    state: "active" | "inactive" | string;
    available: boolean;
    backend_state?: string;
    peer_count?: number;
    addresses?: string[];
    routes?: string[];
    endpoints?: string[];
}

export interface VpnStatus {
    selected: string;
    states: Record<string, string>;
    active: string[];
    providers: Record<string, VpnProviderStatus>;
    summary: string;
}

export interface RadioInventoryRecord {
    interface: string;
    role: "wan" | "ap" | "management" | string;
    present: boolean;
    label: string;
    model: string;
    transport: string;
    driver: string;
    bands: RadioBand[] | string[];
    capabilities: string[];
    supported_channels?: Record<string, number[]>;
}

export interface PowerStatus {
    state?: "ok" | "warning" | "unknown";
    temperature_c?: number;
    throttled?: string;
    detail?: string;
    signal?: "undervolt-now" | "undervolt-history" | "throttle-now" | "throttle-history"
        | "temperature-now" | "temperature-history" | "clean" | "unavailable";
    under_volt_now?: boolean;
    under_volt_history?: boolean;
    throttle_now?: boolean;
    throttle_history?: boolean;
    temp_throttle_now?: boolean;
    temp_throttle_history?: boolean;
    core_volts?: number | null;
    current_ma?: number | null;
    power_w?: number | null;
    current_sensor?: string | null;
    usb_otg_present?: boolean;
    raw_throttled?: string | null;
    unexpected_shutdown?: boolean | null;
    usb_devices?: number | null;
    usb_demand_ma?: number | null;
    power_loss_count?: number | null;
    clock_synced?: boolean | null;
    storage_risk?: "ok" | "elevated" | "high";
}

export interface HealthStatus {
    power?: PowerStatus;
    firmware_overrides?: string[] | null;
    throttle_events?: number | null;
    radio_reset_events?: number | null;
    radio_link_events?: number | null;
    radio_recovery_events?: number | null;
    last_radio_recovery?: number | null;
    radio_watchdog?: "armed" | "stale" | "absent" | string | null;
    portal?: { state?: "online" | "portal" | "blocked" | "unknown" | string; portal_url?: string | null; age_s?: number };
    subnet_overlaps?: string[] | null;
    [key: string]: unknown;
}

export type PdState = "offered" | "not_offered" | "unavailable";

/** Result of the read-only `pd` helper command (DHCPv6 prefix-delegation probe). */
export interface PdProbe {
    ok: true;
    action: "pd_probe";
    pd: {
        state: PdState;
        prefix: string | null;
        prefix_len: number | null;
        valid_s: number | null;
        server: string | null;
        detail: string;
    };
}

export interface StatusViewModel {
    health?: HealthStatus;
    wan: WanStatus;
    ap: ApStatus;
    wired: WiredStatus;
    readiness: ReadinessStatus;
    vpn: VpnStatus;
    radioInventory: Record<string, RadioInventoryRecord>;
    currentWanMac?: string | null;
    wanMacClone?: { active: boolean; address?: string | null };
    [section: string]: unknown;
}

export interface StatusResponse {
    ok: true;
    status: StatusViewModel;
}

export function isMutationAction(value: string): value is MutationAction {
    return (mutationActions as readonly string[]).includes(value);
}
