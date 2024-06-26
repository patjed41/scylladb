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

logger = logging.getLogger(__name__)

@pytest.mark.asyncio
@pytest.mark.parametrize("tablets_enabled", [True, False])
async def test_replication_factor_auto_expansion(manager: ManagerClient, tablets_enabled: bool):
    cfg_dc1 = {"endpoint_snitch": "GossipingPropertyFileSnitch", "enable_tablets": tablets_enabled}
    cfg_dc2 = {"endpoint_snitch": "GossipingPropertyFileSnitch", "enable_tablets": tablets_enabled, "join_ring": False}
    property_file_dc1 = {"dc": "dc1", "rack": "rack"}
    property_file_dc2 = {"dc": "dc2_arbiter", "rack": "rack"}
    servers = await manager.servers_add(2, config=cfg_dc1, property_file=property_file_dc1)
    servers += await manager.servers_add(2, config=cfg_dc2, property_file=property_file_dc2)

    # This check doesn't belong thematically to this test. Maybe I'll move it somewhere else later.
    await manager.server_add(config=cfg_dc1, property_file=property_file_dc2,
                             expected_error="Cannot start with join_ring=true because the node belongs to the arbiter DC dc2_arbiter")

    cql = manager.get_cql()
    assert cql

    ks_name = unique_name()
    await cql.run_async(f"CREATE KEYSPACE {ks_name} WITH replication = {{'class': 'NetworkTopologyStrategy', 'replication_factor': 2}} AND tablets = {{ 'enabled': {str(tablets_enabled).lower()} }}")
    await cql.run_async(f"CREATE TABLE {ks_name}.tbl (pk int PRIMARY KEY, v int)")
    await cql.run_async(f"INSERT INTO {ks_name}.tbl (pk, v) VALUES (1, 2)")

    dc1_connection = cluster_con([servers[0].ip_addr], 9042, False,
                                 load_balancing_policy=WhiteListRoundRobinPolicy([servers[0].ip_addr])).connect()
    dc2_connection = cluster_con([servers[2].ip_addr], 9042, False,
                                 load_balancing_policy=WhiteListRoundRobinPolicy([servers[2].ip_addr])).connect()
    
    select_query = SimpleStatement(f"SELECT * from {ks_name}.tbl", consistency_level=ConsistencyLevel.LOCAL_QUORUM)

    dc1_result = list(dc1_connection.execute(select_query).one())
    dc2_result = dc2_connection.execute(select_query).one()
    assert dc1_result == [1, 2]
    assert dc2_result is None

