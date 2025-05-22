import uuid

def find_newest_timeuuid(timeuids):
    """
    Finds the newest TimeUUID from a list of TimeUUIDs.

    Args:
        timeuids: A list of TimeUUID strings.

    Returns:
        The newest TimeUUID string, or None if the list is empty.
    """
    if not timeuids:
        return None

    newest_timeuuid = None
    newest_timestamp = -1

    for uuid_host_pair in timeuids:
        try:
            # Parse the TimeUUID string into a UUID object
            # tu_obj = uuid.UUID(str(uuid_host_pair[0]))
            tu_obj = uuid_host_pair[0]

            # Check if it's a TimeUUID (version 1)
            # if tu_obj.version == 1:
                # Extract the timestamp from the TimeUUID
                # TimeUUIDs encode the timestamp in the first 60 bits
                # The timestamp is in 100-nanosecond intervals since
                # 1582-10-15 00:00:00 UTC (Gregorian calendar start).
            timestamp = tu_obj.time

            if timestamp > newest_timestamp:
                newest_timestamp = timestamp
                newest_timeuuid = uuid_host_pair
            # else:
            #     print(f"Warning: '{uuid_host_pair}' is not a version 1 (Time) UUID and will be skipped.")
        except ValueError:
            print(f"Warning: Invalid UUID string '{uuid_host_pair}' will be skipped.")

    return newest_timeuuid

