#
# Copyright (C) 2025-present ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import asyncio
import logging
import time
import pytest

from test.pylib.manager_client import ManagerClient
from test.pylib.util import wait_for_cql_and_get_hosts
from test.topology.util import check_system_topology_and_cdc_generations_v3_consistency, \
    check_token_ring_and_group0_consistency, delete_raft_data, reconnect_driver, wait_for_cdc_generations_publishing

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_raft_recovery_during_join(manager: ManagerClient):
    """
    TODO: comment
    """
    coordinator = await manager.server_add()
    servers = [coordinator] + await manager.servers_add(4)
    live_servers = servers[:2]
    dead_servers = servers[2:]

    coordinator_log = await manager.server_open_log(coordinator.server_id)

    await manager.api.enable_injection(coordinator.ip_addr, 'delay_node_bootstrap', one_shot=False)

    failed_server = await manager.server_add(start=False, config={
            'error_injections_at_startup': ['crash_before_topology_request_completion']})
    task = asyncio.create_task(manager.server_start(failed_server.server_id,
                               expected_error='Crashed in stop_before_topology_request_completion'))

    await coordinator_log.wait_for("delay_node_bootstrap: waiting for message")

    await manager.api.message_injection(failed_server.ip_addr, 'crash_before_topology_request_completion')
    await task
    dead_servers.append(failed_server)

    await manager.api.message_injection(coordinator.ip_addr, 'delay_node_bootstrap')

    for srv in dead_servers:
        await manager.server_stop(server_id=srv.server_id)

    cql, hosts = await manager.get_ready_cql(live_servers)

    for h in hosts:
        await delete_raft_data(cql, h)
        await cql.run_async('TRUNCATE TABLE system.raft', host=h)
        await cql.run_async(
            f"UPDATE system.scylla_local SET value = '{str(live_servers[0].ip_addr)}' WHERE key = 'new_leader_ip'",
            host=h)

    for srv in live_servers:
        await manager.server_restart(server_id=srv.server_id)

    cql = await reconnect_driver(manager)
    hosts = await wait_for_cql_and_get_hosts(cql, live_servers, time.time() + 60)

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
