#!/bin/env python

from cassandra.cluster import Cluster
from cassandra.pool import Host

ips = ['127.0.0.1', '127.0.0.2']
cluster = Cluster(ips)
cql = cluster.connect()
hosts = cql.cluster.metadata.all_hosts()

# Needs to be called before restarting with recovery_leader set.
group_id = cql.execute("SELECT value FROM system.scylla_local WHERE key = 'raft_group0_id'").one().value


def delete_old_raft_group_data(host: Host) -> None:
    cql.execute(f'DELETE FROM system.raft WHERE group_id = {group_id}', host=host)
    cql.execute(f'DELETE FROM system.raft_snapshots WHERE group_id = {group_id}', host=host)
    cql.execute(f'DELETE FROM system.raft_snapshot_config WHERE group_id = {group_id}', host=host)


for ip in ips:
    host = [h for h in hosts if h.address == ip][0]
    delete_old_raft_group_data(host)
