CERTS_PATH, REST_PROTOCOL, REST_HOST, REST_PORT, REST_CSP, REST_CORS_ORIGINS = "", "", "", "", "", []


def set_config(options):
    if 'rest-port' not in options:
        return "`rest-port` option is not configured"
    global CERTS_PATH, REST_PROTOCOL, REST_HOST, REST_PORT, REST_CSP, REST_CORS_ORIGINS
    CERTS_PATH = str(options["rest-certs"])
    REST_PROTOCOL = str(options["rest-protocol"])
    REST_HOST = str(options["rest-host"])
    REST_PORT = int(options["rest-port"])
    REST_CSP = str(options["rest-csp"])
    cors_origins = options["rest-cors-origins"]
    REST_CORS_ORIGINS.clear()
    for origin in cors_origins:
        REST_CORS_ORIGINS.append(str(origin))

    return None
