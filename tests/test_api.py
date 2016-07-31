# pyinfra
# File: tests/test_api.py
# Desc: tests for the pyinfra API

from unittest import TestCase
from socket import gaierror, error as socket_error

from mock import patch, mock_open
from paramiko.agent import AgentRequestHandler
from paramiko import (
    SSHClient, SFTPClient, RSAKey,
    SSHException, AuthenticationException
)

# Patch in paramiko fake classes
from pyinfra.api import ssh
from .paramiko_util import (
    FakeSSHClient, FakeSFTPClient, FakeRSAKey,
    FakeAgentRequestHandler
)


from pyinfra import pseudo_state, pseudo_host
from pyinfra.api import Inventory, Config, State
from pyinfra.api.ssh import connect_all, connect
from pyinfra.api.operation import add_op, add_limited_op
from pyinfra.api.operations import run_ops
from pyinfra.api.exceptions import PyinfraError

from pyinfra.modules import files, server

from .util import create_host


def make_inventory(hosts=('somehost', 'anotherhost'), **kwargs):
    return Inventory(
        (hosts, {}),
        test_group=([
            'somehost'
        ], {
            'group_data': 'hello world'
        }),
        ssh_user='vagrant',
        **kwargs
    )


class TestInventoryApi(TestCase):
    def test_inventory_creation(self):
        inventory = make_inventory()

        # Check length
        self.assertEqual(len(inventory.hosts), 2)

        # Get a host
        host = inventory['somehost']
        self.assertEqual(host.data.ssh_user, 'vagrant')

        # Check our group data
        self.assertEqual(
            inventory.get_group_data('test_group').dict(),
            {'group_data': 'hello world'}
        )

    def test_tuple_host_group_inventory_creation(self):
        inventory = make_inventory(
            hosts=[
                ('somehost', {'some_data': 'hello'}),
            ],
            tuple_group=([
                ('somehost', {'another_data': 'world'}),
            ], {
                'tuple_group_data': 'word'
            })
        )

        # Check host data
        host = inventory['somehost']
        self.assertEqual(host.data.some_data, 'hello')
        self.assertEqual(host.data.another_data, 'world')

        # Check group data
        self.assertEqual(host.data.tuple_group_data, 'word')


class TestSSHApi(TestCase):
    def setUp(self):
        self.fake_connect_patch = patch('pyinfra.api.ssh.SSHClient.connect')
        self.fake_connect_mock = self.fake_connect_patch.start()

        self.fake_get_transport_patch = patch('pyinfra.api.ssh.SSHClient.get_transport')
        self.fake_get_transport_patch.start()

        self.fake_agentrequesthandler_patch = patch('pyinfra.api.ssh.AgentRequestHandler')
        self.fake_agentrequesthandler_patch.start()

    def tearDown(self):
        self.fake_connect_patch.stop()
        self.fake_get_transport_patch.stop()
        self.fake_agentrequesthandler_patch.stop()

    def test_connect_all(self):
        inventory = make_inventory()
        state = State(inventory, Config())
        connect_all(state)

        self.assertEqual(len(inventory.connected_hosts), 2)

    def test_connect_all_password(self):
        '''
        Ensure we can connect using a password.
        '''

        inventory = make_inventory(ssh_password='test')

        # Get a host
        host = inventory['somehost']
        self.assertEqual(host.data.ssh_password, 'test')

        state = State(inventory, Config())
        connect_all(state)

        self.assertEqual(len(inventory.connected_hosts), 2)

    def test_connect_exceptions_fail(self):
        '''
        Ensure that connection exceptions are captured and return None.
        '''

        with patch('pyinfra.api.ssh.SSHClient', FakeSSHClient):
            for exception in (
                AuthenticationException, SSHException,
                gaierror, socket_error, EOFError
            ):
                host = create_host(name='nowt', data={
                    'ssh_hostname': exception
                })
                self.assertEqual(connect(host), None)

    def test_connect_with_ssh_key(self):
        state = State(make_inventory(hosts=(
            ('somehost', {'ssh_key': 'testkey'}),
        )), Config())

        with patch('pyinfra.api.ssh.path.isfile', lambda *args, **kwargs: True), \
                patch('pyinfra.api.ssh.RSAKey.from_private_key_file') as fake_key_open:

            fake_key = FakeRSAKey()
            fake_key_open.return_value = fake_key

            state.deploy_dir = '/'

            connect_all(state)

            # Check the key was created properly
            fake_key_open.assert_called_with(filename='testkey', password=None)

            # And check the Paramiko SSH call was correct
            self.fake_connect_mock.assert_called_with(
                'somehost',
                allow_agent=False,
                look_for_keys=False,
                pkey=fake_key,
                port=22,
                timeout=10,
                username='vagrant'
            )

    def test_connect_with_missing_ssh_key(self):
        state = State(make_inventory(hosts=(
            ('somehost', {'ssh_key': 'testkey'}),
        )), Config())

        with self.assertRaises(IOError) as e:
            connect_all(state)

        # Ensure pyinfra style IOError
        self.assertTrue(e.exception.message.startswith('No such private key file:'))

class PatchSSHTest(TestCase):
    '''
    A test class that patches out the paramiko SSH parts such that they succeed as normal.
    The SSH tests above check these are called correctly.
    '''

    @classmethod
    def setUpClass(cls):
        ssh.SSHClient = FakeSSHClient
        ssh.SFTPClient = FakeSFTPClient
        ssh.RSAKey = FakeRSAKey
        ssh.AgentRequestHandler = FakeAgentRequestHandler

    @classmethod
    def tearDownClass(cls):
        ssh.SSHClient = SSHClient
        ssh.SFTPClient = SFTPClient
        ssh.RSAKey = RSAKey
        ssh.AgentRequestHandler = AgentRequestHandler


class TestStateApi(PatchSSHTest):
    def test_fail_percent(self):
        '''
        Ensure that ``Config.FAIL_PERCENT`` works as intended when connecting.
        '''

        inventory = make_inventory(('somehost', SSHException, 'anotherhost'))
        state = State(inventory, Config(FAIL_PERCENT=1))

        # Ensure we would fail at this point
        with self.assertRaises(PyinfraError) as context:
            connect_all(state)
            self.assertEqual(context.exception.message, 'Over 1% of hosts failed')

        # Ensure the other two did connect
        self.assertEqual(len(inventory.connected_hosts), 2)


class TestOperationsApi(PatchSSHTest):
    def test_op(self):
        state = State(make_inventory(), Config())
        connect_all(state)

        add_op(
            state, files.file,
            '/var/log/pyinfra.log',
            user='pyinfra',
            group='pyinfra',
            mode='644',
            sudo=True,
            sudo_user='test_sudo',
            su_user='test_su',
            ignore_errors=True
        )

        # Ensure we have an op
        self.assertEqual(len(state.op_order), 1)

        first_op_hash = state.op_order[0]

        # Ensure the op name
        self.assertEqual(
            state.op_meta[first_op_hash]['names'],
            {'Files/File'}
        )

        # Ensure the commands
        self.assertEqual(
            state.ops['somehost'][first_op_hash]['commands'],
            [
                'touch /var/log/pyinfra.log',
                'chmod 644 /var/log/pyinfra.log',
                'chown pyinfra:pyinfra /var/log/pyinfra.log'
            ]
        )

        # Ensure the meta
        meta = state.op_meta[first_op_hash]
        self.assertEqual(meta['sudo'], True)
        self.assertEqual(meta['sudo_user'], 'test_sudo')
        self.assertEqual(meta['su_user'], 'test_su')
        self.assertEqual(meta['ignore_errors'], True)

        # Ensure run ops works
        run_ops(state)

    def test_file_op(self):
        state = State(make_inventory(), Config())
        connect_all(state)

        with patch('pyinfra.modules.files.path.isfile', lambda *args, **kwargs: True):
            # Test normal
            add_op(
                state, files.put,
                {'First op name'},
                'files/file.txt',
                '/home/vagrant/file.txt'
            )

            # And with sudo
            add_op(
                state, files.put,
                'files/file.txt',
                '/home/vagrant/file.txt',
                sudo=True,
                sudo_user='pyinfra'
            )

            # And with su
            add_op(
                state, files.put,
                'files/file.txt',
                '/home/vagrant/file.txt',
                su_user='pyinfra'
            )

        # Ensure we have all ops
        self.assertEqual(len(state.op_order), 3)

        first_op_hash = state.op_order[0]

        # Ensure first op is the right one
        self.assertEqual(
            state.op_meta[first_op_hash]['names'],
            {'First op name'}
        )

        # Ensure first op has the right (upload) command
        self.assertEqual(
            state.ops['somehost'][first_op_hash]['commands'],
            [
                ('files/file.txt', '/home/vagrant/file.txt')
            ]
        )

        # Ensure second op has sudo/sudo_user
        self.assertEqual(state.op_meta[state.op_order[1]]['sudo'], True)
        self.assertEqual(state.op_meta[state.op_order[1]]['sudo_user'], 'pyinfra')

        # Ensure third has su_user
        self.assertEqual(state.op_meta[state.op_order[2]]['su_user'], 'pyinfra')

        # Check run ops works
        with patch('pyinfra.api.util.open', mock_open(read_data='test!'), create=True):
            run_ops(state)
            run_ops(state, serial=True)
            run_ops(state, no_wait=True)

    def test_limited_op(self):
        inventory = make_inventory()
        state = State(inventory, Config())
        connect_all(state)

        # Add op to both hosts
        add_op(state, server.shell, 'echo "hi"')

        # Add op to just the first host
        add_limited_op(
            state, server.user, inventory['somehost'],
            'somehost_user'
        )

        # Ensure there are two ops
        self.assertEqual(len(state.op_order), 2)

        # Ensure somehost has two ops and anotherhost only has the one
        self.assertEqual(len(state.ops['somehost']), 2)
        self.assertEqual(len(state.ops['anotherhost']), 1)

    def test_pseudo_op(self):
        inventory = make_inventory()
        state = State(inventory, Config())
        connect_all(state)

        pseudo_state.set(state)
        pseudo_host.set(inventory['somehost'])

        # Exceute the op "bare"
        server.shell('echo "hi"')

        # Ensure this is ignored
        state.active = False
        server.shell('echo "hi 2"')

        # We should now have one op
        self.assertEqual(len(state.op_order), 1)

        # Ensure only somehost has actual op
        self.assertEqual(len(state.ops['somehost']), 1)
        self.assertEqual(len(state.ops['anotherhost']), 0)

        # Check we can't call it inside another op
        state.active = True
        state.in_op = True
        with self.assertRaises(PyinfraError):
            server.shell('echo "hi 3"')

        pseudo_state.reset()
        pseudo_host.reset()

    def test_pipelining_active_works(self):
        state = State(make_inventory(), Config())
        connect_all(state)

        state.pipelining = True
        add_op(state, server.shell, 'echo "hi"')
