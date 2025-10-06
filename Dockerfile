FROM  andrius/asterisk:22.5.2_debian-trixie

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv supervisor ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/freya

COPY requirements.txt /opt/freya/requirements.txt
RUN python3 -m venv /opt/freya/.venv && \
    /opt/freya/.venv/bin/pip install --no-cache-dir -r /opt/freya/requirements.txt
ENV PATH="/opt/freya/.venv/bin:$PATH"

COPY . /opt/freya

RUN chown -R asterisk:asterisk /opt/freya

COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/freya

EXPOSE 5060/udp 8088 8099 10000-20000/udp

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD asterisk -rx 'core show uptime' >/dev/null 2>&1 || exit 1

CMD ["/usr/bin/supervisord","-n","-c","/etc/supervisor/conf.d/supervisord.conf"]
