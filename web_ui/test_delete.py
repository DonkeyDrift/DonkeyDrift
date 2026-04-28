import urllib.request
import json

req = urllib.request.Request("http://localhost:8000/api/tub/delete", 
                             data=json.dumps({"indexes": [4000]}).encode('utf-8'),
                             headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req) as response:
        print(response.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
