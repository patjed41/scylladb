#
# Copyright (C) 2025-present ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
import asyncio
import logging
import time
import pytest

from cassandra.cluster import ConsistencyLevel

from test.pylib.manager_client import ManagerClient
from test.pylib.scylla_cluster import ReplaceConfig
from test.pylib.util import unique_name, wait_for_cql_and_get_hosts
from test.topology.util import check_system_topology_and_cdc_generations_v3_consistency, \
        check_token_ring_and_group0_consistency, delete_discovery_state_and_group0_id, delete_raft_group_data, \
        reconnect_driver, start_writes, wait_for_cdc_generations_publishing

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_dead_nodes_with", ["remove", "replace"])
async def test_raft_recovery_user_data(manager: ManagerClient, remove_dead_nodes_with: str):
    """
    Test that the new Raft recovery procedure works correctly with the user data. It involves testing:
    - client requests during the procedure (mainly availability),
    - removing/replacing dead nodes during the procedure in the presence of client requests and tablets on dead nodes.

    1. Start a cluster with two dcs, dc1 and dc2, containing three nodes each.
    2. Start sending writes with CL=LOCAL_QUORUM to a table RF=3, NetworkTopologyStrategy and tablets.
    3. Kill all nodes from dc3 causing a pemermanent group 0 majority loss.
    4. Run the recovery procedure to recreate group 0 with nodes from dc2 as new members. Writes sent to dc1 should
    continue succeeding since at least two nodes are alive at any point during the recovery procedure (it involves a
    rolling restart), every node in dc1 is a replica (3 nodes, RF=3) and two nodes make a local quorum in dc1.
    5. Remove nodes from dc2 from topology using the standard using remove or replace, depending on the value of
    the remove_dead_nodes_with parameter. For remove, we must do two additional steps to make it work:
    - Mark all dead nodes as permanently dead.
    - Decrease RF of the user keyspace, which uses tablets, to 0.
    6. Add a new node (a sanity check verifying that the cluster is functioning properly).
    7. Stop sending writes.
    """
    cfg = {'endpoint_snitch': 'GossipingPropertyFileSnitch', 'enable_tablets': True}
    property_file_dc1 = {'dc': 'dc1', 'rack': 'rack1'}
    property_file_dc2 = {'dc': 'dc2', 'rack': 'rack2'}

    logging.info('Adding servers that will survive majority loss to dc1')
    live_servers = await manager.servers_add(3, config=cfg, property_file=property_file_dc1)
    logging.info('Adding servers that will be killed to dc2')
    dead_servers = await manager.servers_add(3, config=cfg, property_file=property_file_dc2)
    logging.info(f'Servers to syrvive majority loss: {live_servers}, servers to be killed: {dead_servers}')

    cql, hosts = await manager.get_ready_cql(live_servers + dead_servers)
    hosts = await wait_for_cql_and_get_hosts(cql, live_servers, time.time() + 60)

    first_group0_id = (await cql.run_async(
            "SELECT value FROM system.scylla_local WHERE key = 'raft_group0_id'"))[0].value

    rf: int = 3
    ks_name = unique_name()
    restart_writes, stop_writes = await start_writes(cql, rf, ConsistencyLevel.LOCAL_QUORUM, 5, ks_name, True)

    # Send some writes before we kill nodes.
    logging.info('Sleeping for 1 s')
    await asyncio.sleep(1)

    logging.info(f'Killing {dead_servers}')
    for srv in dead_servers:
        await manager.server_stop(server_id=srv.server_id)

    logging.info('Starting the recovery procedure')

    logging.info(f'Restarting {live_servers}')
    await manager.rolling_restart(live_servers)

    logging.info(f'Deleting the persistent discovery state and group 0 ID on {live_servers}')
    for h in hosts:
        await delete_discovery_state_and_group0_id(cql, h)

    recovery_leader_id = await manager.get_host_id(live_servers[0].server_id)
    logging.info(f'Setting recovery leader to {live_servers[0].server_id} on {live_servers}')
    for srv in live_servers:
        await manager.server_update_config(srv.server_id, 'recovery_leader', recovery_leader_id)

    logging.info(f'Restarting {live_servers}')
    await manager.rolling_restart(live_servers)

    # We stop writes and reconnect the driver because we perform a client request below
    # (https://github.com/scylladb/python-driver/issues/295).
    await stop_writes()

    await reconnect_driver(manager)
    cql, hosts = await manager.get_ready_cql(live_servers)

    await restart_writes(cql)

    if remove_dead_nodes_with == "remove":
        # We must mark dead nodes as permanently dead so that they are ignored in topology commands. Without this step,
        # ALTER KEYSPACE below would fail on the global token metadata barrier.
        # For now, we do not have a specific API to mark nodes as dead so we use a work-around.
        logging.info(f'Marking {dead_servers} as permanently dead')
        await manager.remove_node(live_servers[0].server_id, dead_servers[0].server_id,
                                  [dead_srv.ip_addr for dead_srv in dead_servers[1:]],
                                  expected_error='Removenode failed')

        logging.info(f'Desceasing RF of {ks_name} to 0 in dc2')
        for i in range(1, rf + 1):
            # ALTER KEYSPACE with tablets can decrease RF only by one.
            await cql.run_async(f"""ALTER KEYSPACE {ks_name} WITH replication =
                                    {{'class': 'NetworkTopologyStrategy', 'dc1': {rf}, 'dc2': {rf - i}}}""")

        logging.info(f'Removing {dead_servers}')
        for i, being_removed in enumerate(dead_servers):
            ignored = [dead_srv.ip_addr for dead_srv in dead_servers[i + 1:]]
            initiator = live_servers[i]
            await manager.remove_node(initiator.server_id, being_removed.server_id, ignored)
    else:
        logging.info(f'Replacing {dead_servers}')
        for i, being_replaced in enumerate(dead_servers):
            replace_cfg = ReplaceConfig(replaced_id=being_replaced.server_id, reuse_ip_addr=False, use_host_id=True,
                                        ignore_dead_nodes=[dead_srv.ip_addr for dead_srv in dead_servers[i + 1:]])
            await manager.server_add(replace_cfg=replace_cfg, property_file=property_file_dc2)

    logging.info(f'Unsetting the recovery_leader config on {live_servers}')
    for srv in live_servers:
        await manager.server_update_config(srv.server_id, 'recovery_leader', '')

    logging.info(f'Deleting persistent data of group 0 {first_group0_id} on {live_servers}')
    for h in hosts:
        await delete_raft_group_data(first_group0_id, cql, h)

    logging.info('Performing consistency checks after the recovery procedure')
    await wait_for_cdc_generations_publishing(cql, hosts, time.time() + 60)
    await check_token_ring_and_group0_consistency(manager)
    await check_system_topology_and_cdc_generations_v3_consistency(manager, hosts)

    # Disable load balancer on the topology coordinator node so that an ongoing tablet migration doesn't fail the
    # check_system_topology_and_cdc_generations_v3_consistency call below. global_tablet_token_metadata_barrier can
    # suddenly make fence_version inconsistent among nodes.
    await manager.api.disable_tablet_balancing(live_servers[0].ip_addr)

    logger.info('Adding a new server to dc2')
    new_server = await manager.server_add(config=cfg, property_file=property_file_dc2)

    hosts = await wait_for_cql_and_get_hosts(cql, live_servers + [new_server], time.time() + 60)

    logging.info(f'Performing consistency checks after adding {new_server}')
    await wait_for_cdc_generations_publishing(cql, hosts, time.time() + 60)
    await check_token_ring_and_group0_consistency(manager)
    await check_system_topology_and_cdc_generations_v3_consistency(manager, hosts)

    await stop_writes()