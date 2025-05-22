#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from cassandra.cluster import Cluster, Host
from cassandra.auth import PlainTextAuthProvider
from cassandra.query import SimpleStatement
from cassandra import DriverException
import requests
import time

# Authentication and connection configuration
discovery_host = "127.0.0.1"
rest_port = 10000
cql_user = "cassandra"
cql_password = "cassandra"

def get_live_node_ips():
    gossip_endpoint = f"http://{discovery_host}:{rest_port}/gossiper/endpoint/live"
    print(f"querying live nodes from {gossip_endpoint}...")
    response = requests.get(gossip_endpoint)
    response.raise_for_status()
    live_nodes = response.json()
    print(f"\tdiscovered {len(live_nodes)} live nodes: {live_nodes}")
    return live_nodes

def wait_for(pred, deadline, period = 1, before_retry = None):
    while True:
        assert (time.time() < deadline), "Deadline exceeded, failing test."
        res = pred()
        if res is not None:
            return res
        time.sleep(period)
        if before_retry:
            before_retry()

def wait_for_cql_and_get_hosts(cluster, ips, deadline):
    ip_set = set(ips)
    def get_hosts():
        hosts = cluster.metadata.all_hosts()
        remaining = ip_set - {h.address for h in hosts}
        if not remaining:
            return hosts
        print(f"driver hasn't yet learned about hosts: {remaining}")
        return None
    def try_refresh_nodes():
        try:
            cluster.refresh_nodes(force_token_rebuild=True)
        except DriverException:
            pass
    hosts = wait_for(pred=get_hosts, deadline=deadline,
                     before_retry=try_refresh_nodes)
    hosts = [h for h in hosts if h.address in ip_set]
    return hosts

def main():
    auth_provider = PlainTextAuthProvider(username=cql_user, password=cql_password)
    cluster = Cluster([discovery_host], auth_provider=auth_provider)
    session = cluster.connect()
    live_node_ips = get_live_node_ips()
    live_node_hosts = wait_for_cql_and_get_hosts(cluster, live_node_ips, time.time() + 60.)
    step7(session, live_node_hosts)
    cluster.shutdown()

def step7(session, live_node_hosts):
    cql_statements = [
        "DELETE FROM system.scylla_local WHERE key = 'raft_group0_id'",
        "TRUNCATE TABLE system.discovery"
    ]
    for host in live_node_hosts:
        for cql in cql_statements:
            try:
                stmt = SimpleStatement(cql)
                print(f"running {cql} on {host.address}")
                session.execute(stmt, host=host)
                print("\tdone")
            except Exception as e:
                raise RuntimeError(f'failed to run {cql} on {host.address}, error: {e}')

if __name__ == "__main__":
    main()
