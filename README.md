# Background

This is Prometheus exporter for Mikrotik routers and switches.


# Usage

Supply `MIKROTIK_USER`, `MIKROTIK_PASSWORD` and comma separated `TARGETS`
as environment variables via `.env` file.
Optionally configure `PROMETHEUS_BEARER_TOKEN` for securing the
metrics endpoint.


# Why not SNMP

SNMP for whatever reason is horribly slow on Mikrotik,
see [here](https://forum.mikrotik.com/viewtopic.php?t=132304) for discussion.
It takes 2+ minutes to scrape over SNMP vs few seconds over management API.
Also PoE status codes are not fully documented for SNMP,
see forum post [here](https://forum.mikrotik.com/viewtopic.php?t=162423).
