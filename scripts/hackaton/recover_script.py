import argparse


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start a recover procedure")
    parser.add_argument("--node", action="store", required=True,help="Provide a node to connect to")
    args = parser.parse_args()


