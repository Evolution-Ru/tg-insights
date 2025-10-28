# import httpx
import requests
import base64
import copy
import hmac
import json
from time import time
# https://jwt.io/ - JWT Debugger

TEN_MINUTES = 600  # seconds

class TbankClient:
    def __init__(self, api_key, secret_key):
        self.api_key = api_key
        self.secret_key = secret_key

    def get_base_url(self):
        return "https://api.tinkoff.ai:443"

    def request(self, method, endpoint, data=None):
        if data is None:
            data = {}
        headers = {
            'Authorization': f'Bearer {self.__get_token(endpoint)}'
        }
        
        url = self.get_base_url() + endpoint
        try:
            # Таймаут: 10s на соединение, 30s на чтение ответа
            response = requests.request(method, url, headers=headers, json=data, timeout=(10, 30))
            return response
        except requests.exceptions.Timeout as e:
            print(f"⏰ Таймаут T-bank API ({endpoint}): {e}")
            return None
        except Exception as e:
            print(f"❌ Ошибка T-bank API ({endpoint}): {e}")
            return None
        
    def __generate_jwt(self, api_key, secret_key, payload, expiration_time=TEN_MINUTES):
        header = {
            "alg": "HS256",
            "typ": "JWT",
            "kid": api_key
        }
        payload_copy = copy.deepcopy(payload)
        current_timestamp = int(time())
        payload_copy["exp"] = current_timestamp + expiration_time
        # payload_copy["iat"] = current_timestamp
        # payload_copy["nbf"] = current_timestamp
        payload_bytes = json.dumps(payload_copy, separators=(',', ':')).encode("utf-8")
        header_bytes = json.dumps(header, separators=(',', ':')).encode("utf-8")

        data = (base64.urlsafe_b64encode(header_bytes).strip(b'=') + b"." +
                base64.urlsafe_b64encode(payload_bytes).strip(b'='))
        base_secret = base64.urlsafe_b64decode(secret_key) # из примера
        # base_secret = secret_key.encode("utf-8") # "исправленный"
        signature = hmac.new(base_secret, msg=data, digestmod="sha256").digest()
        jwt = data + b"." + base64.urlsafe_b64encode(signature).strip(b'=')
        return jwt.decode("utf-8")
    
    def __get_token(self, endpoint: str):
        auth_payload = {
            "iss": "test_issuer",
            "sub": "test_user",
            "aud": "tinkoff.cloud.longrunning" if endpoint.startswith("/v1/operations") else "tinkoff.cloud.stt"
        }
        return self.__generate_jwt(self.api_key, self.secret_key, auth_payload)