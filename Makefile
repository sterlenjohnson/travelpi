.PHONY: check test harness-check package package-list check-pi-user deploy image-update backup-pull restore harness-mount harness-status skill-install skill-check

# Targets:
#   make test           build + typecheck + every product test. Needs only Node and
#                       Python 3 (contributors run this).
#   make harness-check  mount and validate the agent harness (harness/, AGENTS.md).
#   make check          the full gate: harness-check, then test.
#   make package|deploy build the archive / install on a Pi (deploy changes a real
#                       host; read docs/REFERENCE.md "What make deploy changes" first).

PI_HOST ?= travelpi.local
PI_USER ?= pi
PI_KEY ?= $(HOME)/.ssh/id_ed25519
ARCHIVE ?= dist/travelpi-cockpit.tar.gz
# Opt-in deploy behaviours (all default off; note a default deploy DISABLES the
# SQM auto-tune timer, it does not just leave it unchanged):
#   SQM_AUTOTUNE=1        enable the 4-hourly CAKE auto-tune timer (~30 MB per probe)
#   RADIO_SWITCH=1        run travelpi-radio-driver live during deploy (it can unbind the AP
#                         radio when the kernel newly supports mt7925u); default leaves it
#                         to the boot unit
#   TAILSCALE_SSH=1       tailscale set --ssh --accept-risk=lose-ssh
#   ADVERTISE_ROUTES=...  tailscale set --advertise-routes=<comma-separated CIDRs>;
#                         include your own ULA /64 from /etc/travelpi/ula-prefix
#                         if you want it routed (nothing is advertised otherwise)
#   DISABLE_UNUSED_SERVICES=1  also `systemctl disable --now exim4 containerd` (~30 MB freed)
#   SKIP_NM_RESTART=1     do not restart NetworkManager at the end (default restarts it,
#                         which drops the Pi's Wi-Fi/AP for a moment; use it when
#                         deploying over the Pi's own wireless link)
RADIO_SWITCH ?= 0
SQM_AUTOTUNE ?= 0
DISABLE_UNUSED_SERVICES ?= 0
SKIP_NM_RESTART ?= 0
export PI_USER
# Package allowlist: only what deploy installs. Everything else in the working
# tree (backups/, node_modules, .playwright-mcp, tests, docs, *.local.md) stays out.
PACKAGE_PATHS := manifest.json index.html travelpi.html hotel.html vpn.html network.html health.html \
	travelpi-mutations.js travelpi-typed.js travelpi.js travelpi.css cockpit helper systemd
PACKAGE_LIST ?= dist/package.list
# Paths allowed in a config backup (mirrors the tar list in systemd/travelpi-config-backup).
RESTORE_PATHS := etc/NetworkManager/system-connections etc/NetworkManager/NetworkManager.conf \
	etc/hostapd/hostapd.conf etc/dnsmasq.d/travelpi.conf etc/unbound/unbound.conf.d/travelpi-front.conf \
	etc/radvd.conf etc/travelpi etc/travelpi-home-dns etc/systemd/network/070-travelpi-ap.network \
	etc/systemd/network/070-travelpi-ap.network.d etc/default/travelpi-dns etc/default/travelpi-power-profile \
	etc/sysctl.d/90-travelpi-ipv6.conf etc/sudoers.d/travelpi-adguard etc/default/travelpi-sqm \
	etc/containers/systemd/adguardhome.container etc/systemd/system/travelpi-sqm.service \
	etc/systemd/system/travelpi-sqm-tune.service etc/systemd/system/travelpi-sqm-tune.timer \
	etc/systemd/system/travelpi-radio-watch.service etc/systemd/system/travelpi-mem-watch.service \
	etc/systemd/system/travelpi-power-profile.service etc/systemd/system/travelpi-power-record.service \
	etc/systemd/system/wlan1-static-ip.service usr/local/libexec/travelpi-mem-watch \
	usr/local/sbin/travelpi-sqm var/lib/tailscale etc/travelpi-AdGuardHome.yaml
RESTORE_CASE := $(foreach p,$(RESTORE_PATHS),$(p)|$(p)/*|)__none__
TAILSCALE_SSH ?= 0
ADVERTISE_ROUTES ?=

check: harness-check test

harness-check:
	python3 tools/harness2.py mount
	python3 tools/harness2.py validate

test:
	npm run build:app
	npm run build:runtime
	npm run typecheck
	node --check travelpi.js
	node --check travelpi-typed.js
	python3 harness/scripts/check_classic_script.py travelpi.js travelpi-typed.js
	python3 tests/manifest-pages.py
	python3 tests/deploy-file-list.py
	python3 tests/package-list.py
	python3 tests/unit-hardening.py
	python3 tests/dispatcher-iface.py
	python3 tests/action-contract-alignment.py
	python3 tests/dom-write-coverage.py
	python3 -m py_compile helper/travelpi-cockpit
	python3 tests/harness2.py
	./tests/helper-contract.sh
	python3 tests/helper-action-contract.py
	python3 tests/helper-command-paths.py
	python3 tests/helper-radio-inventory.py
	python3 tests/power-telemetry.py
	python3 tests/radio-capabilities.py
	python3 tests/wan-band.py
	python3 tests/vpn-status.py
	python3 tests/readiness.py
	python3 tests/sqm-persistence.py
	python3 tests/config-backup.py
	python3 tests/ap-address-guard.py
	python3 tests/ula-prefix.py
	python3 tests/radio-driver-switch.py
	python3 tests/pd-probe.py
	python3 tests/privilege-gate.py
	python3 tests/clone-mac.py
	python3 tests/radio-layout.py
	python3 tests/secret-leak.py
	python3 tests/reboot-restart.py
	python3 tests/ipv6-restore.py
	python3 tests/pd-udp.py
	python3 tests/shell-syntax.py
	python3 tests/script-radio-watch.py
	python3 tests/script-mem-watch.py
	python3 tests/script-adguard-dns.py
	python3 tests/script-ap-keeper.py
	node tests/typed-status-view-model.js
	node tests/frontend-runtime.js
	node tests/mutation-coordinator.js

check-pi-user:
	@printf '%s' "$$PI_USER" | grep -Eq '^[a-z_][a-z0-9_-]*$$' || { echo "PI_USER must match ^[a-z_][a-z0-9_-]*$$ (got '$$PI_USER')"; exit 1; }

package-list:
	@mkdir -p $(dir $(PACKAGE_LIST))
	@git ls-files --cached --others --exclude-standard -- $(PACKAGE_PATHS) \
		| grep -Ev '(^|/)(__pycache__|\.DS_Store|node_modules|\.playwright-mcp|\.opencode|\.git|backups)(/|$$)|\.local\.md$$|\.tar\.gz$$' \
		| sort -u | while IFS= read -r f; do if test -f "$$f"; then printf '%s\n' "$$f"; fi; done > $(PACKAGE_LIST)

package: test package-list
	COPYFILE_DISABLE=1 tar -czf $(ARCHIVE) -T $(PACKAGE_LIST)

deploy: check-pi-user package
	ssh -i $(PI_KEY) -o IdentitiesOnly=yes -o ServerAliveInterval=5 -o ServerAliveCountMax=4 $(PI_USER)@$(PI_HOST) \
		'W=$$(mktemp -d) || exit 1; trap "rm -rf $$W" EXIT; trap "exit 1" HUP INT TERM; tar -xzf - -C $$W || { echo "extract failed"; exit 1; }; exec </dev/null; test -f $$W/helper/travelpi-cockpit && test -f $$W/manifest.json || { echo "archive missing helper or manifest"; exit 1; }; sudo -n true || { echo "passwordless sudo required"; exit 1; }; sudo install -d -o root -g root -m 0755 /usr/share/cockpit/travelpi /usr/local/libexec /etc/default /etc/systemd/system/packagekit.service.d && sudo install -o root -g root -m 0644 $$W/manifest.json $$W/index.html $$W/travelpi.html $$W/hotel.html $$W/vpn.html $$W/network.html $$W/health.html $$W/travelpi-mutations.js $$W/travelpi-typed.js $$W/travelpi.js $$W/travelpi.css /usr/share/cockpit/travelpi/ && 		sudo install -o root -g root -m 0755 $$W/helper/travelpi-cockpit /usr/local/libexec/travelpi-cockpit && sudo install -o root -g root -m 0755 $$W/systemd/travelpi-sqm.sh /usr/local/sbin/travelpi-sqm && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-sqm.service /etc/systemd/system/travelpi-sqm.service && sudo install -o root -g root -m 0755 $$W/systemd/travelpi-ap-ip /usr/local/libexec/travelpi-ap-ip && sudo install -o root -g root -m 0755 $$W/systemd/travelpi-ula-init /usr/local/libexec/travelpi-ula-init && sudo install -d -o root -g root -m 0755 /usr/local/share/travelpi && sudo install -o root -g root -m 0644 $$W/systemd/network/travelpi-ap.network.in /usr/local/share/travelpi/travelpi-ap.network.in && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-radvd.conf /usr/local/share/travelpi/travelpi-radvd.conf && sudo /usr/local/libexec/travelpi-ula-init && sudo install -o root -g root -m 0644 $$W/systemd/wlan1-static-ip.service /etc/systemd/system/wlan1-static-ip.service && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-clockset.service /etc/systemd/system/travelpi-clockset.service && if test -e /etc/default/travelpi-sqm; then :; else sudo install -o root -g root -m 0644 $$W/systemd/travelpi-sqm.default /etc/default/travelpi-sqm; fi && sudo install -o root -g root -m 0644 $$W/systemd/packagekit/resource-guard.conf /etc/systemd/system/packagekit.service.d/resource-guard.conf && sudo install -d -o root -g root -m 0755 /etc/cockpit && sudo install -o root -g root -m 0644 $$W/cockpit/packagekit.override.json /etc/cockpit/packagekit.override.json && sudo install -o root -g root -m 0644 $$W/cockpit/systemd.override.json /etc/cockpit/systemd.override.json && install -d -m 0755 "$$HOME/.config/containers/systemd" "$$HOME/.config/systemd/user/default.target.wants" && install -o "$$(id -un)" -g "$$(id -gn)" -m 0644 $$W/systemd/user/adguardhome.container "$$HOME/.config/containers/systemd/adguardhome.container" && ln -sfn "$$HOME/.config/containers/systemd/adguardhome.container" "$$HOME/.config/systemd/user/default.target.wants/adguardhome.container" && systemctl --user daemon-reload && sudo systemctl daemon-reload || { echo "core install failed; aborting before restarts"; exit 1; }; sudo systemctl reenable wlan1-static-ip.service >/dev/null 2>&1 || echo "WARN: reenable failed: wlan1-static-ip.service"; sudo systemctl restart wlan1-static-ip.service >/dev/null 2>&1; sudo install -o root -g root -m 0755 $$W/systemd/travelpi-radio-watch /usr/local/libexec/travelpi-radio-watch && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-radio-watch.service /etc/systemd/system/travelpi-radio-watch.service && sudo systemctl enable travelpi-radio-watch.service >/dev/null 2>&1 || echo "WARN: enable failed: travelpi-radio-watch.service"; sudo systemctl restart travelpi-radio-watch.service >/dev/null 2>&1 || echo "WARN: restart failed: travelpi-radio-watch.service"; sudo install -d -o root -g root -m 0755 /etc/modprobe.d && sudo install -o root -g root -m 0644 $$W/systemd/modprobe/travelpi-mt7925.conf /etc/modprobe.d/travelpi-mt7925.conf && sudo install -o root -g root -m 0755 $$W/systemd/travelpi-radio-driver /usr/local/libexec/travelpi-radio-driver; if test "$(RADIO_SWITCH)" = 1; then sudo /usr/local/libexec/travelpi-radio-driver >/dev/null 2>&1 || echo "WARN: radio driver switch reported a problem"; else echo "NOTE: live radio driver switch skipped; the boot unit applies it (pass RADIO_SWITCH=1 to run it now)"; fi; sudo install -o root -g root -m 0644 $$W/systemd/travelpi-radio-driver.service /etc/systemd/system/travelpi-radio-driver.service && sudo systemctl daemon-reload && { sudo systemctl enable travelpi-radio-driver.service >/dev/null 2>&1 || echo "WARN: enable failed: travelpi-radio-driver.service"; }; sudo install -o root -g root -m 0755 $$W/systemd/travelpi-sqm-autotune /usr/local/sbin/travelpi-sqm-autotune && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-sqm-tune.service /etc/systemd/system/travelpi-sqm-tune.service && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-sqm-tune.timer /etc/systemd/system/travelpi-sqm-tune.timer && if test "$(SQM_AUTOTUNE)" = 1; then sudo systemctl enable travelpi-sqm-tune.timer >/dev/null 2>&1 || echo "WARN: enable failed: travelpi-sqm-tune.timer"; sudo systemctl restart travelpi-sqm-tune.timer >/dev/null 2>&1 || echo "WARN: restart failed: travelpi-sqm-tune.timer"; else sudo systemctl disable --now travelpi-sqm-tune.timer >/dev/null 2>&1 || true; echo "NOTE: SQM auto-tune timer left off; pass SQM_AUTOTUNE=1 to enable it"; fi; if test -e /etc/default/travelpi-sqm && ! grep -q '^TRAVELPI_SQM_AUTOTUNE=' /etc/default/travelpi-sqm; then echo TRAVELPI_SQM_AUTOTUNE=yes | sudo tee -a /etc/default/travelpi-sqm >/dev/null; fi; sudo install -o root -g root -m 0755 $$W/systemd/travelpi-power-record.sh /usr/local/libexec/travelpi-power-record && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-power-record.service /etc/systemd/system/travelpi-power-record.service && if ! sudo systemctl enable --now travelpi-power-record.service >/dev/null 2>&1; then echo "WARN: enable failed: travelpi-power-record.service"; fi && sudo install -o root -g root -m 0755 $$W/systemd/travelpi-mem-watch /usr/local/libexec/travelpi-mem-watch && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-mem-watch.service /etc/systemd/system/travelpi-mem-watch.service && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-power-profile.service /etc/systemd/system/travelpi-power-profile.service && if test -e /etc/default/travelpi-power-profile; then :; else echo "GOVERNOR=ondemand" | sudo tee /etc/default/travelpi-power-profile >/dev/null; fi && sudo systemctl daemon-reload && if ! sudo systemctl reenable travelpi-mem-watch.service travelpi-power-profile.service >/dev/null 2>&1; then echo "WARN: reenable failed: travelpi-mem-watch travelpi-power-profile"; else sudo systemctl restart travelpi-power-profile.service && sudo systemctl restart travelpi-mem-watch.service; fi; for s in hostapd dnsmasq unbound NetworkManager tailscaled adguardhome; do sudo install -d -o root -g root -m 0755 /etc/systemd/system/$$s.service.d && if test "$$s" = adguardhome; then v=900; else v=-900; fi && printf "[Service]\nOOMScoreAdjust=%s\n" "$$v" | sudo tee /etc/systemd/system/$$s.service.d/travelpi-oom.conf >/dev/null; done && sudo systemctl daemon-reload; if test "$(DISABLE_UNUSED_SERVICES)" = 1; then sudo systemctl disable --now exim4.service containerd.service >/dev/null 2>&1; fi; sudo systemctl enable ntpsec.service >/dev/null 2>&1 || echo "WARN: enable failed: ntpsec.service"; sudo systemctl restart ntpsec.service >/dev/null 2>&1 || echo "WARN: restart failed: ntpsec.service"; for u in travelpi-sqm travelpi-clockset; do sudo systemctl enable $$u.service >/dev/null 2>&1 || echo "WARN: enable failed: $$u.service"; sudo systemctl restart $$u.service >/dev/null 2>&1 || echo "WARN: restart failed: $$u.service"; done && sudo install -o root -g root -m 0755 $$W/systemd/travelpi-power-gate.sh /usr/local/libexec/travelpi-power-gate && sudo install -d -o root -g root -m 0755 /etc/containers/systemd && sudo podman volume create --opt type=tmpfs --opt device=tmpfs --opt o=size=32M travelpi-adguard-stats >/dev/null 2>&1 || true; podman volume create --opt type=tmpfs --opt device=tmpfs --opt o=size=32M travelpi-adguard-stats >/dev/null 2>&1 || true; sudo install -o root -g root -m 0644 $$W/systemd/system/adguardhome.container /etc/containers/systemd/adguardhome.container; echo "$(PI_USER) ALL=(root) NOPASSWD: /bin/cat /opt/adguardhome/conf/AdGuardHome.yaml, /usr/bin/cat /opt/adguardhome/conf/AdGuardHome.yaml" > $$W/sudoers.pre && sudo install -o root -g root -m 0440 $$W/sudoers.pre $$W/sudoers.new && if sudo visudo -cf $$W/sudoers.new >/dev/null; then sudo install -o root -g root -m 0440 $$W/sudoers.new /etc/sudoers.d/travelpi-adguard; else echo "WARN: sudoers drop-in failed visudo validation; not installed"; fi; sudo install -d -o root -g root -m 0755 /etc/NetworkManager/dispatcher.d && sudo install -o root -g root -m 0755 $$W/systemd/travelpi-adguard-hotel-dns /etc/NetworkManager/dispatcher.d/95-travelpi-adguard-hotel-dns; NS=$$(grep ^nameserver /etc/resolv.conf | cut -d" " -f2 | head -3 | xargs); if test -n "$$NS"; then sudo env DHCP4_NAMESERVERS="$$NS" sh /etc/NetworkManager/dispatcher.d/95-travelpi-adguard-hotel-dns wlan0 dhcp4-change >/dev/null 2>&1; fi; sudo /usr/local/libexec/travelpi-ula-init render /usr/local/share/travelpi/travelpi-radvd.conf /etc/radvd.conf && sudo install -d -o root -g root -m 0755 /etc/systemd/network && sudo /usr/local/libexec/travelpi-ula-init render /usr/local/share/travelpi/travelpi-ap.network.in /etc/systemd/network/070-travelpi-ap.network && sudo systemctl disable --now radvd.service >/dev/null 2>&1 || true; sudo systemctl enable --now systemd-networkd.socket systemd-networkd.service >/dev/null 2>&1 || echo "WARN: enable failed: systemd-networkd"; sudo networkctl reload >/dev/null 2>&1 || true; sudo networkctl reconfigure wlan1 >/dev/null 2>&1 || true; sudo install -d -o root -g root -m 0755 /etc/sysctl.d && sudo install -o root -g root -m 0644 $$W/systemd/ipv6/travelpi-ipv6.conf /etc/sysctl.d/90-travelpi-ipv6.conf && sudo sysctl -q -p /etc/sysctl.d/90-travelpi-ipv6.conf; ts=""; if test -n "$(ADVERTISE_ROUTES)"; then ts="$$ts --advertise-routes=$(ADVERTISE_ROUTES)"; fi; if test "$(TAILSCALE_SSH)" = 1; then ts="$$ts --ssh --accept-risk=lose-ssh"; fi; if test -n "$$ts"; then sudo tailscale set $$ts >/dev/null 2>&1 || echo "WARN: tailscale set failed"; fi; sudo install -o root -g root -m 0755 $$W/systemd/travelpi-config-backup /usr/local/libexec/travelpi-config-backup && sudo install -o root -g root -m 0644 $$W/systemd/travelpi-config-backup.service $$W/systemd/travelpi-config-backup.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl reenable travelpi-config-backup.timer >/dev/null 2>&1 || echo "WARN: reenable failed: travelpi-config-backup.timer"; if ! sudo systemctl start travelpi-config-backup.service; then echo "WARN: start failed: travelpi-config-backup.service"; fi && for u in unbound tailscaled hostapd dnsmasq containerd; do sudo install -d -o root -g root -m 0755 /etc/systemd/system/$$u.service.d && sudo install -o root -g root -m 0644 $$W/systemd/units/$$u.service.d/resource-guard.conf /etc/systemd/system/$$u.service.d/resource-guard.conf; done && for s in machine.slice user.slice; do sudo install -d -o root -g root -m 0755 /etc/systemd/system/$$s.d && sudo install -o root -g root -m 0644 $$W/systemd/units/$$s.d/travelpi-guard.conf /etc/systemd/system/$$s.d/travelpi-guard.conf; done && if test -e /etc/containers/systemd/adguardhome.container; then systemctl --user mask adguardhome.service >/dev/null 2>&1; rm -f "$$HOME/.config/systemd/user/default.target.wants/adguardhome.container"; systemctl --user daemon-reload; fi && sudo install -d -o root -g root -m 0755 /etc/systemd/journald.conf.d && sudo install -o root -g root -m 0644 $$W/systemd/journald/travelpi-volatile.conf /etc/systemd/journald.conf.d/10-travelpi-volatile.conf && sudo install -d -o root -g root -m 0755 /etc/modules-load.d && sudo install -o root -g root -m 0644 $$W/systemd/modules-load/travelpi-ina219.conf /etc/modules-load.d/travelpi-ina219.conf && sudo systemctl daemon-reload && sudo systemctl restart systemd-journald && sudo systemctl restart adguardhome.service && sudo systemctl mask --now packagekit.service >/dev/null; sudo install -o root -g root -m 0600 $$W/systemd/nm/travelpi-wired-wan.nmconnection /etc/NetworkManager/system-connections/travelpi-wired-wan.nmconnection && if test "$(SKIP_NM_RESTART)" = 1; then sudo nmcli connection reload >/dev/null 2>&1; echo "NOTE: NetworkManager restart skipped (SKIP_NM_RESTART=1)"; else sudo systemctl restart NetworkManager; fi; sudo systemctl restart cockpit.service >/dev/null 2>&1' < $(ARCHIVE)

harness-mount:
	python3 tools/harness2.py mount

# Pull the newest config backup from the Pi to this machine (keep copies
# off-device; the Pi's SD card is the failure domain). The archive is root-only
# on the Pi, so the read goes through sudo: copying hotel credentials and the
# tailnet node key off-device is a deliberate act, and it lands 0600 locally.
# The read runs over a PTY (-t) so sudo can prompt for a password, and the
# archive travels base64-encoded: a PTY rewrites 0x0A as 0x0D 0x0A, which would
# corrupt a raw gzip stream.
backup-pull:
	@mkdir -p backups
	@LATEST=$$(ssh -i $(PI_KEY) -o IdentitiesOnly=yes $(PI_USER)@$${PI_HOST:-$(PI_HOST)} 'ls -t /var/lib/travelpi/backups/config-*.tar.gz 2>/dev/null | head -1'); \
	test -n "$$LATEST" || { echo "no backup found on Pi (timer runs 10min after boot)"; exit 1; }; \
	ssh -t -i $(PI_KEY) -o IdentitiesOnly=yes $(PI_USER)@$${PI_HOST:-$(PI_HOST)} "sudo base64 '$$LATEST'" \
		| tr -d '\r' | base64 -D > "backups/$$(basename $$LATEST)" && \
	chmod 600 "backups/$$(basename $$LATEST)" && \
	tar -tzf "backups/$$(basename $$LATEST)" >/dev/null && \
	echo "pulled $$(basename $$LATEST) -> backups/ (0600, $$(tar -tzf "backups/$$(basename $$LATEST)" | wc -l | tr -d ' ') entries verified)"

# Restore a config backup onto a Pi (after re-image + make deploy):
#   make restore PI_HOST=... RESTORE_ARCHIVE=backups/config-<stamp>.tar.gz [CONFIRM=1]
# Without CONFIRM=1 it only prints the archive listing. The archive is streamed
# over ssh stdin into a private mktemp dir (never /tmp/<fixed name>) and is
# rejected whole if any member is outside RESTORE_PATHS, contains "..", or is a
# link/device. The staged AdGuard config travels as /etc/travelpi-AdGuardHome.yaml
# (as the backup script names it) and is copied to /opt/adguardhome/conf/.
restore: check-pi-user
	test -f "$(RESTORE_ARCHIVE)" || { echo "set RESTORE_ARCHIVE=backups/config-<stamp>.tar.gz"; exit 1; }
	@echo "Archive contents:"; tar -tzf "$(RESTORE_ARCHIVE)"
	@test "$(CONFIRM)" = 1 || { echo "Nothing restored. Re-run with CONFIRM=1 to extract the above onto $(PI_USER)@$${PI_HOST:-$(PI_HOST)} (overwrites live config, restarts network services)."; exit 1; }
	ssh -i $(PI_KEY) -o IdentitiesOnly=yes $(PI_USER)@$${PI_HOST:-$(PI_HOST)} \
		'W=$$(mktemp -d) || exit 1; trap "rm -rf $$W" EXIT; trap "exit 1" HUP INT TERM; cat > $$W/r.tgz && tar -tzf $$W/r.tgz > $$W/names && tar -tvzf $$W/r.tgz | cut -c1 > $$W/types && if grep -qv "^[-d]" $$W/types; then echo "refusing: archive contains links or special files"; exit 1; fi && while IFS= read -r n; do case "$$n" in *..*) echo "refusing: $$n"; exit 1;; $(RESTORE_CASE)) ;; *) echo "refusing: unexpected member $$n"; exit 1;; esac; done < $$W/names && sudo tar -xzf $$W/r.tgz -C / && { if test -e /etc/sudoers.d/travelpi-adguard && ! sudo visudo -cf /etc/sudoers.d/travelpi-adguard >/dev/null 2>&1; then echo "WARN: restored sudoers drop-in invalid; removed"; sudo rm -f /etc/sudoers.d/travelpi-adguard; fi; }; sudo sh -c 'chmod 600 /etc/NetworkManager/system-connections/*.nmconnection' 2>/dev/null; sudo cp /etc/travelpi-AdGuardHome.yaml /opt/adguardhome/conf/AdGuardHome.yaml 2>/dev/null && sudo chmod 600 /opt/adguardhome/conf/AdGuardHome.yaml; sudo systemctl daemon-reload; for u in NetworkManager adguardhome systemd-networkd tailscaled ntpsec travelpi-clockset travelpi-mem-watch travelpi-radio-watch; do sudo systemctl enable $$u.service 2>/dev/null; done; sudo systemctl restart NetworkManager adguardhome systemd-networkd tailscaled ntpsec travelpi-mem-watch travelpi-radio-watch 2>/dev/null; echo restored' < "$(RESTORE_ARCHIVE)"

harness-status:
	python3 tools/harness2.py status

skill-install:
	./tools/install-global-skill.sh

skill-check:
	./tools/install-global-skill.sh --check

# Deliberate AdGuard Home image update on the Pi from the allowlisted mirror.
# Boot startup never pulls; updates are this explicit action.
image-update:
	ssh -i $(PI_KEY) -o IdentitiesOnly=yes $(PI_USER)@$(PI_HOST) 'sudo podman pull mirror.gcr.io/adguard/adguardhome:latest && sudo podman tag mirror.gcr.io/adguard/adguardhome:latest docker.io/adguard/adguardhome:latest && sudo systemctl restart adguardhome.service && sleep 8 && systemctl is-active adguardhome.service'
