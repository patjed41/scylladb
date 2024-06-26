#
# Copyright (C) 2024-present ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import pytest
import logging

from cassandra.cluster import ConsistencyLevel
from cassandra.policies import WhiteListRoundRobinPolicy
from cassandra.query import SimpleStatement

from test.pylib.manager_client import ManagerClient
from test.pylib.util import unique_name
from test.topology.conftest import cluster_con


@pytest.mark.asyncio
@pytest.mark.parametrize('tablets_enabled', [True, False])
@pytest.mark.parametrize('replication_strategy', ['EverywhereStrategy', 'SimpleStrategy', 'NetworkTopologyStrategy'])
async def test_zero_token_nodes_no_replication(manager: ManagerClient, replication_strategy: str, tablets_enabled: bool):
    # Test that zero-token nodes do not replicate data in all replication strategies different from local with and
    # without tablets.
    if tablets_enabled and replication_strategy != 'NetworkTopologyStrategy':
        pytest.skip(f'Tablets do not support {replication_strategy}')

    normal_cfg = {'enable_tablets': tablets_enabled}
    zero_token_cfg = {'enable_tablets': tablets_enabled, 'join_ring': False}

    logging.info('Adding the first server')
    server_a = await manager.server_add(config=normal_cfg)
    logging.info('Adding the second server as zero-token')
    server_b = await manager.server_add(config=zero_token_cfg)
    logging.info('Adding the third server')
    await manager.server_add(config=normal_cfg)

    logging.info(f'Initiating connections to {server_a} and {server_b}')
    cql_a = cluster_con([server_a.ip_addr], 9042, False,
                        load_balancing_policy=WhiteListRoundRobinPolicy([server_a.ip_addr])).connect()
    cql_b = cluster_con([server_b.ip_addr], 9042, False,
                        load_balancing_policy=WhiteListRoundRobinPolicy([server_b.ip_addr])).connect()

    ks_name = unique_name()
    await cql_a.run_async(f"CREATE KEYSPACE {ks_name} WITH replication = {{'class': '{replication_strategy}', 'replication_factor': 2}} AND tablets = {{ 'enabled': {str(tablets_enabled).lower()} }}")
    await cql_a.run_async(f'CREATE TABLE {ks_name}.tbl (pk int PRIMARY KEY, v int)')
    for i in range(100):
        await cql_a.run_async(f'INSERT INTO {ks_name}.tbl (pk, v) VALUES ({i}, {i})')

    select_query = SimpleStatement(f'SELECT * FROM {ks_name}.tbl', consistency_level=ConsistencyLevel.ALL)

    result1 = [(row.pk, row.v) for row in await cql_b.run_async(select_query)]
    result1.sort()
    assert result1 == [(i, i) for i in range(100)]

    logging.info(f'Stopping {server_b}')
    await manager.server_stop_gracefully(server_b.server_id)

    result2 = [(row.pk, row.v) for row in await cql_a.run_async(select_query)]
    result2.sort()
    assert result2 == [(i, i) for i in range(100)]
