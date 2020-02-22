"""Various functions used in the main module."""
import logging
import argparse
import os

class Section():
    """Name of all the sections in the config"""
    CREDENTIALS = 'credentials'
    COMMANDS = 'valid_commands'
    FILE = 'filename'
    PID_PATH = 'pid_path'
    SLEEP_TIME = 'sleep_time'

def build_parser():
    """Build the parser for the args."""
    parser = argparse.ArgumentParser(description='Runs GDoc shell')
    parser.add_argument('mode', type=str, help='Setup|Run|Stop')
    return parser.parse_args()

def setup_logger(name, log_path='log/gdoc_shell.log'):
    """Sets up the logger object.

    Args:
        name: Name of the logger. Usually __name__.
        log_path: Read from the config.

    Returns:
        A tuple containing a configured logger and the handler. The handler is
        used to avoid issues when creating the daemon process.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.INFO)
    formatstr = '%(asctime)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(formatstr)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger, fh

def read_id(path):
    """Reads a file containing a single line.

    Used to get file id and pid lock file
    """
    with open(path, 'r') as f:
        fid = f.readline()
    return fid

def create_lib_dir(path):
    """Creates the directory used to store the token auth and file id."""
    if not os.path.exists(path):
        os.makedirs(path)

def needs_setup(path, fid_path, token_path):
    """Checks whether or not the setup func needs to run."""
    if not os.path.exists(path):
        return True
    return not os.path.exists(fid_path) or not os.path.exists(token_path)