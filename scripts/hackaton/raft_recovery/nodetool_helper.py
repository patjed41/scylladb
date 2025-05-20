"""
Helper class for managing nodetool path and running nodetool commands.
"""

import paramiko
import logging
from typing import List

logger = logging.getLogger(__name__)

class NodetoolHelper:
    def __init__(self, nodetool_path: str = "nodetool"):
        self.nodetool_path = nodetool_path

    def remove_dead_node(self, ssh: paramiko.SSHClient, host_id: str) -> None:
        """
        Runs 'nodetool removenode <host_id>' using the provided SSH client session.
        Args:
            ssh: An established paramiko.SSHClient session to the initiator node.
            host_id: Host ID to remove from the cluster.
        """
        logger.info(f"Removing node: {host_id}")
        cmd = f"{self.nodetool_path} removenode {host_id}"
        logger.debug(f"Running: {cmd}")
        try:
            stdin, stdout, stderr = ssh.exec_command(cmd)
            out = stdout.read().decode()
            err = stderr.read().decode()
            logger.debug(f"removenode output for {host_id}: {out}")
            if err:
                logger.error(f"removenode error for {host_id}: {err}")
        except Exception as e:
            logger.error(f"Failed to run removenode for {host_id}: {e}")
