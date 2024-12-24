#
# Copyright (C) 2025-present ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import time
import pytest

from test.pylib.manager_client import ManagerClient
from test.pylib.util import wait_for_cql_and_get_hosts
from test.topology.util import check_system_topology_and_cdc_generations_v3_consistency, \
        check_token_ring_and_group0_consistency, delete_raft_data, reconnect_driver, wait_for_cdc_generations_publishing
from test.topology_custom.test_group0_schema_versioning import get_group0_schema_version, get_local_schema_version

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_raft_recovery_entry_lose(manager: ManagerClient):
    """
    We start a cluster with 5 nodes and create a scenario where nodes have the following group 0 states:
    - node 1: v1,
    - node 2: v2,
    - nodes 3-5: v3.

    Then, nodes 3-5 die and group 0 majority is permanently lost. This implies that we permanently lose v3. After
    recovering majority, nodes 1-2 shoud have v2, which is the only safe option.

    We recover majority by:
    - removing Raft data on nodes 1-2,
    - setting new_leader_ip to IP of node 2 on nodes 1-2,
    - performing rolling restart of nodes 1-2 (we restart node 2 first).
    This procedure ensures that node 2 becomes the leader of new group 0 and only nodes 1-2 participate in the group
    0 discovery. Note that node 2 must become the leader of new group 0 since it has a newer group 0 state. When node 1
    joins new group 0, it receives group 0 snapshot with v2 from node 2 and applies it. If node 1 became the leader,
    both nodes would end up with v1.

    After recovering majority, we check that node 1 has moved its group 0 state to v2. Then, we remove nodes 3-5 from
    topology using the standard removenode procedure.
    """
    servers = await manager.servers_add(5)
    live_servers = servers[:2]
    dead_servers = servers[2:]

    cql = manager.get_cql()

    await manager.server_stop(live_servers[0].server_id)
    await cql.run_async(
        "CREATE KEYSPACE ks1 WITH replication = {'class': 'NetworkTopologyStrategy', 'replication_factor': 1}")
    await manager.server_stop(live_servers[1].server_id)
    await cql.run_async(
        "CREATE KEYSPACE ks2 WITH replication = {'class': 'NetworkTopologyStrategy', 'replication_factor': 1}")

    cql = await reconnect_driver(manager)
    hosts = await wait_for_cql_and_get_hosts(cql, dead_servers, time.time() + 60)

    v_group0 = await get_group0_schema_version(cql, hosts[0])
    logging.info(f"group 0 schema version {v_group0}")

    for srv in dead_servers:
        await manager.server_stop(server_id=srv.server_id)

    for srv in live_servers:
        await manager.server_start(srv.server_id)

    cql = await reconnect_driver(manager)
    hosts = await wait_for_cql_and_get_hosts(cql, live_servers, time.time() + 60)

    v_node1 = await get_local_schema_version(cql, hosts[0])
    logging.info(f"node 1 schema version {v_node1}")
    v_node2 = await get_local_schema_version(cql, hosts[1])
    logging.info(f"node 2 schema version {v_node2}")
    assert v_group0 != v_node1 != v_node2 != v_group0

    for h in hosts:
        # I need to investigate what part of delete_raft_data is necessary.
        await delete_raft_data(cql, h)
        await cql.run_async("TRUNCATE TABLE system.raft", host=h)
        await cql.run_async(
                f"UPDATE system.scylla_local SET value = '{str(live_servers[1].ip_addr)}' WHERE key = 'new_leader_ip'",
                host=h)

    # Node 2 will become the leader of new group 0.
    for srv in live_servers[::-1]:
        await manager.server_restart(server_id=srv.server_id)

    cql = await reconnect_driver(manager)
    hosts = await wait_for_cql_and_get_hosts(cql, live_servers, time.time() + 60)

    new_v_group0 = await get_group0_schema_version(cql, hosts[1])
    logging.info(f"new group 0 schema version {v_group0}")
    new_v_node1 = await get_local_schema_version(cql, hosts[0])
    logging.info(f"new node 1 schema version {v_node1}")
    new_v_node2 = await get_local_schema_version(cql, hosts[1])
    logging.info(f"new node 2 schema version {v_node2}")
    assert v_group0 != new_v_group0 == new_v_node1 == new_v_node2

    for h in hosts:
        await cql.run_async("DELETE value FROM system.scylla_local WHERE key = 'new_leader_ip'")

    for i, being_removed in enumerate(dead_servers):
        ignored = [dead_srv.ip_addr for dead_srv in dead_servers[i + 1:]]
        initiator = live_servers[i % 2]
        await manager.remove_node(initiator.server_id, being_removed.server_id, ignored)

    await wait_for_cdc_generations_publishing(cql, hosts, time.time() + 60)
    await check_token_ring_and_group0_consistency(manager)
    await check_system_topology_and_cdc_generations_v3_consistency(manager, hosts)

    new_server = await manager.server_add()

    hosts = await wait_for_cql_and_get_hosts(cql, live_servers + [new_server], time.time() + 60)

    await wait_for_cdc_generations_publishing(cql, hosts, time.time() + 60)
    await check_token_ring_and_group0_consistency(manager)
    await check_system_topology_and_cdc_generations_v3_consistency(manager, hosts)
