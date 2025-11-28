#
# Copyright (C) 2025-present ScyllaDB
#
# SPDX-License-Identifier: LicenseRef-ScyllaDB-Source-Available-1.0
#
import subprocess
from test.cqlpy.util import new_test_keyspace
from test.pylib.manager_client import ManagerClient
from test.pylib.scylla_cluster import gather_safely, ReplaceConfig

import pytest
import logging


@pytest.mark.asyncio
async def test_reproducer_enterprise_5686(manager: ManagerClient):
    """
    1. Start three nodes.
    2. Kill one node.
    3. Ensure the topology coordinator will hang in the left_token_ring handler through an error injection.
    4. Start replacing the killed node, but crash the replacing node before streaming.
    5. Stop the two live nodes.
    6. Ensure the next topology coordinator will hang in the left_token_ring handler again.
    7. Start the stopped nodes.
    8. Request /storage_service/host_id/ on any node and hit "No ip address for {} when one is expected" for the killed
       node.

    Both nodes don't have the Host ID -> IP mapping of the killed node in the system.peers table. They also don't get
    it on restart through gossip. This wouldn't happen if we restarted only one node. The restarting node would get
    the mapping from the other node during shadow round.
    """
    leader, follower, dead_node = await manager.servers_add(3, auto_rack_dc='dc1')
    live_servers = [leader, follower]

    cql, _ = await manager.get_ready_cql([leader])

    await cql.run_async("CREATE KEYSPACE ks WITH replication = {'class': 'NetworkTopologyStrategy', 'replication_factor': 3};")
    await cql.run_async("CREATE TABLE ks.test (pk int PRIMARY KEY, c int) WITH TABLETS = {'min_tablet_count': 4};")

    await manager.server_stop_gracefully(dead_node.server_id)

    """
    leader, follower = await manager.servers_add(2, auto_rack_dc=True)
    live_servers = [leader, follower]
    """

    await manager.api.enable_injection(leader.ip_addr, 'topology_coordinator_pause_in_left_token_ring', one_shot=True)

    # False/True
    replace_cfg = ReplaceConfig(replaced_id=dead_node.server_id, reuse_ip_addr=True, use_host_id=False)
    await manager.server_add(replace_cfg, config={
        'error_injections_at_startup': ['crash_before_streaming']
    }, cmdline=[
        '--logger-log-level', 'debug_error_injection=debug'
    ], property_file=dead_node.property_file(), expected_error='Triggering injection \"crash_before_streaming\"')
    """
    await manager.server_add(config={
        'error_injections_at_startup': ['crash_before_streaming']
    }, cmdline=[
        '--logger-log-level', 'debug_error_injection=debug'
    ], property_file=leader.property_file(), expected_error='Triggering injection \"crash_before_streaming\"')
    """

    exe_path = await manager.server_get_exe(leader.server_id)
    cmd = [exe_path, "nodetool", "status"] + ["--logger-log-level",
                                              "scylla-nodetool=trace",
                                              "-h", leader.ip_addr]
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.split('\n')
    logging.info("NODETOOL STATUS")
    for line in lines:
        logging.info(line)

    await gather_safely(*(manager.server_stop_gracefully(srv.server_id) for srv in live_servers))

    await gather_safely(*(
        manager.server_update_config(
            srv.server_id,
            'error_injections_at_startup',
            ['topology_coordinator_pause_in_left_token_ring']
        ) for srv in live_servers
    ))

    await gather_safely(*(manager.server_start(srv.server_id) for srv in live_servers))

    await manager.api.get_host_id_map(leader.ip_addr)
    await manager.api.get_joining_nodes(leader.ip_addr)
    await manager.api.client.get_json("/storage_service/nodes/leaving", leader.ip_addr)
    result = await manager.api.describe_ring(leader.ip_addr, 'system_distributed')

    def columnar(lst):
        return f"\n    {'\n    '.join([f'{x}' for x in lst])}"

    logging.info(f"NODETOOL DESCRIBE RING: {columnar(result)}")

    #actual_ownerships = await manager.api.get_ownership(leader.ip_addr)
    #logging.info(f"ACTUAL OWNERSHIPS: {columnar(actual_ownerships)}")

    cql, [host] = await manager.get_ready_cql([leader])
    result = await manager.get_cql().run_async("SELECT * FROM system.cluster_status", host=host)
    logging.info(f"CLUSTER STATUS: {columnar(result)}")

    #result = await manager.api.client.get_json("/storage_proxy/schema_versions", leader.ip_addr)
    #logging.info(f"SCHEMA VERSIONS: {columnar(result)}")

    result = await manager.api.tokens_endpoint(leader.ip_addr, "ks", "test")
    logging.info(f"/storage_service/tokens_endpoint FOR TABLETS: {columnar(result)}")

    result = await manager.api.client.get_json("/storage_service/ownership/system_distributed", leader.ip_addr)
    logging.info(f"/storage_service/ownership/system_distributed: {columnar(result)}")

    result = await manager.api.client.get_json("/storage_service/range_to_endpoint_map/system_distributed", leader.ip_addr)
    logging.info(f"/storage_service/range_to_endpoint_map/system_distributed: {columnar(result)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.split('\n')
    logging.info("NODETOOL STATUS2")
    for line in lines:
        logging.info(line)

    cmd = [exe_path, "nodetool", "ring"] + ["--logger-log-level",
                                            "scylla-nodetool=trace",
                                            "-h", leader.ip_addr]
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.split('\n')
    logging.info("NODETOOL RING")
    for line in lines:
        logging.info(line)

    assert False
