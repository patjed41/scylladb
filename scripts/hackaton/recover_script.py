#!/usr/bin/env python3

import argparse
from raft_recovery.ssh_helper import create_ssh_client

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start a recover procedure")
    parser.add_argument("--node", action="store", required=True, help="Provide a node to connect to")
    parser.add_argument("--user", action="store", required=True, help="SSH username to use for connection")
    parser.add_argument("--key", action="store", required=False, help="Path to SSH private key file (optional)")
    args = parser.parse_args()

    # Initialize SSH client session using the provided node IP, user, and key path (if provided)
    ssh = create_ssh_client(args.node, ssh_user=args.user, ssh_key_path=args.key)
