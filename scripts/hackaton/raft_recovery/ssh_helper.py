"""
SSH helper for raft_recovery scripts.
"""

import paramiko
import logging

logger = logging.getLogger(__name__)


def create_ssh_client(ip: str, ssh_user: str, ssh_key_path: str) -> paramiko.SSHClient:
    """
    Create and return an SSH client connected to the given IP.
    Args:
        ip: IP address to connect to.
        ssh_user: SSH username.
        ssh_key_path: Path to SSH private key file.
    Returns:
        Connected paramiko.SSHClient instance.
    Raises:
        Exception if connection fails.
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, username=ssh_user, key_filename=ssh_key_path)
    logger.info(f"SSH connection established to {ip}")
    return ssh
