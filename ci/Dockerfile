# Base Docker image for Wildland.
#
# This should be as minimal as possible, and enough to run CI commands
# (make ci-*).
#
# For customization, trying Widland out, etc., see docker/.

FROM debian:bullseye

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get -qy update

RUN apt-get install -y \
      gcc \
      make \
      gnupg2 \
      signify-openbsd \
      python3-dev \
      python3-venv \
      fuse \
      libfuse-dev \
      pkg-config

RUN useradd --create-home user

RUN mkdir /home/user/wildland-fuse

USER user
WORKDIR /home/user/wildland-fuse

COPY ./requirements.txt .
RUN python3 -m venv /home/user/env/
RUN /home/user/env/bin/pip3 install -r requirements.txt
