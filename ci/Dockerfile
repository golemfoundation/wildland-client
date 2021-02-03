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
      signify-openbsd \
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
      screen

# add IPFS client

RUN curl -sL \
  https://github.com/ipfs/go-ipfs/releases/download/v0.7.0/go-ipfs_v0.7.0_linux-amd64.tar.gz \
  -o go-ipfs_v0.7.0_linux-amd64.tar.gz \
  && echo "1d5910f27e8d7ea333145f15c6edcbacc1e8db3a99365f0847467bdfa7c73f4d7a05562e46be8e932056c8324ed0769ca1b6758dfb0ac4c2e1b6066b57c4a086  go-ipfs_v0.7.0_linux-amd64.tar.gz" | sha512sum --check --status \
  && tar -xf go-ipfs_v0.7.0_linux-amd64.tar.gz \
  && install go-ipfs/ipfs /bin/ \
  && rm -rf go-ipfs go-ipfs_v0.7.0_linux-amd64.tar.gz

RUN useradd --create-home user
RUN echo user_allow_other >> /etc/fuse.conf

RUN mkdir /home/user/wildland-client

USER user
WORKDIR /home/user/wildland-client

COPY ./requirements.txt .
RUN python3 -m venv /home/user/env/
RUN /home/user/env/bin/pip install -r requirements.txt

RUN mkdir -p /tmp/docker-user-runtime
ENV XDG_RUNTIME_DIR /tmp/docker-user-runtime
