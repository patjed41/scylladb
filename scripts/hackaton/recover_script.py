#!/usr/bin/env python3

import argparse
import logging

from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
from raft_recovery.ssh_helper import create_ssh_client
from raft_recovery.find_last_uuid import find_newest_timeuuid
from raft_recovery.nodetool_helper import NodetoolHelper
from raft_recovery.query_history import get_latest_state_ids
from raft_recovery.remove_dead_nodes import remove_dead_nodes
from raft_recovery.remove_old_group_data import get_group0_id, delete_old_raft_group_data
from raft_recovery.step7 import step7
from raft_recovery.steps_8_9 import restart_scylla_in_recovery_mode


def get_cql_session(username=None, password=None, contact_points: list=None):
    # Configure authentication if username and password are provided
    if username and password:
        auth_provider = PlainTextAuthProvider(username=username, password=password)
        cluster = Cluster(contact_points=contact_points, auth_provider=auth_provider)
    else:
        cluster = Cluster(contact_points=contact_points)  # Connect without authentication

    return cluster.connect("system")

if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    parser = argparse.ArgumentParser(description="Start a recover procedure")
    parser.add_argument("--node", action="store", required=True, help="Provide a node to connect to")
    parser.add_argument("--user", action="store", required=True, help="SSH username to use for connection")
    parser.add_argument("--key", action="store", required=False, help="Path to SSH private key file (optional)")
    args = parser.parse_args()

    # Initialize SSH client session using the provided node IP, user, and key path (if provided)
    ssh = create_ssh_client(args.node, ssh_user=args.user)


    nodetool = NodetoolHelper(ssh=ssh)
    alive_nodes, dead_nodes = nodetool.get_all_nodes()
    cql_session = get_cql_session(args.user, args.key, contact_points=[node.ip for node in alive_nodes])

    latest_state_ids = get_latest_state_ids(session=cql_session)
    latest_id, leader_id = find_newest_timeuuid(latest_state_ids)
    hosts = [host for host in cql_session.cluster.metadata.all_hosts() if host.is_up is not None and host.is_up]

    old_group_id = get_group0_id(cql=cql_session)

    print(f"{latest_state_ids=}")
    print(f"{old_group_id=}")
    # leader_id = 'aef9c41e-9e71-4292-91a5-8dba9e573cc8'
    # old_group_id = 'a9c5ce20-36ec-11f0-bc0e-81530525a7cc'

    step7(session=cql_session, live_node_hosts=hosts)
    restart_scylla_in_recovery_mode(nodes=alive_nodes, recovery_leader_id=str(leader_id))
    remove_dead_nodes(nodetool=nodetool, host_ids=[node.host_id for node in dead_nodes], logger=logger)
    delete_old_raft_group_data(cql=cql_session, group_id=old_group_id, hosts=hosts)
    print("Recovery procedure completed successfully.")
