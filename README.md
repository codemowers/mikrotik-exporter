# Background

This is Prometheus exporter for Mikrotik routers and switches.

This is yet another Mikrotik exporter implementation besides well known
[nshttpd/mikrotik-exporter](https://github.com/nshttpd/mikrotik-exporter)
and
[akpw/mktxp](https://github.com/akpw/mktxp)

Unlike others [codemowers/mikrotik-exporter](https://github.com/codemowers/mikrotik-exporter) strives to:

* be purely protocol converter, thus it has no separate configuration files
* work with `dns_sd_configs`
* work with `static_configs`
* work with Prometheus operator `Probe` CRD
* be highly concurrent utilizing async Python and doesn't use threads
* be implemented as single Python file
* optionally scrape MAC and IP addresses to `mikrotik_neighbor_host_info`,
  `mikrotik_bridge_host_info` metrics via `module: full`
* follow [Prometheus naming conventions](https://prometheus.io/docs/practices/naming/)

# Usage

Refer to `config/prometheus.yaml` to see how to use directly.

Refer to [git.k-space.ee/k-space/kube](https://git.k-space.ee/k-space/kube/src/branch/master/monitoring/mikrotik-exporter.yaml) for usage in Kubernetes.

Some example queries:
Wait for targets to be scraped, open up Prometheus to run queries:

Interface thoughput rates:

```
rate(mikrotik_interface_rx_bytes[1m])
rate(mikrotik_interface_tx_bytes[1m])
rate(mikrotik_interface_rx_packets[1m])
rate(mikrotik_interface_tx_packets[1m])
```

Hosts running at low link speeds by MAC address:

```
mikrotik_bridge_host_info * on(instance, interface) group_left() mikrotik_interface_rate / 1000000 < 1000
```

Hosts by MAC and IP address merged from switches and router:

```
mikrotik_neighbor_host_info{identity_name="router"} * on(mac) group_left(interface) mikrotik_bridge_host_info{identity_name!="router",interface=~"ether.*",vid="20"}
```

Hosts by link speed, MAC address and IP address merged from switches and router:

```
min without(identity_name, interface, status, namespace, job, instance, version, vid) (
  mikrotik_neighbor_host_info{identity_name="router"}
  * on(mac) group_left(interface, vid, vendor)
  (mikrotik_bridge_host_info{identity_name!="router",vid="20"}
* on(instance, interface) group_left()
  mikrotik_interface_rate / 1000000
))
```

Hosts in a subnet:

```
mikrotik_neighbor_host_info{address=~"193\\.40\\.103\\..*"}
```

Hosts in a subnet by MAC and IP address:

```
mikrotik_neighbor_host_info{address=~"193\\.40\\.103\\..*", identity_name="router"} * on(mac) group_left() mikrotik_bridge_host_info{identity_name!="router",vid="20",interface=~"sfp.*|ether.*"}
```

Host IPv4 and IPv6 addresses by MAC address:

```
mikrotik_neighbor_host_info{mac="fa:fa:fa:fa:fa:fa"}
```

# Why not SNMP

SNMP for whatever reason is horribly slow on Mikrotik,
see [here](https://forum.mikrotik.com/viewtopic.php?t=132304) for discussion.
It takes 2+ minutes to scrape over SNMP vs few seconds over management API.
Also PoE status codes are not fully documented for SNMP,
see forum post [here](https://forum.mikrotik.com/viewtopic.php?t=162423).
