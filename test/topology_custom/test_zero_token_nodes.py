#
# Copyright (C) 2024-present ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import pytest
import logging

from cassandra import ConsistencyLevel
from cassandra.policies import WhiteListRoundRobinPolicy
from cassandra.query import SimpleStatement
from test.pylib.manager_client import ManagerClient
from test.pylib.scylla_cluster import ReplaceConfig
from test.pylib.util import unique_name
from test.topology.conftest import cluster_con

logger = logging.getLogger(__name__)

@pytest.mark.asyncio
@pytest.mark.skip
@pytest.mark.parametrize("tablets_enabled", [True, False])
async def test_zero_token_nodes_topology_ops(manager: ManagerClient, tablets_enabled: bool):
    normal_cfg = {'enable_tablets': tablets_enabled}
    zero_token_cfg = {'enable_tablets': tablets_enabled, 'join_ring': False}

    await manager.server_add(config=zero_token_cfg, expected_error='Cannot start the first node in the cluster as zero-token')

    server_a = await manager.server_add(config=normal_cfg)
    server_b = await manager.server_add(config=zero_token_cfg)
    await manager.server_add(config=normal_cfg)  # Needed to preserve the Raft majority.

    await manager.server_stop_gracefully(server_b.server_id)
    replace_cfg_b = ReplaceConfig(replaced_id = server_b.server_id, reuse_ip_addr = False, use_host_id = False)
    server_b = await manager.server_add(replace_cfg_b, config=zero_token_cfg)
    
    await manager.decommission_node(server_b.server_id)

    server_b = await manager.server_add(config=zero_token_cfg)

    await manager.rebuild_node(server_b.server_id)

    await manager.server_stop_gracefully(server_b.server_id)
    await manager.remove_node(server_a.server_id, server_b.server_id)

    await manager.server_add(config=zero_token_cfg)
    await manager.server_add(config=normal_cfg)

    # TODO:
    # - maybe add some background requests
    # - test that a new CDC generation isn't created when a joining node is zero-token
    # - test that replacing a token-owning node with a zero-token node (and vice versa) fails (not implemented yet)
    # - test keeping the following invariants in the cluster:
    #   - without tablets: #token_owners > 0 (any topology operation breaking it should fail)
    #   - with tablets, for all keyspaces: #token_owners >= RF

@pytest.mark.asyncio
@pytest.mark.parametrize("tablets_enabled", [False]) # For now it fails with tablets.
async def test_zero_token_nodes_no_replication(manager: ManagerClient, tablets_enabled: bool):
    normal_cfg = {'enable_tablets': tablets_enabled}
    zero_token_cfg = {'enable_tablets': tablets_enabled, 'join_ring': False}

    server_a = await manager.server_add(config=normal_cfg)
    server_b = await manager.server_add(config=zero_token_cfg)
    await manager.server_add(config=normal_cfg)

    cql = manager.get_cql()
    assert cql

    ks_name = unique_name()
    await cql.run_async(f"CREATE KEYSPACE {ks_name} WITH replication = {{'class': 'NetworkTopologyStrategy', 'replication_factor': 2}} AND tablets = {{ 'enabled': {str(tablets_enabled).lower()} }}")
    await cql.run_async(f"CREATE TABLE {ks_name}.tbl (pk int PRIMARY KEY, v int)")
    for i in range(100):
        await cql.run_async(f"INSERT INTO {ks_name}.tbl (pk, v) VALUES ({i}, {i})")

    connection_a = cluster_con([server_a.ip_addr], 9042, False,
                               load_balancing_policy=WhiteListRoundRobinPolicy([server_a.ip_addr])).connect()
    connection_b = cluster_con([server_b.ip_addr], 9042, False,
                               load_balancing_policy=WhiteListRoundRobinPolicy([server_b.ip_addr])).connect()

    select_query = SimpleStatement(f"SELECT * from {ks_name}.tbl", consistency_level=ConsistencyLevel.TWO)

    result1 = [(row.pk, row.v) for row in connection_b.execute(select_query)]
    result1.sort()
    assert result1 == [(i, i) for i in range(100)]

    await manager.server_stop_gracefully(server_b.server_id)

    result2 = [(row.pk, row.v) for row in connection_a.execute(select_query)]
    result2.sort()
    assert result2 == [(i, i) for i in range(100)]

    #result_normal = await cql.run_async("SELECT * FROM system_distributed.cdc_streams_descriptions_v2", host=hosts[0])
    #assert len(result_normal) > 0
