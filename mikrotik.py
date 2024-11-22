#!/usr/bin/env python
import asyncio
import humanreadable
import os
import aio_api_ros
from base64 import b64decode
from collections import Counter
from manuf import manuf
from sanic import Sanic, HTTPResponse, exceptions

ouilookup = manuf.MacParser()
m = ouilookup.get_manuf_long("52:54:00:fa:fa:fa")
assert m == "QEMU/KVM virtual machine", m
m = ouilookup.get_manuf_long("30:23:03:00:00:01")
assert m == "Belkin International Inc.", m
m = ouilookup.get_manuf_long("f8:ff:c2:fa:fa:fa")
assert m == "Apple, Inc."

app = Sanic("exporter")
pool = {}

PREFIX = os.getenv("PROMETHEUS_PREFIX", "mikrotik_")

# https://help.mikrotik.com/docs/spaces/ROS/pages/8323191/Ethernet
ETHERNET_RECEIVE_ERROR_REASONS = "align-error", "carrier-error", "code-error", \
    "error-events", "fcs-error", "fragment", "ip-header-checksum-error", \
    "jabber", "length-error", "overflow", "runt", "tcp-checksum-error", \
    "too-long", "too-short", "udp-checksum-error", "unknown-op"
ETHERNET_TRANSMIT_ERROR_REASONS = "align-error", "collisions", "deferred", \
    "drop", "excessive-collision", "excessive-deferred", "fcs-error", \
    "fragment", "carrier-sense-error", "late-collsion", "multiple-collision", \
    "overflow", "runt", "too-short", "single-collision", "too-long", "underrun"

async def wrap(i, **extra_labels):
    metrics_seen = set()
    async for name, tp, value, labels in i:
        labels.update(extra_labels)
        if name not in metrics_seen:
            yield "# TYPE %s %s" % (PREFIX + name, tp)
            metrics_seen.add(name)
        yield "%s%s %s" % (
            PREFIX + name,
            ("{%s}" % ",".join(["%s=\"%s\"" % j for j in labels.items()]) if labels else ""),
            value)

def numbers(i):
    return "=numbers=%s" % (",".join([str(j) for j in range(0, i)]))

async def scrape_mikrotik(mk, module_full=False):
    async for obj in mk.query("/system/resource/print"):
        labels = {}
        yield "system_written_sectors_total", "counter", obj["write-sect-total"], labels
        yield "system_free_memory_bytes", "gauge", obj["free-memory"], labels
        try:
            yield "system_bad_blocks_total", "counter", obj["bad-blocks"], labels
        except KeyError:
            pass

        for key in ("version", "cpu", "cpu-count", "board-name", "architecture-name"):
            labels[key.replace("-", "_")] = obj[key]
        yield "system_version_info", "gauge", 1, labels

    async for obj in mk.query("/system/health/print"):
        # Normalize ROS6 vs ROS7 difference
        if "name" in obj:
            key = obj["name"]
            value = obj["value"]
            obj = {}
            obj[key] = value
        for key, value in obj.items():
            if key.startswith("board-temperature"):
                yield "system_health_temperature_celsius", "gauge", \
                    float(value), {"component": "board%s" % key[17:]}
            elif key == "fan-state":
                yield "system_health_fan_state_info", "gauge", 1, \
                    {"state": value}
            elif key.endswith("temperature"):
                yield "system_health_temperature_celsius", "gauge", \
                    float(value), {"component": key[:-12] or "system"}
            elif key.startswith("fan") and key.endswith("-speed"):
                yield "system_health_fan_speed_rpm", "gauge", \
                    float(value), {"component": key[:-6]}
            elif key.startswith("psu") and key.endswith("-state"):
                yield "system_health_power_supply_state", "gauge", \
                    1, {"state": value, "component": key[:-6]}
            elif key.startswith("psu") and key.endswith("-voltage"):
                yield "system_health_power_supply_voltage", "gauge", \
                    float(value), {"component": key[:-8]}
            elif key.startswith("psu") and key.endswith("-current"):
                yield "system_health_power_supply_current", "gauge", \
                    float(value), {"component": key[:-8]}
            elif key == "power-consumption":
                # Can be calculated from voltage*current
                pass
            elif key == "state" or key == "state-after-reboot":
                # Seems disabled on x86
                pass
            elif key == "poe-out-consumption":
                pass
            else:
                raise NotImplementedError("Don't know how to handle system health record %s" % repr(key))

    bonds = set()
    async for obj in mk.query("/interface/bonding/print"):
        assert ".id" in obj, obj
        bonds.add((obj[".id"], obj["name"]))

    for bond_id, bond_name in bonds:
        async for obj in mk.query("/interface/bonding/monitor", "=.id=%s" % bond_id, "=once="):
            labels = {
                "parent_interface": bond_name,
                "lacp_system_id": obj["lacp-system-id"].lower(),
                "lacp_partner_system_id": obj.get("lacp-partner-system-id", "").lower()
            }

            if obj["active-ports"]:
                for port in obj["active-ports"].split(","):
                    labels["interface"] = port
                    yield "bond_port_active", "gauge", 1, labels
            if obj["inactive-ports"]:
                for port in obj["inactive-ports"].split(","):
                    labels["interface"] = port
                    yield "bond_port_active", "gauge", 0, labels

    stats_sent = set()
    async for obj in mk.query("/interface/ethernet/print", "=stats="):
        labels = {"interface": obj["name"]}
        for tp in "control", "pause", "broadcast", "multicast", "unicast":
            key = "rx-%s" % tp
            if key not in obj:
                continue
            yield "interface_received_packets_by_type_total", "counter", \
                obj[key], labels | {"type": tp}
            key = "tx-%s" % tp
            if key not in obj:
                continue
            yield "interface_transmitted_packets_by_type_total", "counter", \
                obj[key], labels | {"type": tp}

        for reason in ETHERNET_RECEIVE_ERROR_REASONS:
            key = "rx-%s" % reason
            if key not in obj:
                continue
            yield "interface_receive_errors_by_reason_total", "counter", \
                obj[key], labels | {"reason": reason}
            stats_sent.add((obj["name"], key))

        for reason in ETHERNET_TRANSMIT_ERROR_REASONS:
            key = "rx-%s" % reason
            if key not in obj:
                continue
            yield "interface_transmit_errors_by_reason_total", "counter", \
                obj[key], labels | {"reason": reason}
            stats_sent.add((obj["name"], key))

        acc = 0
        for le in (64, 127, 255, 511, 1023, "+Inf"):
            if le == "+Inf":
                i, j = "1024", "max"
            elif le == 127:
                i, j = "65", "127"
            else:
                i, j = str((le + 1) >> 1), str(le)
            for mode in "tx-rx", "tx", "rx":
                if le == 64:
                    key = "%s-%s" % (mode, 64)
                else:
                    key = "%s-%s-%s" % (mode, i, j)
                print(key, "=>>", le)
                if key in obj:
                    acc += obj[key]
            yield "interface_packet_size_bytes_bucket", "counter", acc, labels | {"le": le}

    async for obj in mk.query("/interface/print", "=stats="):
        labels = {"interface": obj["name"]}
        yield "interface_info", "gauge", 1, labels | {
           "comment": obj.get("comment", ""),
           "type": obj.get("type", "null")}
           # TODO: Decode state to label
           # TODO: Decode last-link-up-time
        if not obj["running"] or obj["disabled"]:
            continue
        yield "interface_received_bytes_total", "counter", obj["rx-byte"], labels
        yield "interface_transmitted_bytes_total", "counter", obj["tx-byte"], labels
        yield "interface_received_packets_total", "counter", obj["rx-packet"], labels
        yield "interface_transmitted_packets_total", "counter", obj["tx-packet"], labels

        if "rx-drop" in obj:
            if (obj["name"], "rx-drop") not in stats_sent:
                yield "interface_receive_errors_by_reason_total", "counter", \
                    obj["rx-drop"], labels | {"reason": "drop"}
        if "tx-drop" in obj:
            if (obj["name"], "tx-drop") not in stats_sent:
                yield "interface_transmit_errors_by_reason_total", "counter", \
                    obj["tx-drop"], labels | {"reason": "drop"}
        if "rx-queue-drop" in obj:
            yield "interface_receive_errors_by_reason_total", "counter", \
                obj["rx-queue-drop"], labels | {"reason": "queue-drop"}
        if "tx-queue-drop" in obj:
            yield "interface_transmit_errors_by_reason_total", "counter", \
                obj["tx-queue-drop"], labels | {"reason": "queue-drop"}

        try:
            yield "interface_receive_errors_total", "counter", obj["rx-error"], labels
            yield "interface_transmit_errors_total", "counter", obj["tx-error"], labels
        except KeyError:
            pass

        yield "interface_running", "gauge", int(obj["running"]), labels
        yield "interface_actual_mtu_bytes", "gauge", obj["actual-mtu"], labels

    port_count = 0
    res = mk.query("/interface/ethernet/print")
    async for obj in res:
        port_count += 1

    async for obj in mk.query("/interface/ethernet/monitor", "=once=", numbers(port_count)):
        labels = {"interface": obj["name"]}
        try:
            rate = obj["rate"]
        except KeyError:
            pass
        else:
            yield "interface_link_rate_bps", "gauge", \
                humanreadable.BitsPerSecond(rate).bps, labels

        try:
            labels["sfp_vendor_name"] = obj["sfp-vendor-name"]
        except KeyError:
            pass
        try:
            labels["sfp_vendor_part_number"] = obj["sfp-vendor-part-number"]
        except KeyError:
            pass

        try:
            yield "interface_sfp_temperature_celsius", "gauge", obj["sfp-temperature"], labels
            yield "interface_sfp_transmitted_power_dbm", "gauge", obj["sfp-tx-power"], labels
            yield "interface_sfp_received_power_dbm", "gauge", obj["sfp-rx-power"], labels
        except KeyError:
            pass

        labels["status"] = obj["status"]
        try:
            labels["sfp_module_present"] = int(obj["sfp-module-present"])
        except KeyError:
            pass
        yield "interface_status", "gauge", 1, labels

    poe_port_count = 0
    res = mk.query("/interface/ethernet/poe/print", optional=True)
    async for obj in res:
        poe_port_count += 1

    if poe_port_count:
        res = mk.query("/interface/ethernet/poe/monitor", "=once=", numbers(poe_port_count))
        async for obj in res:
            labels = {"interface": obj["name"]}
            try:
                yield "poe_out_voltage", "gauge", float(obj["poe-out-voltage"]), labels
                yield "poe_out_current", "gauge", int(obj["poe-out-current"]) / 1000.0, labels
            except KeyError:
                pass

            labels["status"] = obj["poe-out-status"]
            yield "poe_out_status", "gauge", 1, labels

    if not module_full:
        # Specify `module: full` in Probe CRD to pull in extra metrics below
        return

    async for obj in mk.query("/interface/bridge/host/print"):
        labels = {
            "mac": obj["mac-address"].lower(),
            "interface": obj["interface"],
            "vid": obj.get("vid", ""),
            "vendor": ouilookup.get_manuf_long(obj["mac-address"]) or "",
        }
        yield "bridge_host_info", "gauge", 1, labels

    async for obj in mk.query("/ip/arp/print"):
        if obj.get("status", "") in ("failed", "incomplete", ""):
            continue
        labels = {
            "address": obj["address"],
            "version": "4",
            "mac": obj["mac-address"].lower(),
            "interface": obj["interface"],
            "status": obj["status"],
        }
        yield "neighbor_host_info", "gauge", 1, labels

    async for obj in mk.query("/ipv6/neighbor/print", optional=True):
        if obj["status"] in ("failed", ""):
            continue
        if obj["address"].lower().startswith("ff02:"): # TODO: Make configurable?
            continue
        if obj["address"].lower().startswith("fe80:"):
            continue

        labels = {
            "address": obj["address"].split("/")[0],
            "version": "6",
            "mac": obj["mac-address"].lower(),
            "interface": obj["interface"],
            "status": obj["status"],
        }
        yield "neighbor_host_info", "gauge", 1, labels


class ServiceUnavailableError(exceptions.SanicException):
    status_code = 503


@app.route("/probe", stream=True)
async def view_export(request):
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Basic "):
        raise exceptions.InvalidUsage("Basic authorization only supported")
    try:
        username, password = b64decode(authorization[6:].encode("ascii")).decode("ascii").split(":")
    except ValueError:
        raise exceptions.InvalidUsage("Failed to parse basic auth credentials")

    target = request.args.get("target")
    if not target:
        raise exceptions.InvalidUsage("Invalid or no target specified")
    if ":" in target:
        target, port = target.split(":")
        port = int(port)
    else:
        port = 8728

    mk = aio_api_ros.connection.ApiRosConnection(
        mk_ip=target,
        mk_port=port,
        mk_user=username,
        mk_psw=password,
    )

    try:
        await mk.connect()
        global_labels = {}
        async for obj in mk.query("/system/identity/print"):
            global_labels["identity"] = obj["name"]
        response = await request.respond(content_type="text/plain")
        async for line in wrap(scrape_mikrotik(mk, module_full=request.args.get("module") == "full"), **global_labels):
            await response.send(line + "\n")

    except aio_api_ros.errors.LoginFailed as e:
        # Host unreachable, name does not resolve etc
        return HTTPResponse(str(e), 403)
    except ConnectionResetError as e:
        return HTTPResponse(e.strerror, 503)
    except OSError as e:
        # Host unreachable, name does not resolve etc
        return HTTPResponse(e.strerror, 503)
    except RuntimeError as e:
        # Handle TCPTransport closed exception
        return HTTPResponse(str(e), 503)
    finally:
        mk.close()

app.run(host="0.0.0.0", port=8728, single_process=True)
