# Base Docker image for Wildland.
#
# This should be as minimal as possible, and enough to run CI commands
# (make ci-*).
#
# For customization, trying Widland out, etc., see docker/.

FROM debian:bullseye

ARG DEBIAN_FRONTEND=noninteractive

# Run update && install as one command:
# https://docs.docker.com/develop/develop-images/dockerfile_best-practices/#apt-get
RUN apt-get -qy update && apt-get install -y \
      gcc \
      make \
      python3-dev \
      python3-pip \
      python3-venv \
      fuse \
      libfuse-dev \
      pkg-config \
      time \
      tree \
      netcat-openbsd \
      moreutils \
      git \
      curl \
      tmux \
      screen \
      jq \
      procps \
      gocryptfs \
      encfs

# add IPFS client
RUN ARCH=$(arch) && CHECKSUM="" \
  && if [ "aarch64" = ${ARCH} ] || [ "arm64" = ${ARCH} ]  ; then \
    ARCH="arm64"; \
    CHECKSUM="57455853cef842233fb6408dc599c9be5950e61adaac9b7682324987cbb9ca339382563b145d94b6d177e0a507a72916a207c4c6ec8c1015eaace730884f3f36"; \
  elif [ "amd64" = ${ARCH} ] || [ "x86_64" = ${ARCH} ] ; then \
    ARCH="amd64"; \
    CHECKSUM="1d5910f27e8d7ea333145f15c6edcbacc1e8db3a99365f0847467bdfa7c73f4d7a05562e46be8e932056c8324ed0769ca1b6758dfb0ac4c2e1b6066b57c4a086"; \
  else \
    echo "Unsupported architecture $ARCH"; \
    exit 126 ; \
  fi \
  && curl -sL \
      https://github.com/ipfs/go-ipfs/releases/download/v0.7.0/go-ipfs_v0.7.0_linux-${ARCH}.tar.gz \
      -o go-ipfs_v0.7.0_linux-${ARCH}.tar.gz \
      && echo "$CHECKSUM  go-ipfs_v0.7.0_linux-$ARCH.tar.gz" | sha512sum --check --status \
      && tar -xf go-ipfs_v0.7.0_linux-${ARCH}.tar.gz \
      && install go-ipfs/ipfs /bin/ \
      && rm -rf go-ipfs go-ipfs_v0.7.0_linux-${ARCH}.tar.gz

RUN useradd --shell /bin/bash --create-home user
RUN echo user_allow_other >> /etc/fuse.conf

RUN mkdir /home/user/wildland-client

USER user
WORKDIR /home/user/wildland-client

COPY ./requirements.txt .
RUN python3 -m venv /home/user/env/
RUN /home/user/env/bin/pip install -r requirements.txt

RUN mkdir -p /tmp/docker-user-runtime
ENV XDG_RUNTIME_DIR /tmp/docker-user-runtime
ENV WL_CLI ./wl
ENV WL_CTRL_SOCK /tmp/docker-user-runtime/wlfuse.sock
ENV WL_CONFIG_DIR /home/user/.config/wildland
ENV WL_MOUNT_POINT /home/user/wildland
ENV WL_START_CMD "./wl start"
ENV WL_STOP_CMD "./wl stop"