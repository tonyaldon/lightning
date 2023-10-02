from ephemeral_port_reserve import reserve
from fixtures import *  # noqa: F401,F403
from pyln.testing.utils import env, wait_for, TEST_NETWORK
import unittest
import requests
from pathlib import Path
import os


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


def test_clnrest_list_methods(node_factory):
    """Test GET request on `/v1/list-methods` end point with default values for options."""
    # start node l1 with clnrest listenning at `base_url` with certificate `ca_cert_path`
    rest_port = str(reserve())
    l1 = node_factory.get_node(options={'rest-port': rest_port})
    base_url = 'https://127.0.0.1:' + rest_port
    wait_for(lambda: l1.daemon.is_in_log(r'plugin-clnrest.py: REST server running at ' + base_url))
    rest_certs_default = Path(l1.rpc.listconfigs()['configs']['rest-certs']['value_str'])
    ca_cert_path = rest_certs_default / 'ca.pem'

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
