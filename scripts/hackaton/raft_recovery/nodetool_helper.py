"""
Helper class for managing nodetool path and running nodetool commands.
"""
from types import SimpleNamespace

import paramiko
import logging
from typing import List, Any

logger = logging.getLogger(__name__)



class NodetoolHelper:
    def __init__(self, ssh: paramiko.SSHClient, nodetool_path: str = "nodetool"):
        self.ssh = ssh
        self.nodetool_path = nodetool_path

    def remove_dead_node(self, host_id: str, ignore_hosts) -> None:
        """
        Runs 'nodetool removenode <host_id>' using the provided SSH client session.
        Args:
            ssh: An established paramiko.SSHClient session to the initiator node.
            host_id: Host ID to remove from the cluster.
        """
        logger.info(f"Removing node: {host_id}")
        # cmd = f"{self.nodetool_path} removenode {host_id}"
        cmd = f"nodetool removenode {host_id}"
        if len(ignore_hosts) > 0:
            cmd += f' --ignore-dead-nodes {','.join(ignore_hosts)}'
        logger.debug(f"Running: {cmd}")
        try:
            stdin, stdout, stderr = self.ssh.exec_command(cmd)
            out = stdout.read().decode()
            err = stderr.read().decode()
            logger.debug(f"removenode output for {host_id}: {out}")
            if err:
                logger.error(f"removenode error for {host_id}: {err}")
        except Exception as e:
            logger.error(f"Failed to run removenode for {host_id}: {e}")

    def get_all_nodes(self) -> list[Any] | tuple[list[Any], list[Any]]:
        """
        Get a list of alive nodes in the cluster using nodetool status.
        """
        try:
            stdin, stdout, stderr = self.ssh.exec_command("nodetool status")
            alive_nodes = []
            dead_nodes = []
            for line in stdout.read().decode('ascii').splitlines():
                if line[:2] not in ['UN', 'UL', 'DN', 'DL']:
                    continue
                node = SimpleNamespace()
                parts = line.split()
                node.status = parts[0]
                node.ip = parts[1]
                node.host_id = parts[6]
                if node.status == "UN" or node.status == "UL":
                    alive_nodes.append(node)
                elif node.status == "DN" or node.status == "DL":
                    dead_nodes.append(node)

            return alive_nodes, dead_nodes
        except Exception as e:
            logger.error(f"Failed to run nodetool status: {e}")
            return []

