#
# Copyright (C) 2025-present ScyllaDB
#
# SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.0
#
import asyncio
import logging
import pytest

from test.cluster.conftest import cluster_con
from test.pylib.internal_types import ServerInfo
from test.pylib.manager_client import ManagerClient
from test.pylib.rest_client import read_barrier
from test.pylib.scylla_cluster import ReplaceConfig
from test.cluster.util import check_token_ring_and_group0_consistency, delete_discovery_state_and_group0_id, \
        reconnect_driver, delete_raft_group_data, reconnect_driver

from cassandra.connection import UnixSocketEndPoint
from cassandra.policies import WhiteListRoundRobinPolicy


@pytest.mark.asyncio
async def test_raft_recovery_leader_dead(manager: ManagerClient):
    """
    TODO:
    - doc string
    - nightly
    """
    # Workaround for https://github.com/scylladb/scylladb/issues/25163.
    cfg = {'tablet_load_stats_refresh_interval_in_seconds': 1}

    # Add servers to dc2 first, so 3 out of 5 voters will be there.
    logging.info('Adding servers that will be killed to dc2')
    dead_servers = await manager.servers_add(3, config=cfg, auto_rack_dc="dc2")
    logging.info('Adding servers that will survive majority the first majority loss to dc1')
    live_servers = await manager.servers_add(3, config=cfg, auto_rack_dc="dc1")
    logging.info(f'Servers to survive the first majority loss: {live_servers}, servers to be killed: {dead_servers}')

    logging.info(f'Killing {dead_servers}')
    await asyncio.gather(*(manager.server_stop(server_id=srv.server_id) for srv in dead_servers))

    logging.info('Checking that group 0 has no majority')
    with pytest.raises(Exception, match="raft operation \\[read_barrier\\] timed out"):
        await read_barrier(manager.api, live_servers[0].ip_addr, timeout=2)

    logging.info('Starting the recovery procedure')

    logging.info(f'Restarting {live_servers}')
    await manager.rolling_restart(live_servers)

    await reconnect_driver(manager)
    cql, hosts = await manager.get_ready_cql(live_servers)

    first_group0_id = (await cql.run_async(
            "SELECT value FROM system.scylla_local WHERE key = 'raft_group0_id'"))[0].value

    logging.info(f'Deleting the persistent discovery state and group 0 ID on {live_servers}')
    for h in hosts:
        await delete_discovery_state_and_group0_id(cql, h)

    # TODO: find_recovery_leader_candidate
    recovery_leader_id = await manager.get_host_id(live_servers[0].server_id)

    async def set_recovery_leader(srv: ServerInfo):
        nonlocal recovery_leader_id
        await manager.server_update_config(srv.server_id, 'recovery_leader', recovery_leader_id)

    logging.info(f'Restarting {live_servers[:2]} with recovery leader {live_servers[0]}')
    await manager.rolling_restart(live_servers[:2], with_down=set_recovery_leader)

    logging.info(f'Killing recovery leader {live_servers[0]}')
    await manager.server_stop(server_id=live_servers[0].server_id)
    dead_servers.append(live_servers[0])
    live_servers = live_servers[1:]

    logging.info('Checking that the new group 0 has no majority')
    with pytest.raises(Exception, match="raft operation \\[read_barrier\\] timed out"):
        await read_barrier(manager.api, live_servers[0].ip_addr, timeout=2)

    logging.info(f'Trying to restart {live_servers[1]} with recovery leader {live_servers[0]}')
    await manager.server_stop_gracefully(server_id=live_servers[1].server_id)
    await manager.server_update_config(live_servers[1].server_id, 'recovery_leader', recovery_leader_id)
    start_task = asyncio.create_task(manager.server_start(live_servers[1].server_id))

    log_file = await manager.server_open_log(live_servers[1].server_id)
    logging.info(f'Waiting for {live_servers[1]} to hang during the group 0 discovery')
    await log_file.wait_for('Performing Raft-based recovery procedure with recovery leader', timeout=60)
    with pytest.raises(TimeoutError):
        await log_file.wait_for('Raft-based recovery procedure - found group 0 with ID', timeout=2)
    # await asyncio.sleep(5)  # remove this
    start_task.cancel()

    logging.info(f'Stopping {live_servers[1]}')
    await manager.server_stop_gracefully(server_id=live_servers[1].server_id)

    logging.info('Restarting the recovery procedure')

    # TODO: why we don't need restarts here
    #logging.info(f'Restarting {live_servers[0]}')
    #await manager.server_restart(live_servers[0].server_id)

    await reconnect_driver(manager)
    cql, [host] = await manager.get_ready_cql(live_servers[:1])

    second_group0_id = (await cql.run_async(
            "SELECT value FROM system.scylla_local WHERE key = 'raft_group0_id'", host=host))[0].value

    # We need to start live_servers[1] to delete the persistent discovery state and group 0 ID below. However, this
    # node cannot restart normally because the second group 0 has no majority. The maintenance mode is the only option.
    logging.info(f'Starting {live_servers[1]} in the maintenance mode')
    await manager.server_update_config(live_servers[1].server_id, 'maintenance_mode', 'true')
    await manager.server_start(live_servers[1].server_id)

    socket_endpoint = UnixSocketEndPoint(await manager.server_get_maintenance_socket_path(live_servers[1].server_id))
    maintenance_cluster = cluster_con([socket_endpoint],
                                      load_balancing_policy=WhiteListRoundRobinPolicy([socket_endpoint]))
    maintenance_cql = maintenance_cluster.connect()

    logging.info(f'Deleting the persistent discovery state and group 0 ID on {live_servers}')
    await delete_discovery_state_and_group0_id(cql, host)
    await delete_discovery_state_and_group0_id(maintenance_cql, maintenance_cql.hosts[0])
    maintenance_cluster.shutdown()

    logging.info(f'Disabling maintenance mode on {live_servers[1]}')
    await manager.server_update_config(live_servers[1].server_id, 'maintenance_mode', 'false')

    logging.info(f'Stopping {live_servers[1]}')
    await manager.server_stop_gracefully(live_servers[1].server_id)

    # The new recovery leader must be a member of the second group 0. Since this group has only one member, the only
    # member must be the correct choice.
    recovery_leader_id = await manager.get_host_id(live_servers[0].server_id)

    # We cannot perform a normal rolling restart with the new recovery leader because we cannot start live_servers[1]
    # first. This node cannot start with the old recovery leader set because it will hang again in the group 0
    # discovery. It also must not restart with no recovery leader set as it would create a new group 0 and histories of
    # two group 0 could diverge. We don't have a safe way to recover from such a state.

    logging.info(f'Restarting {live_servers} with recovery leader {live_servers[0]}')
    await manager.rolling_restart(live_servers, with_down=set_recovery_leader, wait_for_cql=False)

    logging.info(f'Replacing {dead_servers}')
    for i, being_replaced in enumerate(dead_servers):
        replace_cfg = ReplaceConfig(replaced_id=being_replaced.server_id, reuse_ip_addr=False, use_host_id=True,
                                    ignore_dead_nodes=[dead_srv.ip_addr for dead_srv in dead_servers[i + 1:]])
        await manager.server_add(replace_cfg=replace_cfg, config=cfg, property_file=being_replaced.property_file())

    logging.info(f'Unsetting the recovery_leader config option on {live_servers}')
    for srv in live_servers:
        await manager.server_remove_config_option(srv.server_id, 'recovery_leader')

    await reconnect_driver(manager)
    cql, hosts = await manager.get_ready_cql(live_servers)

    logging.info(f'Deleting persistent data of groups {first_group0_id} and {second_group0_id} on {live_servers}')
    for h in hosts:
        await delete_raft_group_data(first_group0_id, cql, h)
        await delete_raft_group_data(second_group0_id, cql, h)

    logging.info('Checking the token ring and group 0 consistency after the recovery procedure')
    await check_token_ring_and_group0_consistency(manager)

    logging.info('Adding a new server to dc1')
    new_server = await manager.server_add(config=cfg, property_file={"dc": "dc1", "rack": "rack1"})

    logging.info(f'Checking the token ring and group 0 consistency after adding {new_server}')
    await check_token_ring_and_group0_consistency(manager)
