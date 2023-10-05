---
title: "REST APIs"
slug: "rest"
hidden: false
createdAt: "2023-09-05T09:54:01.784Z"
updatedAt: "2023-10-05T06:36:32.784Z"
---

# CLNRest

CLNRest is a lightweight Python-based Core Lightning plugin that
transforms RPC calls into a REST service.  It also broadcasts Core
Lightning notifications to listeners connected to its websocket
server.

- [Get started](doc:rest#get-started)
- [Installation](doc:rest#installation)
- [Configuration](doc:rest#configuration)
- [Differences with previous versions](doc:rest#differences-with-previous-versions)
- [REST API Reference Pro-tip](doc:rest#rest-api-reference-pro-tip)
- [Websocket client examples](doc:rest#websocket-client-examples)

## Get started

`clnrest` being a builtin plugin (from v23.08), it comes already
installed with Core Lightning.  However, its python dependencies are
not, and must be installed independently of Core Lightning (See
[Installation](doc:rest#installation) section).

### Starting `clnrest` plugin

Once the dependencies installed, we can enable `clnrest` plugin by
specifying a port to listen to with `rest-port` option when we start
`lightningd`.

For instance, if we want `clnrest` web server to listen to on the port
`3010` with `lightningd` running on `regtest`, we can run the
following command:

```shell
lightningd --regtest --rest-port=3010
```

Note: This assumes that we have already `bitcoind` running the
`regtest` chain.  If we don't we can do it with `-regtest` flag of
`bitcoind`.  And, if we want to enable it on our node running on
mainnet, we just have to run the same command without `--regtest`
flag.

By default, `clnrest` web server is now running at
`https://127.0.0.1:3010` and if `client.pem` or `client-key.pem` files
were not in `~/.lightning/regtest/clnrest/` directory, then
self-signed certificates have been created and used (See [Differences
with previous versions](doc:rest#differences-with-previous-versions)).

### GET /v1/list-methods

With that said, we can now list the available JSON-RPC methods by
sending a `GET /v1/list-methods` request to the server.  To do that we
can run the following `curl` command:

```shell
curl --cacert ~/.lightning/regtest/clnrest/ca.pem \
     --request GET \
     --url https://127.0.0.1:3010/v1/list-methods
```

If we prefer, we can bypass SSL certificate verification using the
`--insecure` flag like this:

```shell
curl --insecure --request GET --url https://127.0.0.1:3010/v1/list-methods
```

We can learn about the `clnrest` REST
interface using the Swagger user interface available at
<https://127.0.0.1:3010>.

Without running `clnrest` ourselves we can also issue `GET
/v1/list-methods` requests and learn about the `clnrest` REST
interface at [List of valid RPC
methods](ref:get_list_methods_resource) page.

If we could just list the JSON-RPC methods of the node it would be
boring.  But it isn't.

### POST /v1/rpc_method

Any JSON-RPC method `rcp_method` listed by `list-methods` can be the
endpoint of a POST request `/v1/rpc_method`.

For instance:

- we can issue the `POST /v1/getinfo` request to get information about
  the node (running the `getinfo` method) and
- we can also issue the `POST /v1/invoice` request to generate an
  invoice (running the `invoice` method).

We can learn more about those POST requests on [Call an RPC method on
a node](ref:post_rpc_method_resource) page.

Those POST requests require the use of a `rune` with the correct
authorization for the given JSON-RPC method.

Let's create a `rune` that only authorize running the
`getinfo` method on the node using the command (see
[createrune](ref:lightning-createrune))

```shell
lightning-cli --regtest createrune null '[["method=getinfo"]]'
```

which prints out:

```json
{
   "rune": "9CsFtt9kKMTzzWxSEB31CFmOnCR6ZEKxfiQAnOmfdUQ9MCZtZXRob2Q9Z2V0aW5mbw==",
   "unique_id": "0"
}
```

Then, with that `rune` we get the node's information by
sending a `POST /v1/getinfo` request to the server.  To do that
we can run the following `curl` command

```shell
curl --cacert ~/.lightning/regtest/clnrest/ca.pem \
     --request POST \
     --url https://127.0.0.1:3010/v1/getinfo \
     --header 'Rune: 9CsFtt9kKMTzzWxSEB31CFmOnCR6ZEKxfiQAnOmfdUQ9MCZtZXRob2Q9Z2V0aW5mbw=='
```

which prints out (pretty printed):

```json
{
   "id": "039e3f3829de4dbce7fd15a366cb8a5ad38845ac1159d4168c12d97c3f8c70040d",
   "alias": "ANGRYPHOTO",
   "color": "039e3f",
   "num_peers": 0,
   "num_pending_channels": 0,
   "num_active_channels": 0,
   "num_inactive_channels": 0,
   "address": [...],
   "binding": [...],
   "version": "...",
   "blockheight": 2,
   "network": "regtest",
   "fees_collected_msat": 0,
   "lightning-dir": "...",
   "our_features": {...}
}
```

Now, if we send a `POST /v1/invoice` request to the server in order
to create an invoice but with the same `rune` that only allows to run
the `getinfo` on the node we'll get an error as we can see by running
the following command


```shell
curl --cacert ~/.lightning/regtest/clnrest/ca.pem \
     --request POST \
     --url https://127.0.0.1:3010/v1/invoice \
     --header 'Rune: 9CsFtt9kKMTzzWxSEB31CFmOnCR6ZEKxfiQAnOmfdUQ9MCZtZXRob2Q9Z2V0aW5mbw==' \
     --header 'content-type: application/json' \
     --data '{"amount_msat": "10000", "label": "my label", "description": "my description"}'
```

which prints out:

```json
{"error": {"code": 1502, "message": "Not permitted: method is not equal to getinfo"}}
```

Indeed, we need a `rune` that authorizes the `invoice` method to
generate an invoice.  Let's create one like this:

```shell
lightning-cli --regtest createrune null '[["method=invoice"]]'
```

We get the following ouptut:

```json
{
   "rune": "WyDb7h26QH6yRuaBDSSZpkh633Vypq-XyZ5gT4B10Rk9MSZtZXRob2Q9aW52b2ljZQ==",
   "unique_id": "1"
}
```

Now, we can use it as value of `Rune` header in that following POST request:

```shell
curl --cacert ~/.lightning/regtest/clnrest/ca.pem \
     --request POST \
     --url https://127.0.0.1:3010/v1/invoice \
     --header 'Rune: WyDb7h26QH6yRuaBDSSZpkh633Vypq-XyZ5gT4B10Rk9MSZtZXRob2Q9aW52b2ljZQ==' \
     --header 'content-type: application/json' \
     --data '{"amount_msat": "10000", "label": "my label", "description": "my description"}'
```

Running the previous command worked as expected and gave us the
following invoice (we've pretty printed it):

```json
{
  "payment_hash": "08870b76a0b1a5b72d59d602d0469fe02e5898a02d667336d8bc1d611c87159a",
  "expires_at": 1697026346,
  "bolt11": "lnbcrt100n1...h4qcptg53mm",
  "payment_secret": "822473c85d2bf4e9c6e1ae1d7978491be10261e87811ed360c7a63d12546bc60",
  "created_index": 1,
  "warning_capacity": "Insufficient incoming channel capacity to pay invoice"
}
```

Note that if we want to generate an unrestricted rune that allows
to execute any command, we can simply use the command `createrune`
with no arguments like this:

```shell
lightning-cli --regtest createrune
```

### Websocket server

When we enable `clnrest` we can also connect to its websocket server
and receive all [Core Lightning notifications](doc:event-notifications).
`clnrest` queues up notifications received for a second then
broadcasts them to listeners.

Continuing with our node running on regtest, the web server
running at `https://127.0.0.1:3010` and the certificate authority
being `~/.lightning/regtest/clnrest/ca.pem`, we can connect to the
websocket available at `https://127.0.0.1:3010`.

To connect to that websocket we must provide `rune` that authorizes
running the `getinfo` method (See [Differences with previous
versions](doc:rest#differences-with-previous-versions)).   We could
generate one as we did above but we are going to do it differently
using the restriction `readonly` by running the following command

```shell
lightning-cli --regtest createrune null readonly
```

which prints out:

```json
{
   "rune": "nklUVNP3smggD6OjqfcE3AtnL9zIU3igkQPEYaU1mDY9MiZtZXRob2RebGlzdHxtZXRob2ReZ2V0fG1ldGhvZD1zdW1tYXJ5Jm1ldGhvZC9saXN0ZGF0YXN0b3Jl",
   "unique_id": "2"
}
```

Now in a file named `ws-file.js` we implement the following Node JS
websocket client that will be able to connect to our websocket server
running at `https://127.0.0.1:3010`:

```javascript ws-file.js
const https = require("https");
const os = require("os")
const path = require("path");
const ca = path.join(os.homedir(), ".lightning/regtest/clnrest/ca.pem")
const rootCas = require("ssl-root-cas").create();
rootCas.addFile(ca);
const io = require("socket.io-client");

const socket = io.connect("https://127.0.0.1:3010", {
  extraHeaders: {
    Rune:
      "nklUVNP3smggD6OjqfcE3AtnL9zIU3igkQPEYaU1mDY9MiZtZXRob2RebGlzdHxtZXRob2ReZ2V0fG1ldGhvZD1zdW1tYXJ5Jm1ldGhvZC9saXN0ZGF0YXN0b3Jl",
  },
  agent: https.globalAgent,
});

socket.on("connect", function () {
  console.log("Websocket connection established at https://127.0.0.1:3010");
});

socket.on("message", function (data) {
  console.log("Notification: ", data);
});
```

Then we install the Node JS dependencies:

```shell
node install ssl-root-cas socket.io-client
```

Finally, we can connect to `clnrest` websocket server like this:

```shell
node ws-client.js
```

We got the following output and the terminal hangs waiting for
incoming messages (Core Lightning notifications) from `clnrest`:

```
Websocket connection established at https://127.0.0.1:3010
```

In another terminal, we create an invoice like this:

```shell
lightning-cli --regtest invoice 10000 'another label' 'another description'
```

This triggered an `invoice_creation` notification that has been
forwarded to `clnrest` plugin which queued it up for a second and then
broadcasted it to our Node JS listener.  We can see in the terminal
running `ws-client.js` script that the `invoice_creation` message has
been received:

```
Websocket connection established at https://127.0.0.1:3010
Notification:  {'invoice_creation': {'msat': '10000msat', 'preimage': 'a78b43991662361158a6d6becf9f05e60a0ac4fa825bd4e4250a4df92259d649', 'label': 'another label'}}
```

See [Websocket client examples](doc:rest#websocket-client-examples)
section for more examples.

## Installation

### Python dependencies

`clnrest` being a builtin plugin (from v23.08), it comes already
installed with Core Lightning.  However, its python dependencies are
not, and must be installed independently of Core Lightning.

This can be done like this

```shell
pip install flask flask_restx flask-socketio gunicorn gevent gevent-websocket pyln-client
```

or using the `requirements.txt` file that can be found in Core
Lightning repository ([plugins/clnrest/requirements.txt](https://github.com/ElementsProject/lightning/blob/master/plugins/clnrest/requirements.txt))
like this:

```shell
pip install -r requirements.txt
```

### If you are running c-lightning-REST plugin

If you are running [c-lightning-REST](https://github.com/Ride-The-Lightning/c-lightning-REST)
plugin, to avoid any conflict with `clnrest` plugin you should
explicitly disable it either by starting `lightningd` with
`--disable-plugin=clnrest.py` or by adding the line
`disable-plugin=clnrest.py` to your config file.

Why?

Because `clnrest` and `c-lightning-REST` both define the options
`rest-port` and `rest-protocol` and this is not authorized by Core
Lightning plugin system.

Specifically, two things can happen if you try to use
`c-lightning-REST` without disabling `clnrest`:

- If `clnrest` Python dependencies are not installed, `clnrest` won't
  start due to a Python error like this `No module name...`, so there
  will be no conflict regarding the options and `c-lightning-REST`
  should start normally.
- If for some reason `clnrest` Python dependencies are installed on
  your system, `lightningd` won't even start due to both plugins trying
  to define the same options.  The error should looks like this

  ```
  error starting plugin '...': option name 'rest-protocol' is already taken
  ```

  or this:

  ```
  error starting plugin '...': option name 'rest-port is already taken
  ```

## Configuration

- `--rest-port`: Sets the REST server port to listen to (`3010` is
  common).  If not specified, `clnrest` plugin is not started.
- `--rest-protocol`: Specifies the REST server protocol.  Default is `https`.
- `--rest-host`: Defines the REST server host.  Default is `127.0.0.1`.
- `--rest-certs`: Defines the path for HTTPS cert & key.  Default path
  is 'lightning-dir/network/clnrest' depending on `lightning-dir`
  and `networt` values (default: `$HOME/.lightning/bitcoin/clnrest`).
  If `client.pem` and `client-key.pem` are not defined in that
  directory, new self-signed certificates will be generated.  See
  [Differences with previous versions](doc:rest#differences-with-previous-versions)
- `--rest-csp`: Creates a whitelist of trusted content sources that
  can run on a webpage and helps mitigate the risk of attacks.  Default
  CSP is set as:

   ```
   default-src 'self'; font-src 'self'; img-src 'self' data:; frame-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline';
   ```

   Example CSP:

   ```
   rest-csp=default-src 'self'; font-src 'self'; img-src 'self'; frame-src 'self'; style-src 'self'; script-src 'self';
   ```

- `--rest-cors-origins`:   Define multiple origins which are allowed
  to share resources on web pages to a domain different from the one
  that served the web page.   Default is `*` which allows all
  origins.  Example to define multiple origins:

   ```
   rest-cors-origins=https://localhost:5500
   rest-cors-origins=http://192.168.1.50:3030
   rest-cors-origins=https?://127.0.0.1:([0-9]{1,4}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5])

   ```

## Differences with previous versions

### Certificates

When `clnrest` is started with `rest-protocol` being `https` (the
default), `clnrest` looks for certificates in the directory specified
by `--rest-certs` to use them or creates new ones in that same
directory if they don't already exist.

In version 23.08 and 23.08.1 this directory was by default the same as
where we can find the `lightning-rpc` file (which is also where the
plugin [cln-grpc](doc:cln-grpc) looks for certificates).

In newer versions the default value for `--rest-certs` option is the
path 'lightning-dir/network/clnrest' depending on `lightning-dir` and
`networt` values (default: `$HOME/.lightning/bitcoin/clnrest`).

So if we want the old behavior in order to use the same certificates
as those used by the `cln-grpc` plugin, we must set `--rest-certs`
accordingly (for instance `$HOME/.lightning/bitcoin` in the default
case).

### POST requests

In version v23.08, the POST requests required the following headers:

- a `Rune` with a valid `rune` and
- a `Nodeid` with the node's id.

In version v23.08.1 and after, only the `Rune` header is required in
the POST requests.

Note that we can still send the `Nodeid` header for backwards
compatiblity, but it is completely ignored.

### Websocket

In version 23.08 and 23.08.1 the websocket connection didn't require
any authentication.

In newer versions, the websocket connection require a `rune` that
authorizes to run the `getinfo` method.  There is at least 3 ways to
create such a rune that we list below from the less permissive to the
more permissive:

```shell
lightning-cli createrune null '[["method=getinfo"]]'
lightning-cli createrune null readonly
lightning-cli createrune
```

See [createrune](ref:lightning-createrune).

## REST API Reference Pro-tip

[REST API REFERENCE](ref:get_list_methods_resource) can also be tested
with your own server.

By default, the base URL is set to connect with the Blockstream-hosted
regtest node.

However, it can be configured to connect to your own cln node as
described below:

- Select `{protocol}://{ip}:{port}/` from Base URL dropdown on the
  right section of the page.
- Click on the right side of the dropdown and configure `protocol`,
  `ip` and `port` values according to your setup.
- The `ip` should be configured with your system's public IP address.
- Default `rest-host` is `127.0.0.1` but this testing will require it
  to be `0.0.0.0`.

Note: This setup is for **testing only**.  It is **highly recommended**
to test with _non-mainnet_ (regtest/testnet) setup only.

## Websocket client examples

In the following examples we assume that:

- the websocket server is available at `http://127.0.0.1:3010`.  This
  can be done by starting `lightningd` with these options:

  ```shell
  lightningd --rest-port=3010 --rest-protocol=http
  ```

- we've generated a `rune` which authorize running the `getinfo`
  method (we refer to it as `<rune-authorizing-getinfo>`).  This can
  be achieved by running the following command:

  ```shell
  lightning-cli createrune null readonly
  ```

  See [Differences with previous versions](doc:rest#differences-with-previous-versions).

### Python

Dependencies: `python-socketio` and `requests`.

```python
import socketio
import requests

http_session = requests.Session()
http_session.verify = True
http_session.headers.update({
    "rune": "<rune-authorizing-getinfo>"
})
sio = socketio.Client(http_session=http_session)

@sio.event
def connect():
    print("Client Connected")

@sio.event
def disconnect():
    print(f"Server connection closed.\nCheck CLN logs for errors if unexpected")

@sio.event
def message(data):
    print(f"Message from server: {data}")

@sio.event
de
f error(err):
    print(f"Error from server: {err}")

sio.connect('http://127.0.0.1:3010')

sio.wait()
```

### NodeJS

Dependencies: `socket.io-client`.

```javascript
const io = require('socket.io-client');

const socket = io.connect("http://127.0.0.1:3010", {
  extraHeaders: {
    Rune:
    "<rune-authorizing-getinfo>",
  }
});

socket.on('connect', function() {
  console.log('Client Connected');
});

socket.on('disconnect', function(reason) {
  console.log('Server connection closed: ', reason, '\nCheck CLN logs for errors if unexpected');
});

socket.on('message', function(data) {
  console.log('Message from server: ', data);
});

socket.on('error', function(err) {
  console.error('Error from server: ', err);
});
```

### HTML

```html
<!DOCTYPE html>
<html>
<head>
    <title>Socket.IO Client Example</title>
    <script src="https://cdn.socket.io/4.0.1/socket.io.min.js"></script>
</head>
<body>
    <h1>Socket.IO Client Example</h1>
    <hr>
    <h3>Status:</h3>
    <div id="status">Not connected</div>
    <hr>
    <h3>Send Message:</h3>
    <input type="text" id="messageInput" placeholder="Type your message here">
    <button onclick="sendMessage()">Send</button>
    <hr>
    <h3>Received Messages:</h3>
    <div id="messages"></div>
    <script>
        const statusElement = document.getElementById('status');
        const messagesElement = document.getElementById('messages');

        const socket = io('http://127.0.0.1:3010', {extraHeaders: {rune: "<rune-authorizing-getinfo>"}});

        socket.on('connect', () => {
            statusElement.textContent = 'Client Connected';
        });

        socket.on('disconnect', (reason) => {
            statusElement.textContent = 'Server connection closed: ' + reason + '\n Check CLN logs for errors if unexpected';
        });

        socket.on('message', (data) => {
            const item = document.createElement('li');
            item.textContent = JSON.stringify(data);
            messagesElement.appendChild(item);
            console.log('Message from server: ', data);
        });

        socket.on('error', (err) => {
            const item = document.createElement('li');
            item.textContent = JSON.stringify(err);
            messagesElement.appendChild(item);
            console.error('Error from server: ', err);
        });

        function sendMessage() {
            const message = messageInput.value;
            if (message) {
                socket.emit('message', message);
                messageInput.value = '';
            }
        }
    </script>
</body>
</html>
```
