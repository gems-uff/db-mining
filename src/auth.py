import json
from functools import wraps

import jwt
import requests

from flask import request, g
from jwt import decode, exceptions
from jwt.algorithms import RSAAlgorithm

with open('./web/src/authentication.json') as json_file:
    auth_okta = json.load(json_file)

KEYS_URL = auth_okta['issuer'] + '/v1/keys?client_id=' + auth_okta['client_id']
CLIENT_ID = auth_okta['client_id']
ALGORITHMS = ['RS256']
public_keys = {}


def verify(authorization):
    token = authorization.split(' ')[1]
    kid = jwt.get_unverified_header(token)['kid']
    resp = decode(token, public_keys[kid], audience=CLIENT_ID, algorithms=ALGORITHMS)
    return resp['name']


def load_keys():
    jwks = requests.get(KEYS_URL).json()
    for jwk in jwks['keys']:
        kid = jwk['kid']
        public_keys[kid] = RSAAlgorithm.from_jwk(json.dumps(jwk))


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        authorization = request.headers.get("authorization", None)
        if not authorization:
            return json.dumps({'error': 'no authorization token provided'}), 403, {'Content-type': 'application/json'}

        try:
            g.user = verify(authorization)
        except exceptions.DecodeError:
            try:  # The cached keys may have expired. Try to reload the keys.
                load_keys()
                g.user = verify(authorization)
            except exceptions.DecodeError:
                return json.dumps({'error': 'invalid authorization token'}), 403, {'Content-type': 'application/json'}

        return f(*args, **kwargs)

    return wrap


load_keys()
