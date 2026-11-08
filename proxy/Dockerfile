FROM haproxy:2.9-alpine

USER root

COPY entrypoint.sh /entrypoint.sh
COPY haproxy.cfg /usr/local/etc/haproxy/haproxy.cfg

RUN chmod +x /entrypoint.sh && \
    FRIGATE_HOST=127.0.0.1:5000 \
    CAMERA1_HOST=127.0.0.1:65535 \
    CAMERA2_HOST=127.0.0.1:65535 \
    ROUTER_HOST=127.0.0.1:65535 \
    haproxy -c -f /usr/local/etc/haproxy/haproxy.cfg

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
