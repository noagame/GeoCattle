#!/bin/sh
# Prepara la llave del servidor (persistente en volumen) y las claves autorizadas del PC.
set -eu
if [ ! -s /etc/ssh/keys/ssh_host_ed25519_key ]; then
  ssh-keygen -q -t ed25519 -N '' -f /etc/ssh/keys/ssh_host_ed25519_key
fi
chmod 0600 /etc/ssh/keys/ssh_host_ed25519_key
# El archivo montado pertenece al anfitrión; sshd exige una copia de root sin escritura ajena.
if [ -s /etc/geocattle/authorized_keys ]; then
  grep -E '^restrict,port-forwarding,' /etc/geocattle/authorized_keys > /etc/ssh/authorized/espejo || true
else
  : > /etc/ssh/authorized/espejo
fi
chown root:root /etc/ssh/authorized/espejo
chmod 0644 /etc/ssh/authorized/espejo
if [ ! -s /etc/ssh/authorized/espejo ]; then
  echo "espejo-ssh: sin clave del PC autorizada; ejecuta scripts/mirror.py authorize" >&2
fi
echo "espejo-ssh: huella del servidor $(ssh-keygen -lf /etc/ssh/keys/ssh_host_ed25519_key.pub)"
exec /usr/sbin/sshd -D -e
