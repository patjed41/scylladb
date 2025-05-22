#!/bin/env python
from cassandra.pool import Host


def get_group0_id(cql) -> str:
    return cql.execute("SELECT value FROM system.scylla_local WHERE key = 'raft_group0_id'").one().value


# Needs to be called in the main script before restarting with recovery_leader set.
# old_group_id = get_group0_id(cql)


def clean_node(cql, host: Host, group_id: str) -> None:
    cql.execute(f'DELETE FROM system.raft WHERE group_id = {group_id}', host=host)
    cql.execute(f'DELETE FROM system.raft_snapshots WHERE group_id = {group_id}', host=host)
    cql.execute(f'DELETE FROM system.raft_snapshot_config WHERE group_id = {group_id}', host=host)


def delete_old_raft_group_data(cql, group_id) -> None:
    hosts = cql.cluster.metadata.all_hosts()
    for host in hosts:
        clean_node(cql, host, group_id)
