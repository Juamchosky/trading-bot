import requests
import hmac
import hashlib
import time
import urllib.parse

api_key = "uyjwlfO5npd0tj1BDGBamPMeDGT5wkFOSEaCctq4W0N0c4mbIjU9gzpIUquJcfYc"
api_secret= "VjPwAmrouRZuMzU01KdsYjZaezPWbrSZldwLcaflXzEXwRfUBIhFnKSUKDK8GdtD"
endpoint="https://api.binance.com/api/v3/account"
timestamp = round(time.time()*1000)
params = {
    "timestamp": timestamp
}
querystring = urllib.parse.urlencode(params)
signature = hmac.new(api_secret.encode('utf-8'), msg=querystring.encode('utf-8'), digestmod=hashlib.sha256).hexdigest()
url = f'{endpoint}?{querystring}&signature={signature}'
headers = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-MBX-APIKEY': api_key
}
response = requests.get(url, headers=headers)
print(response.url)
print(response.text)
print(response.request.headers)