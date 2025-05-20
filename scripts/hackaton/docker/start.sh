#!/bin/bash
/docker-entrypoint.py "$@" &
/usr/sbin/sshd -D
