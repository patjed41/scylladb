#
# Copyright (C) 2022-present ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
"""
Test replacing node in different scenarios
"""
import asyncio
import time
from test.pylib.scylla_cluster import ReplaceConfig
from test.pylib.manager_client import ManagerClient
from test.topology.util import wait_for_token_ring_and_group0_consistency
import pytest


@pytest.mark.asyncio
async def test_replace_different_ip(manager: ManagerClient) -> None:
    """Replace an existing node with new node using a different IP address"""
    servers = await manager.running_servers()
    await manager.server_stop(servers[0].server_id)
    replace_cfg = ReplaceConfig(replaced_id = servers[0].server_id, reuse_ip_addr = False, use_host_id = False)
    await manager.server_add(replace_cfg)
    await wait_for_token_ring_and_group0_consistency(manager, time.time() + 30)

@pytest.mark.asyncio
async def test_replace_different_ip_using_host_id(manager: ManagerClient) -> None:
    """Replace an existing node with new node reusing the replaced node host id"""
    servers = await manager.running_servers()
    await manager.server_stop(servers[0].server_id)
    replace_cfg = ReplaceConfig(replaced_id = servers[0].server_id, reuse_ip_addr = False, use_host_id = True)
    await manager.server_add(replace_cfg)
    await wait_for_token_ring_and_group0_consistency(manager, time.time() + 30)

@pytest.mark.asyncio
async def test_replace_reuse_ip(manager: ManagerClient) -> None:
    """Replace an existing node with new node using the same IP address"""
    servers = await manager.running_servers()
    await manager.server_stop(servers[0].server_id)
    replace_cfg = ReplaceConfig(replaced_id = servers[0].server_id, reuse_ip_addr = True, use_host_id = False)
    await manager.server_add(replace_cfg)
    await wait_for_token_ring_and_group0_consistency(manager, time.time() + 30)

@pytest.mark.asyncio
async def test_replace_reuse_ip_using_host_id(manager: ManagerClient) -> None:
    """Replace an existing node with new node using the same IP address and same host id"""
    servers = await manager.running_servers()
    await manager.server_stop(servers[0].server_id)
    replace_cfg = ReplaceConfig(replaced_id = servers[0].server_id, reuse_ip_addr = True, use_host_id = True)
    await manager.server_add(replace_cfg)
    await wait_for_token_ring_and_group0_consistency(manager, time.time() + 30)

@pytest.mark.asyncio
async def test_replacing_alive_node_fails(manager: ManagerClient) -> None:
    """Try replacing an alive node and check that it fails"""
    servers = await manager.running_servers()
    await asyncio.gather(*(manager.server_sees_others(srv.server_id, len(servers) - 1) for srv in servers))

    # We test for every server because we expect a different error depending on
    # whether we try to replace the topology coordinator. We want to test both cases.
    # Both errors contain the expected string below.
    for srv in servers:
        replace_cfg = ReplaceConfig(replaced_id = srv.server_id, reuse_ip_addr = False, use_host_id = False)
        await manager.server_add(replace_cfg=replace_cfg,
                                 expected_error="the topology coordinator rejected request to join the cluster")
