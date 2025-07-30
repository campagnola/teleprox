"""
Create a daemon process -- one that is completely disconnected from this terminal and may live on indefinitely.

Show that we can reconnect to the process and catch logging output from it.
"""
import time, atexit, signal, sys, logging
import teleprox.log


# start a daemon process
daemon = teleprox.start_process('example-daemon', daemon=True)

# Set up proper cleanup handlers
def cleanup_daemon():
    if daemon is not None:
        try:
            print(f"Cleaning up daemon process {daemon.pid}")
            daemon.kill()
        except Exception as e:
            print(f"Error cleaning up daemon: {e}")

def signal_handler(signum, frame):
    print(f"Received signal {signum}, cleaning up...")
    cleanup_daemon()
    sys.exit(0)

# Register cleanup handlers
atexit.register(cleanup_daemon)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

address = daemon.client.address
print(f"Started daemon process {daemon.pid} with address {address}")

# now close and forget our connection to the daemon
daemon.client.close()
print("Closed connection to daemon")


# ---------------------------------------------------------------
# Some time passes, and now we wish to reconnect to the daemon.
# The code below could be run from a totally different process.


client = teleprox.RPCClient.get_client(address=address)
new_pid = client._import('os').getpid()  # just to prove it's the same daemon
print(f"Reconnected to daemon process at {address} (pid {new_pid})")

print("Connecting logging from daemon to this process..")
# set up logging to console and a log server in this process
teleprox.log.basic_config(log_level='WARNING', exceptions=False)
log_addr = teleprox.log.get_logger_address()

# direct the daemon to send log messages to this process
client._import('teleprox.log').set_logger_address(log_addr)

# create a log message in the daemon process
client._import('logging').warning("Hello from the daemon!")

time.sleep(1)  # wait for all messages to be processed before exiting
