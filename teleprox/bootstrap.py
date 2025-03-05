"""Script for bootstrapping new processes created with start_process.
"""
import os
import sys
import argparse
import logging

parser = argparse.ArgumentParser(description='Start a new process with RPC server')
parser.add_argument('procname', nargs='?', default=None, help='Name of this process')
parser.add_argument('--listen_addr', nargs='?', default="tcp://127.0.0.1:*", help='Address to listen on (default is "tcp://127.0.0.1:*")')
parser.add_argument('--daemon', nargs='?', default=False, const=True, help='Run the process as a daemon')
parser.add_argument('--qt', nargs='?', default=False, const=True, help='Run the RPC server alongside a Qt application')
parser.add_argument('--verbose', nargs='?', default=False, const=True, help='Print log messages to stdout')
parser.add_argument('--logaddr', nargs='?', default=None, help='Optional address to send log records to')
parser.add_argument('--loglevel', nargs='?', default='INFO', help='Log level for this process. (default is INFO)')
parser.add_argument('--bootstrap_addr', nargs='?', default=None, help='Address to send bootstrap messages to')
parser.add_argument('--child_name_prefix', nargs='?', default='', help='Prefix for child process names')

args = parser.parse_args()
conf = vars(args)

conf['class_name'] = 'QtRPCServer' if conf['qt'] else 'RPCServer'
try:
    # loglevel might be sent as an integer string
    if conf['loglevel'].isdigit():
        conf['loglevel'] = int(conf['loglevel'])
    else:
        conf['loglevel'] = getattr(logging, conf['loglevel'].upper())
except ValueError:
    pass

# Fork and detach if requested (only for posix systems; in windows, detachment happens in the parent)
if conf['daemon'] is True and sys.platform != 'win32':
    if os.fork() != 0:
        sys.exit(0)
    os.setsid()
    if os.fork() != 0:
        sys.exit(0)

    # flush and redirect stdio
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = open('/dev/null', 'r+')
    os.dup2(devnull.fileno(), 0)  # Redirect stdin
    os.dup2(devnull.fileno(), 1)  # Redirect stdout
    os.dup2(devnull.fileno(), 2)  # Redirect stderr

# delay all possible imports until after fork
import zmq
import time
import traceback
import faulthandler
import logging

if conf['verbose']:
    logging.basicConfig(level=conf['loglevel'])

# Set up some basic debugging support before importing teleprox
faulthandler.enable()
logger = logging.getLogger()
logger.setLevel(conf['loglevel'])

from teleprox import log
import teleprox

# Set up process name prefix if requested
teleprox.process.PROCESS_NAME_PREFIX = conf['child_name_prefix']

# Start QApplication if requested
if conf['qt']:
    from teleprox import qt
    app = qt.QApplication([])
    app.setQuitOnLastWindowClosed(False)

# Set up log record forwarding
log.set_thread_name('main_thread')
if conf['procname'] is not None:
    log.set_process_name(conf['procname'])
if conf['logaddr'] is not None:
    log.set_logger_address(conf['logaddr'].encode())

# Also send unhandled exceptions to log server
log.log_exceptions()

logger.info('Bootstrapping new process "{procname}" {class_name}({listen_addr}) log_addr:{logaddr} log_level:{loglevel}'.format(**conf))

# Create RPC server
try:
    # Create server
    server_class = getattr(teleprox, conf['class_name'])
    server = server_class(conf['listen_addr'])
    status = {'address': server.address.decode(), 'pid': os.getpid()}
except:
    logger.error("Error starting {class_name} with args: {args}:".format(**conf))
    status = {'error': traceback.format_exception(*sys.exc_info()), 'pid': os.getpid()}
    
# Report server status to spawner
# Open a socket to parent process to inform it of the new RPC server address
if conf['bootstrap_addr'] is not None:
    bootstrap_sock = zmq.Context.instance().socket(zmq.PAIR)
    bootstrap_sock.connect(conf['bootstrap_addr'].encode())
    bootstrap_sock.linger = 1000

    start = time.time()
    while time.time() < start + 10.0:
        # send status repeatedly until spawner gives a reply.
        bootstrap_sock.send_json(status)
        try:
            bootstrap_sock.recv(zmq.NOBLOCK)
            break
        except zmq.error.Again:
            time.sleep(0.01)
            continue

    bootstrap_sock.close()

# Run server until heat death of universe
if 'address' in status:
    server.run_forever()
    
if conf['qt']:
    try:
        app.exec()
    except AttributeError:
        app.exec_()
