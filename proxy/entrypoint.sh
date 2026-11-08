#!/bin/sh
set -e

export FRIGATE_HOST="${FRIGATE_HOST:-127.0.0.1:5000}"
export CAMERA1_HOST="${CAMERA1_HOST:-127.0.0.1:65535}"
export CAMERA2_HOST="${CAMERA2_HOST:-127.0.0.1:65535}"
export ROUTER_HOST="${ROUTER_HOST:-127.0.0.1:65535}"

echo "Starting HAProxy..."
echo "  Frigate UI (/ or /frigate) -> ${FRIGATE_HOST}"
echo "  Camera 1   (/camera1)      -> ${CAMERA1_HOST}"
echo "  Camera 2   (/camera2)      -> ${CAMERA2_HOST}"
echo "  Router     (/router)       -> ${ROUTER_HOST}"

exec haproxy -f /usr/local/etc/haproxy/haproxy.cfg
