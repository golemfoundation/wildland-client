FROM debian:bullseye

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get -q update

RUN apt-get install -y \
      gnupg2 \
      python3-fuse \
      python3-jsonschema \
      python3-yaml \
      python3-pytest \
      python3-gnupg \
      python3-sphinx \
      pylint3 \
      strace \
      fish

ADD *.sh /usr/local/bin/

RUN useradd -s /usr/bin/fish -m user

CMD ["init.sh"]
