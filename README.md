# TravelPi

I had a Raspberry Pi Zero 2 W sitting in a drawer, and I wanted a travel router that was easy to live with: join the hotel Wi-Fi, hand my own network to my devices, keep my DNS and VPN. The Zero 2 W has 512 MB of RAM, so I skipped the usual router web apps and built this as a [Cockpit](https://cockpit-project.org) package: a few static pages (plain HTML, JavaScript and CSS, no framework or bundler) plus one small Python helper. It adds a few tiny watchdog scripts and no web service of its own.

One Wi-Fi radio joins the hotel (or home) network. A second radio, a USB adapter in my case, runs my own access point. I manage the whole thing from the Cockpit page on the Pi.

## What it does

- **Hotel Wi-Fi:** scan, pick a network, connect. Changes are staged, confirmed, then applied, and a failed change puts the old setting back. It never stores hotel passwords or MAC addresses.
- **Captive portals:** it tells you when a portal is blocking the connection. You sign in yourself; it never automates that.
- **Privacy:** clone, randomize or reset the WAN MAC address.
- **Radios:** pick the band for the uplink and for the access point, and change the AP's name, password and channel.
- **DNS and VPN:** AdGuard Home with a fallback resolver, and Tailscale or WireGuard if you use them.
- **Health:** the Zero 2 W browns out on weak power, so it records undervoltage, watches temperature and memory, and restarts a radio that hangs.

## What it does not do

It can't swap which radio is the uplink, and AP clients only get private IPv6 addresses (see below). There are no per-device controls and no VPN kill switch. I've only tested it on my own Zero 2 W with a USB Wi-Fi adapter on Raspberry Pi OS (Debian 13), so expect rough edges elsewhere.

## Quick install

You need a Pi with two Wi-Fi radios running Raspberry Pi OS / Debian 13 with [Cockpit](https://cockpit-project.org), NetworkManager, hostapd, dnsmasq and Unbound installed (AdGuard Home and Tailscale are optional), a user on the Pi with passwordless `sudo`, and SSH access to it. On your computer you need Node 16.20+ and Python 3. The full checklist is in [the reference](docs/REFERENCE.md#prerequisites-on-the-pi).

```sh
git clone https://github.com/sterlenjohnson/travelpi.git
cd travelpi
npm ci
make check          # builds and runs every test, no Pi needed
make deploy PI_HOST=<pi address> PI_USER=<user on the pi> PI_KEY=~/.ssh/<key>
```

Then open `https://<pi address>:9090`, log in, and choose **TravelPi** in the menu.

**Read this before you deploy.** `make deploy` changes the host: it installs systemd units, a sudoers rule, sysctl and modprobe files, and restarts Cockpit. Restarting NetworkManager can drop your session if you are connected over the Pi's own Wi-Fi, so deploy over a cable or add `SKIP_NM_RESTART=1`. The list of everything it touches, and how to undo or skip each part, is in [the reference](docs/REFERENCE.md#what-make-deploy-changes-on-the-host).

## Global IPv6 for AP clients

Devices on the access point get private (ULA) IPv6 addresses, not global ones. Global addresses need the upstream router to delegate a prefix to the Pi. The Network page has a **Check prefix delegation** button that asks the network whether it will, and [the reference](docs/REFERENCE.md#global-ipv6-for-ap-clients) explains how to turn it on in your router. Hotels almost never offer it.

## More

- [Reference](docs/REFERENCE.md): every feature, the helper's allowed actions, defaults you can change, and the threat model.
- [Contributing](CONTRIBUTING.md) and [security reports](SECURITY.md).
- [Design decisions](docs/adr/) for why things work the way they do.

## License

[MIT](LICENSE)
