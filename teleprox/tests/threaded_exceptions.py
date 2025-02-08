import threading
import logging


def raise_after_delay(msg, delay=0.5):
    """Raise an exception after a delay.
    """
    import time
    time.sleep(delay)
    raise Exception(msg)


def log_msg(msg, level='INFO', logger=None):
    """Log a message.
    """
    if logger is None:
        logger = logging.getLogger(__file__)
    if isinstance(logger, str):
        logger = logging.getLogger(logger)
    if isinstance(level, str):
        level = getattr(logging, level)
    logger.log(level, msg)


def raise_in_thread(msg, delay=0):
    """Raise an exception in a separate thread.
    """
    import threading
    t = threading.Thread(target=lambda: raise_after_delay(msg, delay))
    t.start()
    return t


def log_in_thread(msg, level='INFO', logger=None):
    """Log a message in a separate thread.
    """
    import threading
    t = threading.Thread(target=lambda: log_msg(msg, level, logger))
    t.start()
    return t
