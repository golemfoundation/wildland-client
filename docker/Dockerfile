# Image for trying things out, based on the minimal one
# in Dockerfile. Install all customizations here.

FROM wildland-fuse-ci

USER root

# Run update && install as one command:
# https://docs.docker.com/develop/develop-images/dockerfile_best-practices/#apt-get
RUN apt-get -qy update && apt-get install -y \
      strace \
      sudo \
      nano \
      fish \
      vim \
      nginx \
      libnginx-mod-http-dav-ext

# Enable sudo

RUN usermod -G sudo user
RUN sed -i 's/ ALL/ NOPASSWD:ALL/' /etc/sudoers

# Setup nginx

COPY ./docker/nginx-webdav.conf /etc/nginx/sites-available
RUN rm -f /etc/nginx/sites-enabled/default
RUN ln -s ../sites-available/nginx-webdav.conf /etc/nginx/sites-enabled/
# FUSE is configured to allow only the owner
RUN sed -i s/www-data/user/ /etc/nginx/nginx.conf

USER user

ENTRYPOINT ["./docker/entrypoint.sh"]
