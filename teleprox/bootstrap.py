"""Script for bootstrapping new processes created with ProcessSpawner.
"""
import zmq
import time
import os
import sys
import json
import traceback
import faulthandler
import logging

if __name__ == '__main__':
    # Load configuration options for this process from stdin
    stdin = sys.stdin.read()
    assert len(stdin) > 0, "This script should be invoked from teleprox.ProcessSpawner"
    conf = json.loads(stdin)
    # process name is passed in argv to make it easier to identify processes
    # from the outside.
    if len(sys.argv) > 1:
        conf['procname'] = sys.argv[1]
    else:
        conf['procname'] = None

    if conf['daemon'] is True and sys.platform != 'win32':
        # detach from parent process (only on unix; in windows, detachment happens in the parent)
        print("starting pid: ", os.getpid())
        if os.fork() != 0:
            sys.exit(0)
        print("forked pid 1: ", os.getpid())
        os.setsid()
        if os.fork() != 0:
            sys.exit(0)
        print("forked pid 2: ", os.getpid())

        # flush and redirect stdio
        sys.stdout.flush()
        sys.stderr.flush()
        devnull = open('/dev/null', 'r+')
        os.dup2(devnull.fileno(), 0)  # Redirect stdin
        os.dup2(devnull.fileno(), 1)  # Redirect stdout
        os.dup2(devnull.fileno(), 2)  # Redirect stderr

    # Set up some basic debugging support before importing teleprox
    faulthandler.enable()
    logger = logging.getLogger()
    logger.level = conf['loglevel']

    from teleprox import log
    import teleprox

    # Start QApplication if requested
    if conf['qt']:
        from teleprox import qt
        app = qt.QApplication([])
        app.setQuitOnLastWindowClosed(False)

    # Set up log record forwarding
    if conf['procname'] is not None:
        log.set_process_name(conf['procname'])
    if conf['logaddr'] is not None:
        log.set_logger_address(conf['logaddr'].encode())

    # Also send unhandled exceptions to log server
    log.log_exceptions()

    logger.info("New process {procname} {class_name}({args}) log_addr:{logaddr} log_level:{loglevel}".format(**conf))

    # Open a socket to parent process to inform it of the new RPC server address
    bootstrap_sock = zmq.Context.instance().socket(zmq.PAIR)
    bootstrap_sock.connect(conf['bootstrap_addr'].encode())
    bootstrap_sock.linger = 1000

    # Create RPC server
    try:
        # Create server
        server_class = getattr(teleprox, conf['class_name'])
        server = server_class(**conf['args'])
        status = {'address': server.address.decode()}
    except:
        logger.error("Error starting {class_name} with args: {args}:".format(**conf))
        status = {'error': traceback.format_exception(*sys.exc_info())}
        
    # Report server status to spawner
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
        app.exec_()
