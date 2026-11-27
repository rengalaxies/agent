#!/bin/sh
set -eu
umask 077
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
/usr/bin/date -u +%FT%TZ >> /var/lib/impactmap-tls/reload-proof.log
