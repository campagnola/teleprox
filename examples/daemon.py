"""
Create a daemon process -- one that is completely disconnected from this terminal and may live on indefinitely.

Show that we can reconnect to the process and catch logging output from it.
"""
import time
import teleprox
import logging

# start a daemon process
daemon = teleprox.start_process('example-daemon', daemon=True)

address = daemon.client.address
print(f"Started daemon process {daemon.pid} with address {address}")

# now close and forget our connection to the daemon
daemon.client.close()
del daemon
print("Closed connection to daemon")


# ---------------------------------------------------------------
# Some time passes, and now we wish to reconnect to the daemon.
# The code below could be run from a totally different process.


client = teleprox.RPCClient.get_client(address=address)
new_pid = client._import('os').getpid()  # just to prove it's the same daemon
print(f"Reconnected to daemon process at {address} (pid {new_pid})")

print("Connecting logging from daemon to this process..")
# set up logging to console in this process
teleprox.log.basic_config(log_level='INFO')

# set up a log server to receive log messages from the daemon
teleprox.log.start_log_server('')
log_addr = teleprox.log.get_logger_address()

# set up logging in the daemon to send messages to this process
client._import('teleprox.log').set_logger_address(log_addr)
client._import('logging').getLogger().setLevel('INFO')

# create a log message in the daemon process
client._import('logging').info("Hello from the daemon!")

# # finally, close the daemon process
# client.close_server()


# time.sleep(1)  # wait for all messages to be processed before exiting
