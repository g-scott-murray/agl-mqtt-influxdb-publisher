#!/usr/bin/env python3
# Copyright (c) 2025 Scott Murray <scott.murray@konsulko.com>
#
# SPDX-License-Identifier: MIT

#
# Simple InfluxDB publisher for AGL VSS proxy MQTT messages
#

import os
import sys
import argparse

import paho.mqtt.client as mqtt

from agl import vss_notification_pb2

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.domain.write_precision import WritePrecision

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

verbosity = 0

def process_notification(data, runtime_config):
    notification = vss_notification_pb2.SignalUpdateNotification()
    notification.ParseFromString(data)
    for entry in notification.signals:
        if verbosity > 1:
            print(f"Received update: {entry}")
        if not (entry.HasField("timestamp") and entry.HasField("path")):
            continue
        timestamp_ms = entry.timestamp.seconds * 1000 + entry.timestamp.nanos // 1000000;
        value = None
        if entry.HasField("float"):
            value = float(entry.float)
        elif entry.HasField("double"):
            value = float(entry.double)
        elif entry.HasField("int32"):
            value = entry.int32
        elif entry.HasField("int64"):
            value = entry.int64
        elif entry.HasField("uint32"):
            value = entry.uint32
        elif entry.HasField("uint64"):
            value = entry.uint64
        elif entry.HasField("string"):
            value = entry.string
        elif entry.HasField("bool"):
            value = entry.bool
        else:
            print("Unsupported value type, skipping")
            continue
        if runtime_config is not None:
            if verbosity > 0:
                print(f"Writing: path {entry.path} = {value} @ {timestamp_ms} ms")
            p = Point(entry.path).tag("client", notification.clientId).field("value", value).time(timestamp_ms, write_precision=WritePrecision.MS)
            runtime_config["influxdb_api"].write(bucket=runtime_config["influxdb_bucket"], record=p)

def on_subscribe(client, userdata, mid, reason_code_list, properties):
    # Since we subscribed only for a single channel, reason_code_list contains
    # a single entry
    if reason_code_list[0].is_failure:
        print(f"Broker rejected subscription: {reason_code_list[0]}")
    elif verbosity > 0:
        print(f"Broker granted the following QoS: {reason_code_list[0].value}")

def on_unsubscribe(client, userdata, mid, reason_code_list, properties):
    # Be careful, the reason_code_list is only present in MQTTv5.
    # In MQTTv3 it will always be empty
    if len(reason_code_list) == 0 or not reason_code_list[0].is_failure:
        print("unsubscribe succeeded (if SUBACK is received in MQTTv3 it success)")
    else:
        print(f"Broker replied with failure: {reason_code_list[0]}")
    client.disconnect()

def on_message(client, userdata, message):
    if verbosity > 1:
        print(f"Received the following message: {message.payload}")
    process_notification(message.payload, userdata)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"Failed to connect: {reason_code}. loop_forever() will retry connection")
    else:
        # we should always subscribe from on_connect callback to be sure
        # our subscribed is persisted across reconnections.
        if isinstance(userdata, dict) and "mqtt_topic" in userdata:
            client.subscribe(userdata["mqtt_topic"])

def read_config(name):
    if name is None:
        return None

    config = None
    try:
        with open(name, "rb") as f:
            config = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        print(f"Misformatted configuration file {name}")
        config = None
    except:
        print(f"Failed to read configuration file {name}")
        config = None

    return config
    
def check_config(config):
    # Optional publisher section can contain verbosity setting
    if "publisher" in config and isinstance(config["publisher"], dict):
        if not "verbose" in config["publisher"]:
            config["publisher"]["verbose"] = 0
        elif config["publisher"]["verbose"] == "true" or config["publisher"]["verbose"] == "True":
            config["publisher"]["verbose"] = 1
    else:
        config["publisher"] = {}
        config["publisher"]["verbose"] = 0

    # mqtt section required for at least topic
    if "mqtt" in config and isinstance(config["mqtt"], dict):
        if not ("topic" in config["mqtt"] and isinstance(config["mqtt"]["topic"], str)):
            print("ERROR: MQTT configuration missing \"topic\"")
            return False

        # Default to localhost:1883 if not specified
        # Special handling is required since port 8883 is typically the default
        # if using TLS.
        mqtt_default_port = False
        if not "host" in config["mqtt"]:
            config["mqtt"]["host"] = "localhost"
        if not "port" in config["mqtt"]:
            config["mqtt"]["port"] = 1883
            mqtt_default_port = True

        if "username" in config["mqtt"]:
            if not isinstance(config["mqtt"]["username"], str):
                print("ERROR: invalid \"username\" value in MQTT configuration")
                return False
        else:
            config["mqtt"]["username"] = None

        if "password" in config["mqtt"]:
            if not isinstance(config["mqtt"]["password"], str):
                print("ERROR: invalid \"password\" value in MQTT configuration")
                return False
        else:
            config["mqtt"]["password"] = None

        if "client-id" in config["mqtt"]:
            if not isinstance(config["mqtt"]["client-id"], str):
                print("ERROR: invalid \"client-id\" value in MQTT configuration")
                return False
        else:
            config["mqtt"]["client-id"] = None

        if "v5" in config["mqtt"]:
            if not isinstance(config["mqtt"]["v5"], bool):
                print("ERROR: invalid \"v5\" value in MQTT configuration")
                return False
        else:
            config["mqtt"]["v5"] = True

        if "use-tls" in config["mqtt"]:
            if not isinstance(config["mqtt"]["use-tls"], bool):
                print("ERROR: invalid \"use-tls\" value in MQTT configuration")
                return False
            if config["mqtt"]["use-tls"]:
                if "ca-certificate" in config["mqtt"]:
                    if not isinstance(config["mqtt"]["ca-certificate"], str):
                        print("ERROR: Invalid \"ca-certificate\" value in MQTT configuration")
                        return False
                else:
                    # Default is to use host CA certs
                    config["mqtt"]["ca-certificate"] = None

                if "verify-server-hostname" in config["mqtt"]:
                    if not isinstance(config["mqtt"]["verify-server-hostname"], bool):
                        print("ERROR: Invalid \"verify-server-hostname\" value in MQTT configuration")
                        return False
                else:
                    # Default is to verify the server hostname
                    config["mqtt"]["verify-server-hostname"] = True

                # Fix up default port if necessary
                if mqtt_default_port:
                    config["mqtt"]["port"] = 8883
        else:
            # Default is no TLS
            config["mqtt"]["use-tls"] = False
    else:
        print("ERROR: Configuration missing \"mqtt\" section")
        return False

    # influxdb section required for org, bucket, and API token
    if "influxdb" in config and isinstance(config["influxdb"], dict):
        if not ("org" in config["influxdb"] and isinstance(config["influxdb"]["org"], str)):
            print("ERROR: InfluxDB configuration missing \"org\"")
            return False
        if not ("bucket" in config["influxdb"] and isinstance(config["influxdb"]["bucket"], str)):
            print("ERROR: InfluxDB configuration missing \"bucket\"")
            return False
        if not ("token" in config["influxdb"] and isinstance(config["influxdb"]["token"], str)):
            print("ERROR: InfluxDB configuration missing \"token\"")
            return False

        # Default to localhost:8086 if not specified
        if not "host" in config["influxdb"]:
            config["influxdb"]["host"] = "localhost"
        if not "port" in config["influxdb"]:
            config["influxdb"]["port"] = 8086

        if "use-tls" in config["influxdb"]:
            if not isinstance(config["influxdb"]["use-tls"], bool):
                print("ERROR: invalid \"use-tls\" value in InfluxDB configuration")
                return False
            if config["influxdb"]["use-tls"]:
                if "ca-certificate" in config["influxdb"]:
                    if not isinstance(config["influxdb"]["ca-certificate"], str):
                        print("ERROR: Invalid \"ca-certificate\" value in InfluxDB configuration")
                        return False
                else:
                    # Default is to use host CA certs
                    config["influxdb"]["ca-certificate"] = None

                if "verify-server-hostname" in config["influxdb"]:
                    if not isinstance(config["influxdb"]["verify-server-hostname"], bool):
                        print("ERROR: Invalid \"verify-server-hostname\" value in InfluxDB configuration")
                        return False
                else:
                    # Default is to verify the server hostname
                    config["influxdb"]["verify-server-hostname"] = True
        else:
            # Default is no TLS
            config["influxdb"]["use-tls"] = False
    else:
        print("ERROR: Configuration missing \"influxdb\" section")
        return False

    return True

def main(config):
    influxdb_protocol = "http"
    if config["influxdb"]["use-tls"]:
        influxdb_protocol = "https"
    influxdb_url = f'{influxdb_protocol}://{config["influxdb"]["host"]}:{config["influxdb"]["port"]}'
    print(f"Connecting to InfluxDB at {influxdb_url}")
    influx_client = None
    if config["influxdb"]["use-tls"]:
        influx_client = InfluxDBClient(url = influxdb_url,
                                       token = config["influxdb"]["token"],
                                       org = config["influxdb"]["org"],
                                       ssl_ca_cert = config["influxdb"]["ca-certificate"],
                                       verify_ssl = config["influxdb"]["verify-server-hostname"])
    else:
        influx_client = InfluxDBClient(url = influxdb_url,
                                       token = config["influxdb"]["token"],
                                       org = config["influxdb"]["org"])

    influx_write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    runtime_config = {}
    runtime_config["influxdb_api"] = influx_write_api
    runtime_config["influxdb_bucket"] = config["influxdb"]["bucket"]
    runtime_config["mqtt_topic"] = config["mqtt"]["topic"]

    mqtt_protocol = mqtt.MQTTProtocolVersion.MQTTv311
    if config["mqtt"]["v5"]:
        mqtt_protocol = mqtt.MQTTProtocolVersion.MQTTv5
    mqtt_client = mqtt.Client(callback_api_version = mqtt.CallbackAPIVersion.VERSION2,
                              client_id = config["mqtt"]["client-id"],
                              protocol = mqtt_protocol)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.on_subscribe = on_subscribe
    mqtt_client.on_unsubscribe = on_unsubscribe
    mqtt_client.user_data_set(runtime_config)

    mqtt_server_desc = ""
    if config["mqtt"]["use-tls"]:
        try:
            mqtt_client.tls_set(ca_certs = config["mqtt"]["ca-certificate"])
        except FileNotFoundError:
            print(f'Invalid MQTT ca-certificate \"{config["mqtt"]["ca-certificate"]}\"')
            sys.exit(2)
        mqtt_server_desc = " (TLS)"
        if not config["mqtt"]["verify-server-hostname"]:
            mqtt_client.tls_insecure_set(True)

    if config["mqtt"]["username"] is not None:
        mqtt_client.username_pw_set(username = config["mqtt"]["username"],
                                    password = config["mqtt"]["password"])

    print(f'Connecting to MQTT server at {config["mqtt"]["host"]}:{config["mqtt"]["port"]}{mqtt_server_desc}')
    try:
        mqtt_client.connect(host = config["mqtt"]["host"], port = config["mqtt"]["port"])
    except ConnectionRefusedError:
        print("Connection refused")
        sys.exit(2)
    mqtt_client.loop_forever()

# Process command-line
parser = argparse.ArgumentParser(
    prog="agl-mqtt-influxdb-publisher",
    description="Publishes AGL VSS proxy MQTT notifications to InfluxDB bucket")
parser.add_argument("-c", "--config", default = "agl-mqtt-influxdb-publisher.conf")
parser.add_argument("-v", "--verbose", action="count", default = 0)
parser.add_argument("-q", "--quiet", action="store_true")
args = parser.parse_args()

# Read configuration
config = read_config(args.config)
if config is None or not check_config(config):
    sys.exit(1)
verbosity = config["publisher"]["verbose"]
if args.quiet:
    # Quiet flag overrides given verbosity
    verbosity = 0
elif args.verbose > config["publisher"]["verbose"]:
    # Higher command-line verbosity overrides file value
    verbosity = args.verbose

# Run
try:
    main(config)
except KeyboardInterrupt:
    try:
        sys.exit(130)
    except SystemExit:
        os._exit(130)
