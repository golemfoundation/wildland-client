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
      python3.8-dev \
      python3-pip \
      python3.8-venv \
      fuse \
      libfuse-dev \
      pkg-config \
      time \
      tree \
      netcat-openbsd \
      moreutils \
      git

RUN useradd --create-home user
RUN echo user_allow_other >> /etc/fuse.conf

RUN mkdir /home/user/wildland-fuse

USER user
WORKDIR /home/user/wildland-fuse

COPY ./requirements.txt .
RUN python3.8 -m venv /home/user/env/
RUN /home/user/env/bin/pip install -r requirements.txt


RUN mkdir -p /tmp/docker-user-runtime
ENV XDG_RUNTIME_DIR /tmp/docker-user-runtime
