"""
SSH helper for raft_recovery scripts.
"""

import paramiko
import logging
from typing import Optional
import getpass

logger = logging.getLogger(__name__)


def create_ssh_client(ip: str, ssh_user: str, ssh_key_path: Optional[str] = None) -> paramiko.SSHClient:
    """
    Create and return an SSH client connected to the given IP.
    If ssh_key_path is not provided, prompt for password.
    Args:
        ip: IP address to connect to.
        ssh_user: SSH username.
        ssh_key_path: Path to SSH private key file (optional).
    Returns:
        Connected paramiko.SSHClient instance.
    Raises:
        Exception if connection fails.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if ssh_key_path:
        ssh.connect(ip, username=ssh_user, key_filename=ssh_key_path)
    else:
        password = getpass.getpass(f"Enter SSH password for {ssh_user}@{ip}: ")
        ssh.connect(ip, username=ssh_user, password=password)
    logger.info(f"SSH connection established to {ip}")
    return ssh
