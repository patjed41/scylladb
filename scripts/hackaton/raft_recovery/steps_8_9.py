import subprocess
import time

from .ssh_helper import create_ssh_client

KILL_TEMPLATE = 'PROC="%s"; PIDS=$(pgrep -f "$PROC"); [ -n "$PIDS" ] && kill $PIDS && while kill -0 $PIDS 2>/dev/null; do sleep 1; done && echo "Process $PROC terminated"'
KILL_SCYLLA = KILL_TEMPLATE % 'scylla'
KILL_ENTRYPOINT = KILL_TEMPLATE % 'docker-entrypoint.py'
START_SCYLLA = 'nohup python3 /docker-entrypoint.py --seeds=scylla-node1 --smp 1 --memory 750M --overprovisioned 1 --api-address 0.0.0.0 </dev/null >/dev/null 2>&1 & disown'
# START_SCYLLA = 'exec /usr/bin/scylla --log-to-syslog 1 --log-to-stdout 0 --default-log-level info --network-stack posix --developer-mode=1 --memory 750M --smp 1 --overprovisioned --listen-address 172.18.0.2 --rpc-address 172.18.0.2 --seed-provider-parameters seeds=scylla-node1 --api-address 0.0.0.0 --alternator-address 172.18.0.2 --blocked-reactor-notify-ms 999999999'

def execute_command(ssh, command):
    stdin, stdout, stderr = ssh.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        print(f"Command failed with exit status {exit_status}")
        print(f"Error: {stderr.read().decode()}")
        raise Exception(f"Command failed: {command}")

def wait_for_node_to_start(node_ip):
    """
    Waits for a ScyllaDB node to start by running a CQL query using cqlsh locally.

    Args:
        node_ip (str): IP address of the node to check.

    Returns:
        bool: True if the node started successfully, False otherwise.
    """
    print(f"Waiting for node {node_ip} to start...")
    for _ in range(120):  # Retry for up to 30 seconds
        try:
            result = subprocess.run(
                ["/home/xtrey/projects/scylladb/tools/cqlsh/bin/cqlsh.py", node_ip, "-e", "SELECT * FROM system.topology;"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            if result.returncode == 0:
                print(f"Node {node_ip} is alive.")
                return True
        except subprocess.CalledProcessError:
            pass
        time.sleep(1)
    print(f"Node {node_ip} failed to start within the timeout period.")
    return False


def restart_scylla_in_recovery_mode(nodes, recovery_leader_id):
    """
    Stops ScyllaDB on the given nodes, adds a recovery.yaml file with a config parameter
    recovery_leader=<recovery_leader_id>, starts the leader node first, waits for it to start,
    and then starts the other nodes.

    Args:
        nodes (list): List of SimpleNamespace objects containing node information (status, node_id, ip).
        recovery_leader_id (str): Recovery leader ID to be added as a config parameter.
    """
    # Determine the leader node IP based on the recovery_leader_id
    leader_node = next(
        (node for node in nodes if node.host_id == recovery_leader_id), None)
    if not leader_node:
        print(
            f"Leader node with ID {recovery_leader_id} not found in the nodes list.")
        return
    leader_ip = leader_node.ip

    for node in nodes:
        ssh = create_ssh_client(ip=node.ip, ssh_user="root")
        try:
            print(
                f"Adding recovery.yaml file on node {node.ip}...")
            recovery_yaml_content = f"recovery_leader: {recovery_leader_id}\n"
            execute_command(ssh,
                f"echo '{recovery_yaml_content}' > /etc/scylla.d/recovery.yaml"
            )
        except Exception as e:
            print(
                f"Error adding recovery.yaml on node {node.ip}: {e}")
            return

    try:
        ssh = create_ssh_client(ip=leader_ip, ssh_user="root")
        print(f"Stopping ScyllaDB on leader node {leader_ip}...")
        ssh.exec_command(KILL_ENTRYPOINT)
        time.sleep(5)
        print(f"Starting ScyllaDB on leader node {leader_ip}...")
        execute_command(ssh,  START_SCYLLA)
        if not wait_for_node_to_start(leader_ip):
            print(f"Leader node {leader_ip} failed to start.")
            return
    except Exception as e:
        print(f"Error starting leader node {leader_ip}: {e}")
        return

    for node in nodes:
        if node.ip == leader_ip:
            continue
        try:
            ssh = create_ssh_client(ip=node.ip, ssh_user="root")
            print(f"Stopping ScyllaDB on node {node.ip}...")
            ssh.exec_command(KILL_ENTRYPOINT)
            print(f"Starting ScyllaDB on node {node.ip}...")
            execute_command(ssh, START_SCYLLA)
            if not wait_for_node_to_start(node.ip):
                print(f"Node {node.ip} failed to start.")
        except Exception as e:
            print(
                f"ru{node.ip}: {e}")
            continue

    # Verify all nodes are alive
    for node in nodes:
        if node.ip == leader_ip:
            continue

        if not wait_for_node_to_start(node.ip):
            print(f"Node {node.ip} failed to start.")
