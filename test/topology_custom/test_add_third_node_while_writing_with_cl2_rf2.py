import pytest
import logging
import time
import asyncio

from cassandra.cluster import ConsistencyLevel, Session
from cassandra.policies import WhiteListRoundRobinPolicy
from cassandra.query import SimpleStatement

from test.pylib.manager_client import ManagerClient
from test.pylib.scylla_cluster import ReplaceConfig
from test.pylib.util import unique_name, wait_for_cql_and_get_hosts
from test.topology.conftest import cluster_con


@pytest.mark.asyncio
async def test_add_third_node_while_writing_with_cl2_rf2(manager: ManagerClient):
    cmdline = [
        '--logger-log-level', 'storage_proxy=trace',
        '--logger-log-level', 'cql_server=trace',
        '--logger-log-level', 'query_processor=trace',
        ]
    logging.info('Adding two initial servers')
    servers = await manager.servers_add(2, cmdline=cmdline)

    await wait_for_cql_and_get_hosts(manager.cql, servers, time.time() + 60)
    finish_writes = await start_writes(manager.cql, 2)

    logging.info('Adding the third server')
    await manager.server_add(cmdline=cmdline)

    logging.info('Checking results of the background writes')
    await finish_writes()

async def start_writes(cql: Session, rf: int, concurrency: int = 3):
    logging.info(f"Starting to asynchronously write, concurrency = {concurrency}")

    stop_event = asyncio.Event()

    ks_name = unique_name()
    await cql.run_async(f"CREATE KEYSPACE {ks_name} WITH replication = {{'class': 'NetworkTopologyStrategy', 'replication_factor': {rf}}}")
    await cql.run_async(f"USE {ks_name}")
    await cql.run_async(f"CREATE TABLE tbl (pk int PRIMARY KEY, v int)")

    # In the test we only care about whether operations report success or not
    # and whether they trigger errors in the nodes' logs. Inserting the same
    # value repeatedly is enough for our purposes.
    stmt = SimpleStatement("INSERT INTO tbl (pk, v) VALUES (0, 0)", consistency_level=ConsistencyLevel.TWO)

    async def do_writes(worker_id: int):
        write_count = 0
        while not stop_event.is_set():
            start_time = time.time()
            try:
                await cql.run_async(stmt)
                write_count += 1
            except Exception as e:
                logging.error(f"Write started {time.time() - start_time}s ago failed: {e}")
                raise
        logging.info(f"Worker #{worker_id} did {write_count} successful writes")

    tasks = [asyncio.create_task(do_writes(worker_id)) for worker_id in range(concurrency)]

    async def finish():
        logging.info("Stopping write workers")
        stop_event.set()
        await asyncio.gather(*tasks)

    return finish
