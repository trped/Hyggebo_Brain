#!/usr/bin/with-contenv bashio

# Read options from HA Supervisor
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USER=$(bashio::config 'mqtt_user')
export MQTT_PASSWORD=$(bashio::config 'mqtt_password')
export PG_HOST=$(bashio::config 'pg_host')
export PG_PORT=$(bashio::config 'pg_port')
export PG_DATABASE=$(bashio::config 'pg_database')
export PG_USER=$(bashio::config 'pg_user')
export PG_PASSWORD=$(bashio::config 'pg_password')
export LOG_LEVEL=$(bashio::config 'log_level')

# Resolve HA Supervisor token
if [ -z "${SUPERVISOR_TOKEN:-}" ]; then
    export SUPERVISOR_TOKEN=$(cat /run/s6/container_environment/SUPERVISOR_TOKEN 2>/dev/null || echo "")
fi

bashio::log.info "Starting Hyggebo Brain v0.7.0..."
bashio::log.info "PostgreSQL: ${PG_HOST}:${PG_PORT}/${PG_DATABASE}"
bashio::log.info "MQTT: ${MQTT_HOST}:${MQTT_PORT}"

exec python3 /app/main.py
