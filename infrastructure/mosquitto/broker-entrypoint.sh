#!/bin/sh
set -eu
umask 077
: "${MQTT_USERNAME:?Defina MQTT_USERNAME}"
: "${MQTT_PASSWORD:?Defina MQTT_PASSWORD}"
# No se imprimen credenciales. El archivo queda dentro del contenedor.
mosquitto_passwd -b -c /mosquitto/data/passwords "$MQTT_USERNAME" "$MQTT_PASSWORD"
chown mosquitto:mosquitto /mosquitto/data/passwords
cat > /mosquitto/data/acl <<EOF
user $MQTT_USERNAME
topic readwrite application/#
topic readwrite geocattle/#
topic readwrite au915_0/#
EOF
chown mosquitto:mosquitto /mosquitto/data/acl
exec /usr/sbin/mosquitto -c /opt/geocattle/mosquitto.conf

