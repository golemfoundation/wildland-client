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
      fish \
      nginx

COPY ./docker/nginx-webdav.conf /etc/nginx/sites-available

RUN rm -f /etc/nginx/sites-enabled/default
RUN ln -s ../sites-available/nginx-webdav.conf /etc/nginx/sites-enabled/
# FUSE is configured to allow only the owner
RUN sed -i s/www-data/user/ /etc/nginx/nginx.conf

RUN useradd -G sudo -s /usr/bin/fish -m user
RUN sed -i 's/ ALL/ NOPASSWD:ALL/' /etc/sudoers

USER user

WORKDIR /home/user

COPY ./requirements.txt .
RUN python3 -m venv /home/user/env/
RUN /home/user/env/bin/pip3 install -r requirements.txt

WORKDIR /wildland-fuse

ENTRYPOINT ["./docker/entrypoint.sh"]
