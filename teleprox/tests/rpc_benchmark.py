# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import time, threading
import teleprox

def test_poingrate(cli, dur=2.0):
    start = time.time()
    count = 0
    while time.time() < start + dur:
        assert cli.send('ping', sync='sync') == 'pong'
        count += 1
        
    print("Ping rate: %0.0f/sec" % (count/dur))


def test_async_poingrate(cli, dur=2.0, buffer=500):
    start = time.time()
    count = 0
    futs = []
    for i in range(buffer):
        futs.append(cli.send('ping', sync='async'))
    while time.time() < start + dur:
        futs.append(cli.send('ping', sync='async'))
        assert futs.pop(0).result() == 'pong'
        count += 1
        
    print("Async ping rate: %0.0f/sec" % (count/dur))

    
    

# thread, inproc
print("=========== inproc to thread ============")
server = teleprox.RPCServer('inproc://testserver')
thread = threading.Thread(target=server.run_forever, daemon=True)
thread.start()

cli = teleprox.RPCClient(server.address)
test_poingrate(cli)
test_async_poingrate(cli)

cli.close_server()


# thread, tcp
print("=========== tcp to thread ============")
server = teleprox.RPCServer('tcp://127.0.0.1:*')
thread = threading.Thread(target=server.run_forever, daemon=True)
thread.start()

cli = teleprox.RPCClient(server.address)
test_poingrate(cli)
test_async_poingrate(cli)

cli.close_server()


# process
print("=========== TCP to spawned process ============")
proc = teleprox.ProcessSpawner()
test_poingrate(proc.client)
test_async_poingrate(proc.client)


# process
print("=========== TCP to spawned Qt process ============")
proc = teleprox.ProcessSpawner(qt=True)
test_poingrate(proc.client)
test_async_poingrate(proc.client)

