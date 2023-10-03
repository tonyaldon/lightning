import json5
from flask import request, make_response
from flask_restx import Namespace, Resource
from .shared import call_rpc_method, verify_rune
from .rpc_plugin import plugin

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
        try:
            is_valid_rune = verify_rune(plugin, request)

            if "error" in is_valid_rune:
                plugin.log(f"Error: {is_valid_rune}", "error")
                raise Exception(is_valid_rune)

        except Exception as err:
            return json5.loads(str(err)), 401

        try:
            if request.is_json:
                if len(request.data) != 0:
                    payload = request.get_json()
                else:
                    payload = {}
            else:
                payload = request.form.to_dict()
            return call_rpc_method(plugin, rpc_method, payload), 201

        except Exception as err:
            plugin.log(f"Error: {err}", "debug")
            return json5.loads(str(err)), 500
