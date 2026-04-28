import sys
import os
import json
sys.path.append(r"c:\Dev\DDC\donkeycar")

from donkeycar.parts.tub_v2 import Tub
from donkeycar.parts.datastore_v2 import Manifest

tub_path = r"c:\Dev\DDC\donkeycar\data\tub" # We don't know the exact tub path, but we can check what's currently open.

# Let's write a small server check script.
import urllib.request
try:
    req = urllib.request.Request("http://localhost:8000/api/tub/records?offset=0&limit=10")
    with urllib.request.urlopen(req) as response:
        print(response.read().decode('utf-8')[:500])
except Exception as e:
    print(f"API Error: {e}")
