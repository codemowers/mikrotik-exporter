#!/usr/bin/env python
import asyncio
import humanreadable
import os
import aio_api_ros
from base64 import b64decode
from manuf import manuf
from sanic import Sanic, exceptions

ouilookup = manuf.MacParser()
assert ouilookup.get_manuf_long("52:54:00:fa:fa:fa") == "QEMU/KVM virtual machine"
assert ouilookup.get_manuf_long("30:23:03:00:00:01") == "Belkin International Inc."
assert ouilookup.get_manuf_long("f8:ff:c2:fa:fa:fa") == "Apple, Inc."

app = Sanic("exporter")
pool = {}

PREFIX = os.getenv("PROMETHEUS_PREFIX", "mikrotik_")

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

async def scrape_mikrotik(mk, module_full=False):
    async for obj in mk.query("/interface/print"):
        labels = {"interface": obj["name"]}

        yield "interface_info", "gauge", 1, labels | {
           "comment": obj.get("comment", ""),
           "type": obj.get("type", "null")}
           # TODO: Decode state to label
           # TODO: Decode last-link-up-time
        if not obj["running"] or obj["disabled"]:
            continue
        yield "interface_rx_bytes", "counter", obj["rx-byte"], labels
        yield "interface_tx_bytes", "counter", obj["tx-byte"], labels
        yield "interface_rx_packets", "counter", obj["rx-packet"], labels
        yield "interface_tx_packets", "counter", obj["tx-packet"], labels
        try:
            yield "interface_rx_errors", "counter", obj["rx-error"], labels
            yield "interface_tx_errors", "counter", obj["tx-error"], labels
        except KeyError:
            pass
        try:
            yield "interface_rx_drops", "counter", obj["rx-drop"], labels
            yield "interface_tx_drops", "counter", obj["tx-drop"], labels
        except KeyError:
            pass
        yield "interface_running", "gauge", int(obj["running"]), labels
        yield "interface_actual_mtu", "gauge", obj["actual-mtu"], labels

    port_count = 0
    res = mk.query("/interface/ethernet/print")
    async for obj in res:
        port_count += 1
    ports = ",".join([str(j) for j in range(1, port_count)])

    async for obj in mk.query("/interface/ethernet/monitor", "=once=", "=numbers=%s" % ports):
        labels = {"interface": obj["name"]}

        try:
            rate = obj["rate"]
        except KeyError:
            pass
        else:
            yield "interface_rate", "gauge", \
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
            yield "interface_sfp_temperature", "gauge", obj["sfp-temperature"], labels
            yield "interface_sfp_tx_power", "gauge", obj["sfp-tx-power"], labels
            yield "interface_sfp_rx_power", "gauge", obj["sfp-tx-power"], labels
        except KeyError:
            pass

        labels["status"] = obj["status"]
        try:
            labels["sfp_module_present"] = int(obj["sfp-module-present"])
        except KeyError:
            pass
        yield "interface_status", "gauge", 1, labels

    poe_ports = set()
    res = mk.query("/interface/ethernet/poe/print", optional=True)
    async for obj in res:
        poe_ports.add(int(obj[".id"][1:], 16) - 1)

    if poe_ports:
        res = mk.query("/interface/ethernet/poe/monitor", "=once=", "=numbers=%s" % ",".join([str(j) for j in poe_ports]))
        async for obj in res:
            labels = {"interface": obj["name"]}
            try:
                yield "poe_out_voltage", "gauge", float(obj["poe-out-voltage"]), labels
                yield "poe_out_current", "gauge", int(obj["poe-out-current"]) / 1000.0, labels
            except KeyError:
                pass

            labels["status"] = obj["poe-out-status"]
            yield "poe_out_status", "gauge", 1, labels

    async for obj in mk.query("/system/resource/print"):
        labels = {}
        yield "system_write_sect_total", "counter", obj["write-sect-total"], labels
        yield "system_free_memory", "gauge", obj["free-memory"], labels
        try:
            yield "system_bad_blocks", "counter", obj["bad-blocks"], labels
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

    if not module_full:
        # Specify `module: full` in Probe CRD to pull in extra metrics below
        return

    async for obj in mk.query("/interface/bridge/host/print"):
        labels = {
            "mac": obj["mac-address"].lower(),
            "interface": obj["interface"],
            "vid": obj.get("vid", ""),
            "vendor": ouilookup.get_manuf_long(obj["mac-address"]),
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

    async for obj in mk.query("/ipv6/neighbor/print"):
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


class ServiceUnavailableError(exceptions.ServerError):
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
    response = await request.respond(content_type="text/plain")
    handle = target, port, username, password

    if handle not in pool:
        mk = aio_api_ros.connection.ApiRosConnection(
            mk_ip=target,
            mk_port=port,
            mk_user=username,
            mk_psw=password,
        )
        pool[handle] = mk, asyncio.Lock()
    mk, lock = pool[handle]

    async with lock:
        try:
            await mk.connect()
            await mk.login()
            global_labels = {}
            async for obj in mk.query("/system/identity/print"):
                global_labels["identity_name"] = obj["name"]

            async for line in wrap(scrape_mikrotik(mk, module_full=request.args.get("module") == "full"), **global_labels):
                await response.send(line + "\n")
        except aio_api_ros.errors.LoginFailed as e:
            pool.pop(handle)
            # Host unreachable, name does not resolve etc
            raise exceptions.Forbidden(str(e))
        except OSError as e:
            pool.pop(handle)
            # Host unreachable, name does not resolve etc
            raise ServiceUnavailableError(e.strerror)
        except RuntimeError as e:
            # Handle TCPTransport closed exception
            pool.pop(handle)
            raise exceptions.ServerError(str(e))

app.run(host="0.0.0.0", port=3001, single_process=True)
