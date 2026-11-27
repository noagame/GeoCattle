# Punto de llegada del túnel inverso del PC del campo (modo espejo).
# Solo acepta reenvíos remotos a los puertos 15432 (PostgreSQL del PC) y 18084 (web del PC).
FROM alpine:3.23
RUN apk add --no-cache openssh-server \
 && adduser -D -H -s /sbin/nologin espejo \
 && sed -i 's/^espejo:!/espejo:*/' /etc/shadow \
 && mkdir -p /etc/ssh/keys /etc/ssh/authorized \
 && rm -f /etc/ssh/ssh_host_*
COPY infrastructure/espejo-ssh/sshd_config /etc/ssh/sshd_config
COPY infrastructure/espejo-ssh/entrypoint.sh /usr/local/bin/espejo-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/espejo-entrypoint /etc/ssh/sshd_config \
 && chmod 0755 /usr/local/bin/espejo-entrypoint && chmod 0644 /etc/ssh/sshd_config
EXPOSE 22
ENTRYPOINT ["/usr/local/bin/espejo-entrypoint"]
