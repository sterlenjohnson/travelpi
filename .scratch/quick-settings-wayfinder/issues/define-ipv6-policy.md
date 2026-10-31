---
title: Define IPv6 delegation and firewall policy
labels:
  - wayfinder:research
status: open
parent: ../map.md
---

## Question

What IPv6 behavior can TravelPi safely support when the hotel upstream does or does not delegate IPv6?

Research the NetworkManager, dnsmasq/RA, firewall, and client implications for: no upstream IPv6, global delegated prefix, and link-local/LAN-only IPv6. The answer must define when the UI reports unavailable/available/LAN-only, what is staged, and how rollback prevents clients from receiving unusable or unprotected IPv6 routes.
