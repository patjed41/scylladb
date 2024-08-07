Reset Authenticator Password
============================

This procedure describes what to do when a user loses his password and can not reset it with a superuser role. 
The procedure requires cluster downtime and as a result, all auth data is deleted.

Procedure
.........

| 1. Stop ScyllaDB nodes (**Stop all the nodes in the cluster**).

.. code-block:: shell 

   sudo systemctl stop scylla-server

| 2. Remove system tables starting with ``role`` prefix from ``/var/lib/scylla/data/system`` directory.

.. code-block:: shell  

   rm -rf /var/lib/scylla/data/system/role*

| 3. Start ScyllaDB nodes.

.. code-block:: shell 

   sudo systemctl start scylla-server

| 4. Verify that you can log in to your node using ``cqlsh`` command.
| The access is only possible using ScyllaDB superuser.

.. code-block:: cql
 
   cqlsh -u cassandra -p cassandra

| 5. Recreate the users

.. include:: /troubleshooting/_common/ts-return.rst
