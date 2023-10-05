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

    from pathlib import Path
    from flask import Flask, request, Blueprint
    from flask_restx import Api
    from flask_cors import CORS
    from gunicorn.app.base import BaseApplication
    from multiprocessing import Process, Queue
    from flask_socketio import SocketIO, disconnect
    from utilities.generate_certs import generate_certs
    from utilities.rpc_routes import rpcns
    from utilities.rpc_plugin import plugin
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
