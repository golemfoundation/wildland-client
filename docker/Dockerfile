# Image for trying things out, based on the minimal one
# in Dockerfile. Install all customizations here.

FROM wildland-client-ci

USER root

# Run update && install as one command:
# https://docs.docker.com/develop/develop-images/dockerfile_best-practices/#apt-get
RUN apt-get -qy update && apt-get install -y \
      strace \
      sudo \
      fish \
      procps htop \
      less nano vim \
      ranger \
      apache2 \
      nnn

# Enable sudo

RUN usermod -G sudo user
RUN sed -i 's/ ALL/ NOPASSWD:ALL/' /etc/sudoers

# Setup webdav

RUN sed -i 's/www-data/user/' /etc/apache2/envvars
COPY ./docker/apache2-wl.conf /etc/apache2/sites-available/wl.conf
RUN a2enmod dav dav_fs rewrite
RUN a2dissite 000-default
RUN a2ensite wl
RUN mkdir -p /var/lock/apache2
RUN chown -R user /var/lock/apache2

USER user

ENTRYPOINT ["./docker/entrypoint.sh"]
