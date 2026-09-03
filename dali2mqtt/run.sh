#!/usr/bin/env bashio
# shellcheck shell=bash
set -e

CONFIG_PATH=/data/options.json
RUNTIME_PATH=/data/dali2mqtt.runtime.json
DEVICES_NAMES=/data/devices.yaml

# --------------------------------------------------------------------------
# Resolve the MQTT broker: manual override wins, otherwise use the Home
# Assistant MQTT service, otherwise fail loudly.
# --------------------------------------------------------------------------
if bashio::config.has_value 'mqtt_host'; then
    MQTT_HOST=$(bashio::config 'mqtt_host')
    MQTT_PORT=$(bashio::config 'mqtt_port')
    MQTT_USER=$(bashio::config 'mqtt_username')
    MQTT_PASS=$(bashio::config 'mqtt_password')
    bashio::var.is_empty "${MQTT_PORT}" && MQTT_PORT=1883
    bashio::log.info "Using manually configured MQTT broker ${MQTT_HOST}:${MQTT_PORT}"
elif bashio::services.available 'mqtt'; then
    MQTT_HOST=$(bashio::services 'mqtt' 'host')
    MQTT_PORT=$(bashio::services 'mqtt' 'port')
    MQTT_USER=$(bashio::services 'mqtt' 'username')
    MQTT_PASS=$(bashio::services 'mqtt' 'password')
    bashio::log.info "Using Home Assistant MQTT service ${MQTT_HOST}:${MQTT_PORT}"
else
    bashio::exit.nok \
        "No MQTT broker configured and no MQTT service available. Install the Mosquitto add-on or set mqtt_host in the options."
fi

# --------------------------------------------------------------------------
# Build a fully resolved configuration document for the Python app.
# The Home Assistant REST endpoint uses the Supervisor proxy + token, so no
# host/IP or long-lived token is ever baked into the image.
# --------------------------------------------------------------------------
jq -n \
    --argjson opts "$(cat "${CONFIG_PATH}")" \
    --arg mqtt_server "${MQTT_HOST}" \
    --argjson mqtt_port "${MQTT_PORT}" \
    --arg mqtt_username "${MQTT_USER}" \
    --arg mqtt_password "${MQTT_PASS}" \
    --arg ha_base_url "http://supervisor/core" \
    --arg ha_token "${SUPERVISOR_TOKEN:-}" \
    --arg devices_names "${DEVICES_NAMES}" \
    '$opts
      + {
          mqtt_server: $mqtt_server,
          mqtt_port: $mqtt_port,
          mqtt_username: $mqtt_username,
          mqtt_password: $mqtt_password,
          ha_base_url: $ha_base_url,
          ha_token: $ha_token,
          ha_verify_ssl: false,
          devices_names: $devices_names
        }
      | del(.mqtt_host)' > "${RUNTIME_PATH}"

bashio::log.info "Starting dali2mqtt (driver: $(bashio::config 'dali_driver'))"

cd /opt/dali2mqtt
exec python3 -m app --options-json "${RUNTIME_PATH}"
