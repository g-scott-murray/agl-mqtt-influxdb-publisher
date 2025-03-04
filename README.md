# Introduction

A simple InfluxDB publisher for AGL VSS proxy MQTT messages.  See <https://git.automotivelinux.org/src/agl-vss-proxy/tree/README.md> for more details on the proxy and its message format.

# Support

Support options include:
- #general Discord channel on AGL's Discord server <https://discord.gg/ZztCaVeQVG>
- AGL App Framework and Connectivity expert group (EG) Zoom call every second Wednesday, see calendar at https://lists.automotivelinux.org/g/agl-dev-community/calendar.
- AGL community mailing list, see https://lists.automotivelinux.org/g/agl-dev-community for subscription information and archives.

# Installation

Required dependencies:
- Python 3.10 or higher
- pip

Install the required Python modules with `pip3`, e.g. `pip3 install --user -r requirements.text`.  The `agl-mqtt-influxdb-publisher.py` script may then either be run in place or copied to a desired install location.

# Configuration

The script requires a configuation file in TOML syntax.  If run with no arguments, it will look for `agl-mqtt-influxdb-publisher.conf` in the current directory.  Alternatively, a different file can be specified on the command-line with the `--config` (or `-c`) option.  An example of a minimal configuration file is:
```
[mqtt]
topic = "agl/v2c/demo"

[influxdb]
org = "AGL"
bucket = "test"
token = "API token..."
  ```
  This will result in attempting to use local instances of a MQTT broker and InfluxDB database with no TLS and the given values for the MQTT topic and InfluxDB organization, bucket, and API token.  See `agl-mqtt-influxdb-publisher.conf.example` for a full example configuration file that documents the various options.

# Source Provenance

The agl-vss-proxy MQTT payload protobuf definition has been copied to `protos/agl/vss-notification.proto` for development convenience.

# TODOs

Potential extensions:
- MQTT client certificate support
- TLS pre-shared key support
- MQTT v5 message properties support

