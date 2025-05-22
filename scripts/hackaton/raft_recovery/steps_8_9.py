import subprocess
import time


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
                ["cqlsh", "-e", "SELECT * FROM system.topology;"],
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
        nodes (list): List of dictionaries containing node information (status, node_id, node_ip).
        recovery_leader_id (str): Recovery leader ID to be added as a config parameter.
    """
    # Determine the leader node IP based on the recovery_leader_id
    leader_node = next(
        (node for node in nodes if node['node_id'] == recovery_leader_id), None)
    if not leader_node:
        print(
            f"Leader node with ID {recovery_leader_id} not found in the nodes list.")
        return
    leader_ip = leader_node['node_ip']

    for node in nodes:
        try:
            print(f"Stopping ScyllaDB on node {node['node_ip']}...")
            subprocess.run(
                ["ssh", node['node_ip'], "sudo systemctl stop scylla-server"],
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(
                f"Error stopping ScyllaDB on node {node['node_ip']}: {e}")
            return

    for node in nodes:
        try:
            print(
                f"Adding recovery.yaml file on node {node['node_ip']}...")
            recovery_yaml_content = f"recovery_leader: {recovery_leader_id}\n"
            subprocess.run(
                [
                    "ssh", node['node_ip'],
                    f"echo '{recovery_yaml_content}' | sudo tee /scylla.d/recovery.yaml"
                ],
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(
                f"Error adding recovery.yaml on node {node['node_ip']}: {e}")
            return

    try:
        print(f"Starting ScyllaDB on leader node {leader_ip}...")
        subprocess.run(
            ["ssh", leader_ip, "sudo systemctl start scylla-server"],
            check=True
        )
        if not wait_for_node_to_start(leader_ip):
            print(f"Leader node {leader_ip} failed to start.")
            return
    except subprocess.CalledProcessError as e:
        print(f"Error starting leader node {leader_ip}: {e}")
        return

    for node in nodes:
        if node['node_ip'] == leader_ip:
            continue
        try:
            print(f"Starting ScyllaDB on node {node['node_ip']}...")
            subprocess.run(
                ["ssh", node['node_ip'], "sudo systemctl start scylla-server"],
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(
                f"Error starting ScyllaDB on node {node['node_ip']}: {e}")
            continue

    # Verify all nodes are alive
    for node in nodes:
        if node['node_ip'] == leader_ip:
            continue

        if not wait_for_node_to_start(node['node_ip']):
            print(f"Node {node['node_ip']} failed to start.")
