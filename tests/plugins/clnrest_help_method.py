#!/usr/bin/env python3
"""
This plugin is used to test `GET /v1/list-methods` request of clnrest plugin.
Under the hood, this GET request does a call to the `help` method.  To check
that we correctly catch errors produced by that call we "rebind" the `help`
method to return an error.
"""
from pyln.client import Plugin

plugin = Plugin()


@plugin.hook("rpc_command")
def on_rpc_command(plugin, rpc_command, **kwargs):
    request = rpc_command
    if request["method"] == "help":
        return {"return":
                {"error":
                 {"code": -1, "message": "testing clnrest `GET /v1/list-methods` request"}}}
    return {"result": "continue"}


plugin.run()
