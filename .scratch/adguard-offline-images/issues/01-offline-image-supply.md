---
title: Offline image supply for the AdGuard Quadlet
labels:
  - ready-for-agent
status: closed
---

## Question

How should the AdGuard Home Quadlet start reliably with no reachable container registry?

Evidence (2026-10-26): `/etc/containers/systemd/adguardhome.container` used `AutoUpdate=registry` + registry pull on start; with `registry-1.docker.io` unreachable the service crash-looped (restart counter 19) and the DNS stack was down for hours until the image was pulled from `mirror.gcr.io`. `PullPolicy=always`/`ExecStartPre=podman pull` couples DNS availability to registry reachability on every boot.

Required outcome:

- Quadlet uses `PullPolicy=missing` (start the local image; never require the network at boot).
- Image updates are an explicit, offline-capable operation: `make deploy` ships the image via `podman save`/`podman load` (or an explicit `image-update` make target using an allowlisted mirror list).
- Remove boot-time `ExecStartPre=podman pull` from both the user Quadlet (`systemd/user/adguardhome.container`) and the Pi's system copy.
- Deployment verifies the local image exists after load and reports image version; cockpit's DNS status surfaces image-present vs registry-check state separately.

Constraints: rootful quadlet on the Pi, rootless quadlet in repo; both must change together.

## Comments

- 2026-10-26: Live incident — image absent + Docker Hub timeout = 19 restart loop; `mirror.gcr.io` worked once, so allowlist it for deliberate updates only.
- Live notes: Pi quadlet version rejects the `PullPolicy` key (generator error removed the unit entirely — caught during deploy), so offline behavior is achieved via `AutoUpdate=local` + no `ExecStartPre` pull (quadlet default = pull only if image missing). `make image-update` is the explicit mirror path. AdGuard active + DNS resolving post-deploy.
