FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    iproute2 \
    iputils-ping \
    iptables \
    tcpdump \
    net-tools \
    python3 \
    python3-pip \
    bash \
    inetutils-traceroute \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/sdwan

COPY collector.py engine.py net_manager.py main.py /opt/sdwan/
COPY branch_entrypoint.sh /opt/sdwan/branch_entrypoint.sh
RUN chmod +x /opt/sdwan/branch_entrypoint.sh

ENTRYPOINT ["/opt/sdwan/branch_entrypoint.sh"]