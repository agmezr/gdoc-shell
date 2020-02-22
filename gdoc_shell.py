# -*- coding: utf-8 -*-
"""GDoc Shell.

A service used to run commands shell commands from Google Doc to this machine.

The basic example of the Google Doc:

+---------------------+
|Insert command below |
+---------------------+
|pwd                  |
+---------------------+

+--------+------------+-----------+
|Command | Output     | Datetime  |
+--------+------------+-----------+
|pwd     | /some/path | 2020-01-01|
+--------+------------+-----------+
"""
import configparser
import datetime
import os
import signal
import subprocess
import time
import sys

import daemon
from daemon import pidfile
from httplib2 import Http
from googleapiclient import discovery
from oauth2client import file, client, tools

import utils

GSHELL_CONFIG = 'gshell.config'
MAIN_SECTION = 'GSHELL'

# path to store the doc id and token auth
STORAGE_PATH = os.path.join(os.path.expanduser('~'), '.gdoc_shell')
FILE_ID_PATH = os.path.join(STORAGE_PATH, 'fid')
TOKEN_PATH = os.path.join(STORAGE_PATH, 'token')

# drive params
# using drive.file since it only creates one file
SCOPES = ['https://www.googleapis.com/auth/drive.file']
DOC_MIMETYPE = 'application/vnd.google-apps.document'

# msgs output table
OUTPUT_INVALID_CMD = 'Command is not in the list of valid commands. Please add it to the config if you want to use it.'
OUTPUT_NO_OUTPUT = 'No output'

logger, handler = utils.setup_logger(__name__)

DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def _get_http_client(cred_file):
    """Uses project credentials (if exists) along with requested OAuth2 scopes.

    Based from this example:
    https://github.com/gsuitedevs/python-samples/blob/master/docs/mail-merge/docs_mail_merge.py
    """
    store = file.Storage(TOKEN_PATH)
    cred = store.get()
    if not cred or cred.invalid:
        flow = client.flow_from_clientsecrets(cred_file, SCOPES)
        cred = tools.run_flow(flow, store)
    return cred.authorize(Http())


def _create_file(service, filename):
    """Creates the file used for the commands.

    This file will be owned by the user only.
    """
    body = {
        'name': filename,
        'mimeType': DOC_MIMETYPE,
    }
    fid = service.files().create(body=body, fields='id').execute().get('id')
    with open(FILE_ID_PATH, 'w') as f:
        f.write(fid)
    return fid


def _add_tables(service, fid):
    """Creates the tables for the generated google doc.

    This tables will be used for all the functions here.
    The first one is where the user will leave the command to be executed.
    The second one is a log with the output of all the commands executed from the first table.
    """
    # Inserting both tables in a single requests results in only 1 table.
    # I need to research more on this.
    for col in (1, 3):
        requests = [{
          'insertTable': {
              'rows': 2,
              'columns': col,
              'endOfSegmentLocation': {
                'segmentId': ''
              }
          },
        }]
        _batch_update(fid, service, requests)
    
    document = service.documents().get(documentId=fid).execute()
    command_table = document['body']['content'][2]  # first table after paragraph
    output_table = document['body']['content'][4]  # there is a line break after first table, hence the fourth element

    # Always start from right to left to avoid issues with the index.
    output_table_cells = output_table['table']['tableRows'][0]['tableCells']
    command_table_cells = command_table['table']['tableRows'][0]['tableCells']

    requests = [
        _build_insert_text(output_table_cells[2]['startIndex'] + 1, 'Datetime'),
        _build_insert_text(output_table_cells[1]['startIndex'] + 1, 'Output'),
        _build_insert_text(output_table_cells[0]['startIndex'] + 1, 'Command'),
        _build_insert_text(command_table_cells[0]['startIndex'] + 1, 'Insert command below'),
    ]
    _batch_update(fid, service, requests)


def _read_command(service, fid):
    """Reads a command on the first table of the gdoc."""
    document = service.documents().get(documentId=fid).execute()
    command_table = document['body']['content'][2]
    cell = command_table['table']['tableRows'][1]['tableCells'][0]['content'][0]
    content = cell['paragraph']['elements'][0]['textRun']['content'].strip()
    return content


def _execute_command(cmd, valid_commands):
    """Executes the command the user put on the first table.

    To avoid potential MAJOR security risks with this, the command will only be
    executed if is on a list of valid commands. This list starts with a small
    set and can be modified by the user in the .config file.
    """
    cmd_list = cmd.split()
    if not cmd_list:  # the user hasn't put a new command.
        return None
    if cmd_list[0] not in valid_commands:
        logger.warning('Attempted command %s failed since is not in valid commands list', cmd)
        return OUTPUT_INVALID_CMD
    result = subprocess.run(cmd_list, capture_output=True)
    output = result.stdout.decode('utf-8').strip()
    logger.info('Output for command %s: %s', cmd, output)
    return output or OUTPUT_NO_OUTPUT


def _write_output(cmd, output, service, fid):
    """Inserts the output of the command to the output table.

    The output table should be the last table in the doc and have 3 columns
    """
    # No command was read on the table.
    if output is None:
        return
    document = service.documents().get(documentId=fid).execute()
    output_table = document['body']['content'][-2]
    table_cells = output_table['table']['tableRows'][-1]['tableCells']

    # starts from right to left to avoid issues with indexes
    index_datetime = table_cells[2]['startIndex'] + 1
    index_output = table_cells[1]['startIndex'] + 1
    index_cmd = table_cells[0]['startIndex'] + 1
    now = datetime.datetime.now()

    requests = [
        _build_insert_text(index_datetime, now.strftime(DATETIME_FORMAT)),
        _build_insert_text(index_output, output),
        _build_insert_text(index_cmd, cmd),
        {
            'insertTableRow': {   # insert a new row at the end after each call to avoid issues with index
                'tableCellLocation': {
                    'tableStartLocation': {
                        'index': output_table['startIndex'],
                    },
                    'rowIndex': len(output_table['table']['tableRows']) - 1,
                    'columnIndex': 0
                },
                'insertBelow': 'true'
            }
        }]
    _batch_update(fid, service, requests)


def _build_insert_text(index, text):
    """Creates the structure needed for an insert text request."""
    return {
            'insertText': {
                'location': {
                    'index': index,
                },
                'text': text,
            }
        }


def _batch_update(fid, service, requests):
    """Wrapper for the doc api service."""
    service.documents().batchUpdate(documentId=fid, body={'requests': requests}).execute()


def _build_valid_commands(config):
    """Reads and formats the list of valid commands."""
    config_commands = config[MAIN_SECTION][utils.Section.COMMANDS]
    return {cmd.strip() for cmd in config_commands.split(',')}


def setup(config):
    """Reads and apply the config.

    Will create the doc used for the commands and will create the template.
    """
    cred_file = config[MAIN_SECTION][utils.Section.CREDENTIALS]
    filename = config[MAIN_SECTION][utils.Section.FILE]
    http_client = _get_http_client(cred_file)
    drive_service = discovery.build('drive', 'v3', http=http_client)
    docs_service = discovery.build('docs', 'v1', http=http_client)

    fid = _create_file(drive_service, filename)
    logger.info('File created: %s', fid)
    print('File created. Creating template...')
    time.sleep(4)  # wait a couple of seconds to make sure the doc is available
    _add_tables(docs_service, fid)
    logger.info('Template created for file %s', fid)
    print('Template created')
    return fid


def _run():
    """Runs the main process of gdoc_shell.

    1. Read the config and find the ID of the file created during setup.
    2. Find the command in the first table of the gdoc.
    3. Run the command if is in the valid list of commands.
    4. Insert the output to the second table of the gdoc.
    """
    config = configparser.ConfigParser()
    config.read(GSHELL_CONFIG)
    fid = utils.read_id(FILE_ID_PATH)
    logger.info('File id found %s', fid)
    http_client = _get_http_client(config[MAIN_SECTION][utils.Section.CREDENTIALS])
    docs_service = discovery.build('docs', 'v1', http=http_client)
    cmd = _read_command(docs_service, fid)
    logger.info('Command to execute: %s', cmd)
    output = _execute_command(cmd, _build_valid_commands(config))
    _write_output(cmd, output, docs_service, fid)
    logger.info('Output updated to file')


def stop():
    """Stops the daemon process."""
    logger.info('Shutting down daemon process.')
    config = configparser.ConfigParser()
    config.read(GSHELL_CONFIG)
    pid_path = config[MAIN_SECTION][utils.Section.PID_PATH]
    pid = int(utils.read_id(pid_path))
    os.kill(pid, signal.SIGTERM)


def start_daemon_process():
    """Starts the daemon."""
    config = configparser.ConfigParser()
    config.read(GSHELL_CONFIG)
    if not os.path.exists(config[MAIN_SECTION][utils.Section.CREDENTIALS]):
        raise ValueError('Credentials json file not found. Make sure you have '
                         'the correct path in the gshell.config file')
    if utils.needs_setup(STORAGE_PATH, FILE_ID_PATH, TOKEN_PATH):
        utils.create_lib_dir(STORAGE_PATH)
        # For some weird reason having arguments kills the setup method.
        # More precisely on the _get_http_client function.
        sys.argv = []
        fid = setup(config)
        url = 'https://docs.google.com/document/d/{}'.format(fid)
        print('Document created successfully')
        print('You can access your document here:', url)

    pid_path = config[MAIN_SECTION][utils.Section.PID_PATH]
    sleep_time = int(config[MAIN_SECTION][utils.Section.SLEEP_TIME])
    with daemon.DaemonContext(
        working_directory='./',
        umask=0o002,
        files_preserve=[handler.stream],
        stderr=handler.stream,
        pidfile=pidfile.PIDLockFile(pid_path),
    ):
        logger.info('Starting daemon')
        while True:
            logger.info('Running gdoc process.')
            _run()
            time.sleep(sleep_time)


if __name__ == '__main__':
    args = utils.build_parser()
    if args.mode == 'start':
        start_daemon_process()
    elif args.mode == 'stop':
        stop()
    elif args.mode == 'restart':
        stop()
        start_daemon_process()
    else:
        raise ValueError('Invalid mode.')
