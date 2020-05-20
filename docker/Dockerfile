FROM debian:bullseye

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get -q update

RUN apt-get install -y \
      gcc \
      make \
      gnupg2 \
      python3-dev \
      python3-venv \
      fuse \
      libfuse-dev \
      pkg-config \
      strace \
      sudo \
      nano \
      fish

RUN useradd -G sudo -s /usr/bin/fish -m user

USER user

WORKDIR /home/user

COPY ./requirements.txt .
RUN python3 -m venv /home/user/env/
RUN /home/user/env/bin/pip3 install -r requirements.txt

WORKDIR /wildland-fuse

ENTRYPOINT ["./docker/entrypoint.sh"]
