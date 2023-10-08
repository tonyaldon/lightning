from ephemeral_port_reserve import reserve
from fixtures import *  # noqa: F401,F403
from pyln.testing.utils import wait_for
import requests
from pathlib import Path


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
