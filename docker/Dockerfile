FROM debian:bullseye

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get -q update

RUN apt-get install -y \
      python3-fuse \
      python3-voluptuous \
      python3-yaml \
      strace \
      fish

ADD init.sh /

RUN useradd -s /usr/bin/fish -m user

CMD ["/init.sh"]
