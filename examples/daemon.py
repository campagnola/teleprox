"""
Create a daemon process -- one that is completely disconnected from this terminal and may live on indefinitely.

Show that we can reconnect to the process and catch logging output from it.
"""
import teleprox
import logging

# start a daemon process
daemon = teleprox.start_process('daemon', daemon=False)

address = daemon.client.address
pid = daemon.client._import('os').getpid()
print(f"Started daemon process {pid} with address {address}")

# create a log sender in the remote process
remote_log = daemon.client._import('teleprox.log')
remote_sender = remote_log.LogSender(logger='')  # prepare to send all messages from the root logger to a log server
daemon.client['log_sender'] = remote_sender  # publish a reference to the sender so we can access it easily later on
# request to log exceptions in the daemon
remote_log.log_exceptions()

# now close and forget our connection to the daemon
daemon.client.close()
del daemon
print("Closed connection to daemon")

# .. some time passes, and now we wish to reconnect to the daemon

client = teleprox.RPCClient.get_client(address=address)
new_pid = client._import('os').getpid()
print(f"Reconnected to daemon process at {address} (pid {new_pid})")

print("Connecting logging from daemon to this process..")
# set up logging in this process
logger = logging.getLogger('')
logger.setLevel(logging.INFO)
# create a handler to print log messages to the console
handler = teleprox.log.RPCLogHandler()  
# attach to the root logger so we get messages from both processes
logger.addHandler(handler)
# create a log server to receive messages from the daemon
log_server = teleprox.log.LogServer(logger='daemon')

# connect the remote log sender to our log server
client['log_sender'].connect(log_server.address)

# log a message in the daemon process
client._import('logging').info("Hello from the daemon!")

# finally, close the daemon process
client.close_server()


