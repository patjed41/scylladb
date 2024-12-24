#
# Copyright (C) 2025-present ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import logging
import time
import pytest

from cassandra.cluster import ConsistencyLevel

from test.pylib.manager_client import ManagerClient
from test.pylib.util import wait_for_cql_and_get_hosts
from test.topology.util import check_system_topology_and_cdc_generations_v3_consistency, \
        check_token_ring_and_group0_consistency, delete_raft_data, reconnect_driver, start_writes, \
        wait_for_cdc_generations_publishing

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_raft_recovery_data_path(manager: ManagerClient):
    """
    TODO: comment
    """
    cfg = {'endpoint_snitch': 'GossipingPropertyFileSnitch', 'enable_tablets': True}
    property_file_dc1 = {'dc': 'dc1', 'rack': 'rack1'}
    property_file_dc2 = {'dc': 'dc2', 'rack': 'rack2'}
    live_servers = await manager.servers_add(3, config=cfg, property_file=property_file_dc1)
    dead_servers = await manager.servers_add(3, config=cfg, property_file=property_file_dc2)

    cql, hosts = await manager.get_ready_cql(live_servers + dead_servers)
    hosts = await wait_for_cql_and_get_hosts(cql, live_servers, time.time() + 60)

    finish_writes = await start_writes(cql, 3, ConsistencyLevel.LOCAL_QUORUM, 10, node_shutdowns=True)

    for srv in dead_servers:
        await manager.server_stop(server_id=srv.server_id)

    for h in hosts:
        await delete_raft_data(cql, h)
        await cql.run_async("TRUNCATE TABLE system.raft", host=h)
        await cql.run_async(
                f"UPDATE system.scylla_local SET value = '{str(live_servers[0].ip_addr)}' WHERE key = 'new_leader_ip'",
                host=h)

    await manager.rolling_restart(live_servers)

    # We must reconnect the driver because we perform a client request below
    # (https://github.com/scylladb/python-driver/issues/295). This also forces us to stop writes.
    await finish_writes()

    await reconnect_driver(manager)
    cql, hosts = await manager.get_ready_cql(live_servers)

    finish_writes = await start_writes(cql, 3, ConsistencyLevel.LOCAL_QUORUM)

    for h in hosts:
        await cql.run_async("DELETE value FROM system.scylla_local WHERE key = 'new_leader_ip'")

    for i, being_removed in enumerate(dead_servers):
        ignored = [dead_srv.ip_addr for dead_srv in dead_servers[i + 1:]]
        initiator = live_servers[i]
        await manager.remove_node(initiator.server_id, being_removed.server_id, ignored)

    await wait_for_cdc_generations_publishing(cql, hosts, time.time() + 60)
    await check_token_ring_and_group0_consistency(manager)
    await check_system_topology_and_cdc_generations_v3_consistency(manager, hosts)

    # Disable load balancer on the topology coordinator node so that an ongoing tablet migration doesn't fail the
    # check_system_topology_and_cdc_generations_v3_consistency call below. global_tablet_token_metadata_barrier can
    # suddenly make fence_version inconsistent among nodes.
    await manager.api.disable_tablet_balancing(live_servers[0].ip_addr)

    new_server = await manager.server_add(config=cfg, property_file=property_file_dc2)

    hosts = await wait_for_cql_and_get_hosts(cql, live_servers + [new_server], time.time() + 60)

    await wait_for_cdc_generations_publishing(cql, hosts, time.time() + 60)
    await check_token_ring_and_group0_consistency(manager)
    await check_system_topology_and_cdc_generations_v3_consistency(manager, hosts)

    await finish_writes()
