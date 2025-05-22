FROM ubuntu:latest

ENV container=docker
ENV PATH=/opt/scylladb/python3/bin:/usr/bin:/usr/sbin

RUN apt-get update \
 && apt-get install -y systemd openssh-server python3-yaml python3-pip\
 && mkdir /var/run/sshd \
 && echo "root:root" | chpasswd \
 && apt-get clean

RUN sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin yes/' /etc/ssh/sshd_config \
 && sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config

RUN pip3 install --break-system-packages --no-cache-dir traceback_with_variables
RUN pip3 install --prefix=/usr --break-system-packages --no-cache-dir supervisor
RUN ln -s /usr/local/bin/supervisord /usr/bin/supervisord

COPY binary /scylla
COPY start.sh /start.sh
COPY binary/dist/docker/etc etc/
COPY binary/dist/docker/scylla-housekeeping-service.sh /scylla-housekeeping-service.sh
COPY binary/dist/docker/scyllasetup.py /scyllasetup.py
COPY binary/dist/docker/commandlineparser.py /commandlineparser.py
COPY binary/dist/docker/docker-entrypoint.py /docker-entrypoint.py
RUN chmod +x /start.sh

RUN mkdir -p /opt/scylladb/supervisor
RUN touch /opt/scylladb/SCYLLA-CONTAINER-FILE
COPY binary/dist/common/supervisor/scylla-server.sh /opt/scylladb/supervisor/scylla-server.sh
COPY binary/dist/common/supervisor/scylla-node-exporter.sh /opt/scylladb/supervisor/scylla-node-exporter.sh
COPY binary/dist/common/supervisor/scylla_util.sh /opt/scylladb/supervisor/scylla_util.sh


RUN /scylla/install.sh --without-systemd

EXPOSE 22

ENTRYPOINT ["/start.sh"]