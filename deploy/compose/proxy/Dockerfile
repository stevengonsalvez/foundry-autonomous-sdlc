# Allow-list egress proxy for the coder (squid, forward proxy only).
FROM alpine:3.22

RUN apk add --no-cache squid \
    && mkdir -p /run/squid \
    && chown squid:squid /run/squid

COPY squid.conf /etc/squid/squid.conf
COPY allowlist.txt /etc/squid/allowlist.txt

USER squid
EXPOSE 3128
HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD nc -z 127.0.0.1 3128 || exit 1
# -N: foreground, -d1: errors to stderr. squid -k parse validates the config before it starts.
CMD ["sh", "-c", "squid -k parse -f /etc/squid/squid.conf >/dev/null && exec squid -N -d1 -f /etc/squid/squid.conf"]
