FROM debian:bullseye

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get -q update

RUN apt-get install -y \
      gnupg2 \
      python3-fuse \
      python3-jsonschema \
      python3-yaml \
      python3-gnupg \
      python3-boto3 \
      python3-pytest \
      python3-pytest-cov \
      python3-sphinx \
      python3-sphinx-argparse \
      pylint3 \
      strace \
      sudo \
      fish

RUN useradd -G sudo -s /usr/bin/fish -m user

USER user

WORKDIR /wildland-fuse/docker

CMD ["./init.sh"]
