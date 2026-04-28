import sys
import urllib.request
import json

req = urllib.request.Request("http://localhost:8000/api/tub/records?offset=0&limit=10000")
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode('utf-8'))
    records = data['records']
    indexes = [r['_index'] for r in records]
    print(f"Total records: {len(records)}")
    
    # check 4000 to 5000
    in_range = [i for i in indexes if 4000 <= i <= 5000]
    print(f"Count between 4000 and 5000: {len(in_range)}")
    if in_range:
        print(f"First few in range: {in_range[:5]}")
