from ephemeral_port_reserve import reserve
from fixtures import *  # noqa: F401,F403
from pyln.testing.utils import env, wait_for, TEST_NETWORK
import unittest
import requests
from pathlib import Path
import os
import socketio
import time


def test_clnrest_no_auto_start(node_factory):
    """Ensure that we do not start clnrest unless a `rest-port` is configured."""
    l1 = node_factory.get_node()
    wait_for(lambda: [p for p in l1.rpc.plugin('list')['plugins'] if 'clnrest.py' in p['name']] == [])
    assert l1.daemon.is_in_log(r'plugin-clnrest.py: Killing plugin: disabled itself at init: `rest-port` option is not configured')


def test_clnrest_self_signed_certificates(node_factory):
    """Test that self-signed certificates have `rest-host` IP in Subject Alternative Name."""
    rest_port = str(reserve())
    rest_host = '127.0.0.2'
    base_url = f'https://{rest_host}:{rest_port}'
    l1 = node_factory.get_node(options={'disable-plugin': 'cln-grpc',
                                        'rest-port': rest_port,
                                        'rest-host': rest_host})
    wait_for(lambda: l1.daemon.is_in_log(r'plugin-clnrest.py: REST server running at ' + base_url))
    rest_certs_default = Path(l1.rpc.listconfigs()['configs']['rest-certs']['value_str'])
    ca_cert_path = rest_certs_default / 'ca.pem'
    r = requests.get(base_url + '/v1/list-methods', verify=ca_cert_path)
    assert r.status_code == 200


@unittest.skipIf(env('RUST') != '1', 'RUST is not enabled skipping rust-dependent tests')
def test_clnrest_does_not_depend_on_grpc_plugin_certificates(node_factory):
    """Test that clnrest doesn't depend on `cln-grpc` plugin certificates when started with default options.

    Defaults:
    - rest-port: 127.0.0.1
    - rest-protocol: https
    """
    grpc_port = str(reserve())
    rest_port = str(reserve())
    l1 = node_factory.get_node(options={'grpc-port': grpc_port,
                                        'rest-port': rest_port})
    base_url = 'https://127.0.0.1:' + rest_port
    wait_for(lambda: l1.daemon.is_in_log(r'serving grpc on 0.0.0.0:'))
    wait_for(lambda: l1.daemon.is_in_log(r'plugin-clnrest.py: REST server running at ' + base_url))
    rest_certs_default = Path(l1.rpc.listconfigs()['configs']['rest-certs']['value_str'])
    ca_cert_path = rest_certs_default / 'ca.pem'
    r = requests.get(base_url + '/v1/list-methods', verify=ca_cert_path)
    assert r.status_code == 200


def test_clnrest_generate_certificate(node_factory):
    """Test whether we correctly generate the certificates."""
    # when `rest-port` not specified, clnrest disables itself and doesn't generate certs
    l1 = node_factory.get_node()
    wait_for(lambda: l1.daemon.is_in_log(r'plugin-clnrest.py: Killing plugin: disabled itself at init'))
    rest_certs_default = Path(l1.daemon.lightning_dir) / TEST_NETWORK / 'clnrest'
    assert not rest_certs_default.exists()

    # when `rest-protocol` is `http`, certs are not generated
    rest_port = str(reserve())
    rest_protocol = 'http'
    l1 = node_factory.get_node(options={'rest-port': rest_port,
                                        'rest-protocol': rest_protocol})
    rest_certs_default = Path(l1.daemon.lightning_dir) / TEST_NETWORK / 'clnrest'
    assert not rest_certs_default.exists()

    # node l1 not started
    rest_port = str(reserve())
    l1 = node_factory.get_node(options={'rest-port': rest_port}, start=False)
    rest_certs_default = Path(l1.daemon.lightning_dir) / TEST_NETWORK / 'clnrest'
    files = [rest_certs_default / f for f in [
        'ca.pem',
        'ca-key.pem',
        'client.pem',
        'client-key.pem',
        'server-key.pem',
        'server.pem',
    ]]

    # before starting no files exist.
    assert [f.exists() for f in files] == [False] * len(files)

    # certificates generated at startup
    l1.start()
    assert [f.exists() for f in files] == [True] * len(files)

    # the files exist, restarting should not change them
    contents = [f.open().read() for f in files]
    l1.restart()
    assert contents == [f.open().read() for f in files]

    # remove client.pem file, so all certs are regenerated at restart
    files[2].unlink()
    l1.restart()
    contents_1 = [f.open().read() for f in files]
    assert [c[0] != c[1] for c in zip(contents, contents_1)] == [True] * len(files)

    # remove client-key.pem file, so all certs are regenerated at restart
    files[3].unlink()
    l1.restart()
    contents_2 = [f.open().read() for f in files]
    assert [c[0] != c[1] for c in zip(contents, contents_2)] == [True] * len(files)


def start_node_with_clnrest(node_factory):
    """Start a node with the clnrest plugin, whose options are the default options.
    Return:
    - the node,
    - the base url and
    - the certificate authority path used for the self-signed certificates."""
    rest_port = str(reserve())
    l1 = node_factory.get_node(options={'rest-port': rest_port})
    base_url = 'https://127.0.0.1:' + rest_port
    wait_for(lambda: l1.daemon.is_in_log(r'plugin-clnrest.py: REST server running at ' + base_url))
    rest_certs_default = Path(l1.rpc.listconfigs()['configs']['rest-certs']['value_str'])
    ca_cert_path = rest_certs_default / 'ca.pem'
    return l1, base_url, ca_cert_path


def test_clnrest_list_methods(node_factory):
    """Test GET request on `/v1/list-methods` end point with default values for options."""
    # start a node with clnrest
    l1, base_url, ca_cert_path = start_node_with_clnrest(node_factory)

    # /v1/list-methods
    r = requests.get(base_url + '/v1/list-methods', verify=ca_cert_path)
    assert r.status_code == 200
    assert r.text.find('Command: getinfo') > 0

    # /v1/list-methods with the `help` method of l1 node returning an error
    plugin = os.path.join(os.getcwd(), "tests/plugins/clnrest_help_method.py")
    l1.rpc.plugin_start(plugin)
    r = requests.get(base_url + '/v1/list-methods', verify=ca_cert_path)
    assert r.status_code == 500
    assert r.json()['error']['code'] == -1


def test_clnrest_rpc_method(node_factory):
    """Test POST requests on `/v1/<rpc_method>` end points with default values for options."""
    # start a node with clnrest
    l1, base_url, ca_cert_path = start_node_with_clnrest(node_factory)

    # /v1/getinfo no rune provided in header of the request
    r = requests.post(base_url + '/v1/getinfo', verify=ca_cert_path)
    assert r.status_code == 401
    assert r.json()['error']['code'] == 403

    # /v1/getinfo with a rune which doesn't authorized getinfo method
    rune_no_getinfo = l1.rpc.createrune(restrictions=[["method/getinfo"]])['rune']
    r = requests.post(base_url + '/v1/getinfo', headers={'Rune': rune_no_getinfo},
                      verify=ca_cert_path)
    assert r.status_code == 401
    assert r.json()['error']['code'] == 1502

    # /v1/getinfo with a correct rune
    rune_getinfo = l1.rpc.createrune(restrictions=[["method=getinfo"]])['rune']
    r = requests.post(base_url + '/v1/getinfo', headers={'Rune': rune_getinfo},
                      verify=ca_cert_path)
    assert r.status_code == 201
    assert r.json()['id'] == l1.info['id']

    # /v1/invoice with a correct rune but missing parameters
    rune_invoice = l1.rpc.createrune(restrictions=[["method=invoice"]])['rune']
    r = requests.post(base_url + '/v1/invoice', headers={'Rune': rune_invoice},
                      verify=ca_cert_path)
    assert r.status_code == 500
    assert r.json()['error']['code'] == -32602

    # /v1/invoice with a correct rune but wrong parameters
    rune_invoice = l1.rpc.createrune(restrictions=[["method=invoice"]])['rune']
    r = requests.post(base_url + '/v1/invoice', headers={'Rune': rune_invoice},
                      data={'amount_msat': '<WRONG>',
                            'label': 'label',
                            'description': 'description'},
                      verify=ca_cert_path)
    assert r.status_code == 500
    assert r.json()['error']['code'] == -32602

    # l2 pays l1's invoice where the invoice is created with /v1/invoice
    rune_invoice = l1.rpc.createrune(restrictions=[["method=invoice"]])['rune']
    r = requests.post(base_url + '/v1/invoice', headers={'Rune': rune_invoice},
                      data={'amount_msat': '50000000',
                            'label': 'label',
                            'description': 'description'},
                      verify=ca_cert_path)
    invoice = r.json()['bolt11']
    l2 = node_factory.get_node()
    l1.connect(l2)
    l2.fundchannel(l1, 100000)
    l2.rpc.pay(invoice)


# Tests for websocket are written separately to avoid flake8
# to complain with the errors F811 like this "F811 redefinition of
# unused 'message'".

def test_clnrest_websocket_no_rune(node_factory):
    """Test websocket with default values for options."""
    # start a node with clnrest
    l1, base_url, ca_cert_path = start_node_with_clnrest(node_factory)

    # http session
    http_session = requests.Session()
    http_session.verify = ca_cert_path.as_posix()

    # no rune provided => no websocket connection and no notification received
    sio = socketio.Client(http_session=http_session)
    notifications = []

    @sio.event
    def message(data):
        notifications.append(data)
    sio.connect(base_url)
    sio.sleep(2)
    l1.rpc.invoice(10000, "label", "description")  # trigger `invoice_creation` notification
    time.sleep(2)
    sio.disconnect()
    assert len(notifications) == 0


def test_clnrest_websocket_wrong_rune(node_factory):
    """Test websocket with default values for options."""
    # start a node with clnrest
    l1, base_url, ca_cert_path = start_node_with_clnrest(node_factory)

    # http session
    http_session = requests.Session()
    http_session.verify = ca_cert_path.as_posix()

    # wrong rune provided => no websocket connection and no notification received
    http_session.headers.update({"rune": "<WRONG>"})
    sio = socketio.Client(http_session=http_session)
    notifications = []

    @sio.event
    def message(data):
        notifications.append(data)
    sio.connect(base_url)
    sio.sleep(2)
    l1.rpc.invoice(10000, "label", "description")  # trigger `invoice_creation` notification
    time.sleep(2)
    sio.disconnect()
    assert len(notifications) == 0


def test_clnrest_websocket_unrestricted_rune(node_factory):
    """Test websocket with default values for options."""
    # start a node with clnrest
    l1, base_url, ca_cert_path = start_node_with_clnrest(node_factory)

    # http session
    http_session = requests.Session()
    http_session.verify = ca_cert_path.as_posix()

    # unrestricted rune provided => websocket connection and notifications received
    rune_unrestricted = l1.rpc.createrune()['rune']
    http_session.headers.update({"rune": rune_unrestricted})
    sio = socketio.Client(http_session=http_session)
    notifications = []

    @sio.event
    def message(data):
        notifications.append(data)
    sio.connect(base_url)
    sio.sleep(2)
    l1.rpc.invoice(10000, "label", "description")  # trigger `invoice_creation` notification
    time.sleep(2)
    sio.disconnect()
    assert len([n for n in notifications if n.find('invoice_creation') > 0]) == 1


def test_clnrest_websocket_rune_readonly(node_factory):
    """Test websocket with default values for options."""
    # start a node with clnrest
    l1, base_url, ca_cert_path = start_node_with_clnrest(node_factory)

    # http session
    http_session = requests.Session()
    http_session.verify = ca_cert_path.as_posix()

    # readonly rune provided => websocket connection and notifications received
    rune_readonly = l1.rpc.createrune(restrictions="readonly")['rune']
    http_session.headers.update({"rune": rune_readonly})
    sio = socketio.Client(http_session=http_session)
    notifications = []

    @sio.event
    def message(data):
        notifications.append(data)
    sio.connect(base_url)
    sio.sleep(2)
    l1.rpc.invoice(10000, "label", "description")  # trigger `invoice_creation` notification
    time.sleep(2)
    sio.disconnect()
    assert len([n for n in notifications if n.find('invoice_creation') > 0]) == 1


def test_clnrest_websocket_rune_getinfo(node_factory):
    """Test websocket with default values for options."""
    # start a node with clnrest
    l1, base_url, ca_cert_path = start_node_with_clnrest(node_factory)

    # http session
    http_session = requests.Session()
    http_session.verify = ca_cert_path.as_posix()

    # rune authorizing getinfo method provided => websocket connection and notifications received
    rune_getinfo = l1.rpc.createrune(restrictions=[["method=getinfo"]])['rune']
    http_session.headers.update({"rune": rune_getinfo})
    sio = socketio.Client(http_session=http_session)
    notifications = []

    @sio.event
    def message(data):
        notifications.append(data)
    sio.connect(base_url)
    sio.sleep(2)
    l1.rpc.invoice(10000, "label", "description")  # trigger `invoice_creation` notification
    time.sleep(2)
    sio.disconnect()
    assert len([n for n in notifications if n.find('invoice_creation') > 0]) == 1


def test_clnrest_websocket_rune_no_getinfo(node_factory):
    """Test websocket with default values for options."""
    # start a node with clnrest
    l1, base_url, ca_cert_path = start_node_with_clnrest(node_factory)

    # http session
    http_session = requests.Session()
    http_session.verify = ca_cert_path.as_posix()

    # with a rune which doesn't authorized getinfo method => no websocket connection and no notification received
    rune_no_getinfo = l1.rpc.createrune(restrictions=[["method/getinfo"]])['rune']
    http_session.headers.update({"rune": rune_no_getinfo})
    sio = socketio.Client(http_session=http_session)
    notifications = []

    @sio.event
    def message(data):
        notifications.append(data)
    sio.connect(base_url)
    sio.sleep(2)
    l1.rpc.invoice(10000, "label", "description")  # trigger `invoice_creation` notification
    time.sleep(2)
    sio.disconnect()
    assert len([n for n in notifications if n.find('invoice_creation') > 0]) == 0
