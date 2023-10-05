#!/usr/bin/env python3
# For --hidden-import gunicorn.glogging gunicorn.workers.sync
try:
    import sys
    import os
    import re
    import ssl
    import time
    import multiprocessing
    from gunicorn import glogging  # noqa: F401
    from gunicorn.workers import sync  # noqa: F401
    from pyln.client import Plugin
    from pathlib import Path
    from flask import Flask, request, Blueprint, make_response
    from flask_restx import Api, Namespace, Resource
    from flask_cors import CORS
    from gunicorn.app.base import BaseApplication
    from multiprocessing import Process, Queue
    from flask_socketio import SocketIO, disconnect
    import ipaddress
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    import datetime
except ModuleNotFoundError as err:
    # OK, something is not installed?
    import json
    getmanifest = json.loads(sys.stdin.readline())
    print(json.dumps({'jsonrpc': "2.0",
                      'id': getmanifest['id'],
                      'result': {'disable': str(err)}}))
    sys.exit(1)

multiprocessing.set_start_method('fork')


def check_origin(origin):
    rest_cors_origins = plugin.options["rest-cors-origins"]["value"]
    is_whitelisted = False
    if rest_cors_origins[0] == "*":
        is_whitelisted = True
    else:
        for whitelisted_origin in rest_cors_origins:
            try:
                does_match = bool(re.compile(whitelisted_origin).match(origin))
                is_whitelisted = is_whitelisted or does_match
            except Exception as err:
                plugin.log(f"Error from rest-cors-origin {whitelisted_origin} match with {origin}: {err}", "info")
    return is_whitelisted


jobs = {}
app = Flask(__name__)
socketio = SocketIO(app, async_mode="gevent", cors_allowed_origins=check_origin)
msgq = Queue()


def broadcast_from_message_queue():
    while True:
        while not msgq.empty():
            msg = msgq.get()
            if msg is None:
                return
            plugin.log(f"Emitting message: {msg}", "debug")
            socketio.emit("message", msg)
        # Wait for a second after processing all items in the queue
        time.sleep(1)


# Starts a background task which pulls notifications from the message queue
# and broadcasts them to all connected ws clients at one-second intervals.
socketio.start_background_task(broadcast_from_message_queue)


@socketio.on("message")
def handle_message(message):
    plugin.log(f"Received message from client: {message}", "debug")
    socketio.emit('message', {"client_message": message, "session": request.sid})


@socketio.on("connect")
def ws_connect():
    try:
        rune = request.headers.get("rune", None)
        if rune is None:
            raise Exception('{ "error": {"code": 403, "message": "Not authorized: Missing rune"} }')
        plugin.rpc.call("checkrune", {"rune": rune, "method": "getinfo"})
        plugin.log("websocket connection established", "debug")
        return True
    except Exception as err:
        # Logging as error/warn emits the event for all clients
        plugin.log(f"websocket connection failed: {err}", "info")
        disconnect()


# routes

methods_list = []
rpcns = Namespace("RPCs")
payload_model = rpcns.model("Payload", {}, None, False)


@rpcns.route("/list-methods")
class ListMethodsResource(Resource):
    @rpcns.response(200, "Success")
    @rpcns.response(500, "Server error")
    def get(self):
        """Get the list of all valid rpc methods, useful for Swagger to get human readable list without calling lightning-cli help"""
        try:
            help_response = plugin.rpc.call("help", [])
        except Exception as err:
            plugin.log(f"Error: {err}", "debug")
            return {"error": err.error}, 500

        commands = help_response["help"]
        line = "\n---------------------------------------------------------------------------------------------------------------------------------------------------------------------------\n\n"
        html_content = line.join(
            "Command: {}\n Category: {}\n Description: {}\n Verbose: {}\n".format(
                cmd["command"], cmd["category"], cmd["description"], cmd["verbose"])
            for cmd in commands)
        response = make_response(html_content)
        response.headers["Content-Type"] = "text/html"
        return response


@rpcns.route("/<rpc_method>")
class RpcMethodResource(Resource):
    @rpcns.doc(security=[{"rune": []}])
    @rpcns.doc(params={"rpc_method": (f"Name of the RPC method to be called")})
    @rpcns.expect(payload_model, validate=False)
    @rpcns.response(201, "Success")
    @rpcns.response(500, "Server error")
    def post(self, rpc_method):
        """Call any valid core lightning method (check list-methods response)"""
        if request.is_json:
            if len(request.data) != 0:
                rpc_params = request.get_json()
            else:
                rpc_params = {}
        else:
            rpc_params = request.form.to_dict()

        try:
            rune = request.headers.get("rune", None)
            if rune is None:
                err = {"code": 403, "message": "Not authorized: Missing rune"}
                plugin.log(f"Error: {repr(err)}", "debug")
                return {"error": err}, 401
            plugin.rpc.call("checkrune", {"rune": rune, "method": rpc_method, "params": rpc_params})
        except Exception as err:
            plugin.log(f"Error: {err}", "debug")
            return {"error": err.error}, 401

        try:
            return plugin.rpc.call(rpc_method, rpc_params), 201
        except Exception as err:
            plugin.log(f"Error: {err}", "debug")
            return {"error": err.error}, 500


# certs

def save_cert(entity_type, cert, private_key, certs_path):
    """Serialize and save certificates and keys.
    `entity_type` is either "ca", "client" or "server"."""
    with open(os.path.join(certs_path, f"{entity_type}.pem"), "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(os.path.join(certs_path, f"{entity_type}-key.pem"), "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()))


def create_cert_builder(subject_name, issuer_name, public_key, rest_host):
    return (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(issuer_name)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=10 * 365))  # Ten years validity
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("cln"),
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address(rest_host))
        ]), critical=False)
    )


def generate_cert(entity_type, ca_subject, ca_private_key, rest_host, certs_path):
    # Generate Key pair
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    # Generate Certificates
    if isinstance(ca_subject, x509.Name):
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"cln rest {entity_type}")])
        cert_builder = create_cert_builder(subject, ca_subject, public_key, rest_host)
        cert = cert_builder.sign(ca_private_key, hashes.SHA256())
    else:
        ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"cln Root REST CA")])
        ca_private_key, ca_public_key = private_key, public_key
        cert_builder = create_cert_builder(ca_subject, ca_subject, ca_public_key, rest_host)
        cert = (
            cert_builder
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_private_key, hashes.SHA256())
        )

    os.makedirs(certs_path, exist_ok=True)
    save_cert(entity_type, cert, private_key, certs_path)
    return ca_subject, ca_private_key


def generate_certs(plugin, rest_host, certs_path):
    ca_subject, ca_private_key = generate_cert("ca", None, None, rest_host, certs_path)
    generate_cert("client", ca_subject, ca_private_key, rest_host, certs_path)
    generate_cert("server", ca_subject, ca_private_key, rest_host, certs_path)
    plugin.log(f"Certificates Generated!", "debug")


def set_application_options(plugin):
    rest_port = plugin.options["rest-port"]["value"]
    rest_host = plugin.options["rest-host"]["value"]
    rest_protocol = plugin.options["rest-protocol"]["value"]
    rest_certs = plugin.options["rest-certs"]["value"]
    plugin.log(f"REST Server is starting at {rest_protocol}://{rest_host}:{rest_port}", "debug")
    if rest_protocol == "http":
        # Assigning only one worker due to added complexity between gunicorn's multiple worker process forks
        # and websocket connection's persistance with a single worker.
        options = {
            "bind": f"{rest_host}:{rest_port}",
            "workers": 1,
            "worker_class": "geventwebsocket.gunicorn.workers.GeventWebSocketWorker",
            "timeout": 60,
            "loglevel": "warning",
        }
    else:
        cert_file = Path(f"{rest_certs}/client.pem")
        key_file = Path(f"{rest_certs}/client-key.pem")
        if not cert_file.is_file() or not key_file.is_file():
            plugin.log(f"Certificate not found at {rest_certs}. Generating a new certificate!", "debug")
            generate_certs(plugin, rest_host, rest_certs)
        try:
            plugin.log(f"Certs Path: {rest_certs}", "debug")
        except Exception as err:
            raise Exception(f"{err}: Certificates do not exist at {rest_certs}")
        # Assigning only one worker due to added complexity between gunicorn's multiple worker process forks
        # and websocket connection's persistance with a single worker.
        options = {
            "bind": f"{rest_host}:{rest_port}",
            "workers": 1,
            "worker_class": "geventwebsocket.gunicorn.workers.GeventWebSocketWorker",
            "timeout": 60,
            "loglevel": "warning",
            "certfile": cert_file.as_posix(),
            "keyfile": key_file.as_posix(),
            "ssl_version": ssl.PROTOCOL_TLSv1_2
        }
    return options


# App

def create_app():
    global app
    app.config["SECRET_KEY"] = os.urandom(24).hex()
    authorizations = {
        "rune": {"type": "apiKey", "in": "header", "name": "Rune"}
    }
    CORS(app, resources={r"/*": {"origins": plugin.options["rest-cors-origins"]["value"]}})
    blueprint = Blueprint("api", __name__)
    api = Api(blueprint, version="1.0", title="Core Lightning Rest", description="Core Lightning REST API Swagger", authorizations=authorizations, security=["rune"])
    app.register_blueprint(blueprint)
    api.add_namespace(rpcns, path="/v1")


@app.after_request
def add_csp_headers(response):
    try:
        response.headers['Content-Security-Policy'] = plugin.options["rest-csp"]["value"]
        return response
    except Exception as err:
        plugin.log(f"Error from rest-csp config: {err}", "info")


class CLNRestApplication(BaseApplication):
    def __init__(self, app, options=None):
        rest_port = plugin.options["rest-port"]["value"]
        rest_host = plugin.options["rest-host"]["value"]
        rest_protocol = plugin.options["rest-protocol"]["value"]
        self.application = app
        self.options = options or {}
        plugin.log(f"REST server running at {rest_protocol}://{rest_host}:{rest_port}", "info")
        super().__init__()

    def load_config(self):
        config = {key: value for key, value in self.options.items()
                  if key in self.cfg.settings and value is not None}
        for key, value in config.items():
            self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


def worker():
    global app
    options = set_application_options(plugin)
    create_app()
    CLNRestApplication(app, options).run()


def start_server():
    global jobs
    rest_port = plugin.options["rest-port"]["value"]
    if rest_port in jobs:
        return False, "server already running"
    p = Process(
        target=worker,
        args=[],
        name="server on port {}".format(rest_port),
    )
    p.daemon = True
    jobs[rest_port] = p
    p.start()
    return True


# plugin

plugin = Plugin(autopatch=False)

rest_certs = Path(os.getcwd()) / 'clnrest'

plugin.add_option(name="rest-certs", default=rest_certs.as_posix(), description="Path for certificates (for https)", opt_type="string", deprecated=False)
plugin.add_option(name="rest-protocol", default="https", description="REST server protocol", opt_type="string", deprecated=False)
plugin.add_option(name="rest-host", default="127.0.0.1", description="REST server host", opt_type="string", deprecated=False)
plugin.add_option(name="rest-port", default=None, description="REST server port to listen", opt_type="int", deprecated=False)
plugin.add_option(name="rest-cors-origins", default="*", description="Cross origin resource sharing origins", opt_type="string", deprecated=False, multi=True)
plugin.add_option(name="rest-csp", default="default-src 'self'; font-src 'self'; img-src 'self' data:; frame-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline';", description="Content security policy (CSP) for the server", opt_type="string", deprecated=False)


@plugin.init()
def init(options, configuration, plugin):
    if "rest-port" not in options:
        return {"disable": "`rest-port` option is not configured"}
    start_server()


@plugin.subscribe("*")
def on_any_notification(request, **kwargs):
    plugin.log("Notification: {}".format(kwargs), "debug")
    if request.method == 'shutdown':
        # A plugin which subscribes to shutdown is expected to exit itself.
        sys.exit(0)
    else:
        msgq.put(str(kwargs))


try:
    plugin.run()
except ValueError as err:
    plugin.log("Unable to subscribe to all events. Feature available with CLN v23.08 and above: {}".format(err), "warn")
except (KeyboardInterrupt, SystemExit):
    pass
