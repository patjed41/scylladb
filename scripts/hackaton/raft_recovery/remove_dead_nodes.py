"""
Script for removing dead nodes from a ScyllaDB cluster using nodetool removenode via SSH.
"""

import paramiko
import logging
from typing import List
from .ssh_helper import create_ssh_client
from .nodetool_helper import NodetoolHelper


def remove_dead_nodes(ssh: paramiko.SSHClient, nodetool: NodetoolHelper, host_ids: List[str], logger: logging.Logger) -> None:
    """
    Removes each host ID in the list using the provided NodetoolHelper and SSH client session.
    Args:
        ssh: An established paramiko.SSHClient session to the initiator node.
        nodetool: NodetoolHelper instance to use for nodetool operations.
        host_ids: List of host IDs to remove from the cluster.
        logger: Logger instance to use for logging.
    """
    logger.debug(f"Removing nodes: {host_ids} using provided SSH session and nodetool at {nodetool.nodetool_path}")
    for host_id in host_ids:
        nodetool.remove_dead_node(ssh, host_id)
