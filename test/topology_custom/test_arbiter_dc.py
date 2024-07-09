#
# Copyright (C) 2024-present ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import pytest

from cassandra import ConsistencyLevel
from cassandra.policies import WhiteListRoundRobinPolicy
from cassandra.query import SimpleStatement
from test.pylib.manager_client import ManagerClient

from test.pylib.util import unique_name
from test.topology.conftest import cluster_con

@pytest.mark.asyncio
@pytest.mark.parametrize('tablets_enabled', [True, False])
async def test_arbiter_dc(manager: ManagerClient, tablets_enabled: bool):
    # Test that:
    # - adding token-owning nodes to an arbiter DC is impossible,
    # - RF auto-expansion works as expected in the case of arbiter DC, that is it assigns RF=0.
    cfg_dc1 = {'endpoint_snitch': 'GossipingPropertyFileSnitch', 'enable_tablets': tablets_enabled}
    cfg_dc2 = {'endpoint_snitch': 'GossipingPropertyFileSnitch', 'enable_tablets': tablets_enabled, 'join_ring': False}
    property_file_dc1 = {'dc': 'dc1', 'rack': 'rack'}
    property_file_dc2 = {'dc': 'dc2__arbiter__', 'rack': 'rack'}
    logging.info('Creating dc1 with 2 token-owning nodes')
    servers = await manager.servers_add(2, config=cfg_dc1, property_file=property_file_dc1)
    logging.info('Creating dc2__arbiter__ with 2 zero-token nodes')
    servers += await manager.servers_add(2, config=cfg_dc2, property_file=property_file_dc2)

    logging.info('Trying to add a token-owning node to dc2__arbiter__')
    await manager.server_add(config=cfg_dc1, property_file=property_file_dc2,
                             expected_error='Cannot start with join_ring=true because the node belongs to the arbiter DC dc2__arbiter__')

    logging.info('Creating connections to dc1 and dc2__arbiter__')
    dc1_cql = cluster_con([servers[0].ip_addr], 9042, False,
                          load_balancing_policy=WhiteListRoundRobinPolicy([servers[0].ip_addr])).connect()
    dc2_cql = cluster_con([servers[2].ip_addr], 9042, False,
                          load_balancing_policy=WhiteListRoundRobinPolicy([servers[2].ip_addr])).connect()

    ks_name = unique_name()
    await dc1_cql.run_async(f"CREATE KEYSPACE {ks_name} WITH replication = {{'class': 'NetworkTopologyStrategy', 'replication_factor': 2}} AND tablets = {{ 'enabled': {str(tablets_enabled).lower()} }}")
    await dc1_cql.run_async(f'CREATE TABLE {ks_name}.tbl (pk int PRIMARY KEY, v int)')
    await dc1_cql.run_async(f'INSERT INTO {ks_name}.tbl (pk, v) VALUES (1, 2)')

    select_query = SimpleStatement(f'SELECT * FROM {ks_name}.tbl', consistency_level=ConsistencyLevel.LOCAL_QUORUM)

    dc1_result = list((await dc1_cql.run_async(select_query))[0])
    dc2_result = await dc2_cql.run_async(select_query)
    assert dc1_result == [1, 2]
    assert dc2_result == []
