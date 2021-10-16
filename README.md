# Background

This is Prometheus exporter for Mikrotik routers and switches.


# Usage

Supply `MIKROTIK_USER`, `MIKROTIK_PASSWORD` using `.env` file.
Spin up the containers:

```bash
docker-compose up --build
```

Wait for targets to be scraped, open up Prometheus to run queries:

* [rate(mikrotik_interface_rx_bytes[1m])](http://localhost:9090/graph?g0.expr=rate(mikrotik_interface_rx_bytes%5B1m%5D)&g0.tab=0)
* [rate(mikrotik_interface_tx_bytes[1m])](http://localhost:9090/graph?g0.expr=rate(mikrotik_interface_tx_bytes%5B1m%5D)&g0.tab=0)
* [rate(mikrotik_interface_rx_packets[1m])](http://localhost:9090/graph?g0.expr=rate(mikrotik_interface_rx_packets%5B1m%5D)&g0.tab=0)
* [rate(mikrotik_interface_tx_packets[1m])](http://localhost:9090/graph?g0.expr=rate(mikrotik_interface_tx_packets%5B1m%5D)&g0.tab=0)


# Why not SNMP

SNMP for whatever reason is horribly slow on Mikrotik,
see [here](https://forum.mikrotik.com/viewtopic.php?t=132304) for discussion.
It takes 2+ minutes to scrape over SNMP vs few seconds over management API.
Also PoE status codes are not fully documented for SNMP,
see forum post [here](https://forum.mikrotik.com/viewtopic.php?t=162423).
