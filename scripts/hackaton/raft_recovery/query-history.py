from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider

def query_scylla_group0_history(contact_point, username=None, password=None):
    """
    Queries a local table in ScyllaDB and prints the results.  Handles authentication if provided.

    Args:
        contact_point: A contact point (IP addresses or hostnames) for the ScyllaDB node.
        username (str, optional): The username for authentication. Defaults to None.
        password (str, optional): The password for authentication. Defaults to None.

    Returns:
        newest group0 state id
    """
    cluster = None
    session = None
    try:
        # Configure authentication if username and password are provided
        if username and password:
            auth_provider = PlainTextAuthProvider(username=username, password=password)
            cluster = Cluster(contact_points=contact_points, auth_provider=auth_provider)
        else:
            cluster = Cluster(contact_points=contact_points)  # Connect without authentication

        session = cluster.connect("system")  # Connect to the specified keyspace

        # Construct the query to select all from the table.  Using a prepared statement is generally recommended
        # for performance, but for a simple query like this, it's often fine to use a regular query.  For more
        # complex queries or repeated execution, definitely use prepared statements.
        query = f" SELECT state_id FROM system.group0_history LIMIT 1"
        # In a production environment, handle exceptions more granularly.
        rows = session.execute(query)

        row = rows.one()
       
        if row:
            return row[0]
        else:
            return None

    except Exception as e:
        print(f"Error: {e}")  # Print the exception
    finally:
        #  Added defensive closing of resources.
        if session:
            session.shutdown()
        if cluster:
            cluster.shutdown()
    return None

def get_latest_state_ids(contact_points):
    return [query_scylla_group0_history(cp) for cp in contact_points]
