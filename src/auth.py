from functools import wraps
from flask import request, g, abort
from jwt import decode, exceptions
import json


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        print(request.headers)
        authorization = request.headers.get("authorization", None)
        if not authorization:
            print('2')

            return json.dumps({'error': 'no authorization token provided'}), 403, {'Content-type': 'application/json'}

        try:
            print('3')

            token = authorization.split(' ')[1]
            resp = decode(token, None, verify=False, algorithms=['HS256'])
            g.user = resp['sub']
        except exceptions.DecodeError as identifier:
            print('4')

            return json.dumps({'error': 'invalid authorization token'}), 403, {'Content-type': 'application/json'}

        print('5')

        return f(*args, **kwargs)

    return wrap
