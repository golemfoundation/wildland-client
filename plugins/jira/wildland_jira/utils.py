import base64
from typing import Union, List, Dict


def _stringify_param(key, params):
    value_str = ','.join(params[key]) if isinstance(params[key], list) else params[key]
    param_str = f'{key}={value_str}'
    return param_str


def stringify_query_params(params: Dict[str, Union[str, List[str]]]) -> str:
    if len(params) == 0:
        return ''

    return '?' + '&'.join([_stringify_param(key, params) for key in params])


def encode_basic_auth(username: str, personal_token: str) -> str:
    assert username is not None and len(username)
    assert personal_token is not None and len(personal_token)

    basic_token = f'{username}:{personal_token}'
    basic_token = base64.b64encode(basic_token.encode('utf-8'))

    return str(basic_token, "utf-8")
