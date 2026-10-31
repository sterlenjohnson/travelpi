---
name: Bug report
about: Something in TravelPi Cockpit or its helper does not behave as documented
title: ""
labels: bug
---

**Do not include secrets.** Remove Wi-Fi passwords, auth keys, SSIDs you want kept private and MAC addresses you do not want public. For a security problem, do not open an issue: see SECURITY.md.

**What happened**
<!-- What you did, what you expected, what you saw. The exact notice or error text helps most. -->

**Hardware and OS**
- Board (e.g. Pi Zero 2 W) and the Wi-Fi radios used as WAN and AP:
- OS and kernel (`cat /etc/os-release`, `uname -r`):
- Cockpit version:

**Output of the read-only checks** (redact first)
<!-- `sudo /usr/local/libexec/travelpi-cockpit status` , and for IPv6/DHCP issues `sudo /usr/local/libexec/travelpi-cockpit pd` -->

**Deploy options in use**
<!-- Which make deploy variables you passed (SKIP_NM_RESTART, RADIO_SWITCH, ...) -->
