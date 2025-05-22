
def query_scylla_group0_history(session=None, host=None):
    """
    Queries a local table in ScyllaDB and prints the results.  Handles authentication if provided.

    Args:
        session session to connect to ScyllaDB

    Returns:
        newest group0 state id
    """
    try:

        # Construct the query to select all from the table.  Using a prepared statement is generally recommended
        # for performance, but for a simple query like this, it's often fine to use a regular query.  For more
        # complex queries or repeated execution, definitely use prepared statements.
        query = f" SELECT state_id FROM system.group0_history LIMIT 1"
        # In a production environment, handle exceptions more granularly.
        rows = session.execute(query, host=host)

        row = rows.one()
       
        if row:
            return row[0], host.host_id
        else:
            return None

    except Exception as e:
        print(f"Error: {e}")  # Print the exception
    return None

def get_latest_state_ids(session):
    hosts = session.cluster.metadata.all_hosts()
    return [query_scylla_group0_history(session, host) for host in hosts]
