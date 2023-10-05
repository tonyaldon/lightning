from flask import request, make_response
from flask_restx import Namespace, Resource
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
