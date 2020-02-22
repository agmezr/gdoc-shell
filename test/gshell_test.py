"""Tests for the main and util modules."""
import configparser
import unittest
from unittest import mock

import gdoc_shell
import utils

MOCK_FID_PATH = './test_fid'
MOCK_FID = '123Testing....Testing'
CONFIG_ALLOWED_CMD = {'ls', 'pwd'}
TEST_CONFIG = 'gshell_test.config'


class GShellTest(unittest.TestCase):

    def test_read_fid(self):
        """Tests the function returns the id stored in a file."""
        result = utils.read_id(MOCK_FID_PATH)
        self.assertEqual(result, MOCK_FID)

    def test_execute_command(self):
        """Tests the different results for execute command"""
        valid_commands = {'pwd', 'ls', 'touch', 'echo', 'more'}
        echo_test = 'Testing'
        output = gdoc_shell._execute_command(f'echo {echo_test}', valid_commands)
        invalid = gdoc_shell._execute_command('rm -rf some', valid_commands)
        self.assertEqual(echo_test, output)
        self.assertEqual(invalid, gdoc_shell.OUTPUT_INVALID_CMD)

    def test_build_valid_commands(self):
        """Tests the function to read the available commands from config."""
        config = configparser.ConfigParser()
        config.read(TEST_CONFIG)
        commands = gdoc_shell._build_valid_commands(config)
        self.assertEqual(commands, CONFIG_ALLOWED_CMD)


if __name__ == '__main__':
    unittest.main()
