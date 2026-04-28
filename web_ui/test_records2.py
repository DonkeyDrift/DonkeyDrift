import sys
import urllib.request
import json

req = urllib.request.Request("http://localhost:8000/api/tub/records?offset=0&limit=10000")
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read().decode('utf-8'))
    records = data['records']
    indexes = [r['_index'] for r in records]
    print(f"Total records: {len(records)}")
    
    print(f"Min index: {min(indexes)}")
    print(f"Max index: {max(indexes)}")
    
    # print some gaps
    for i in range(1, len(indexes)):
        if indexes[i] - indexes[i-1] > 1:
            print(f"Gap from {indexes[i-1]} to {indexes[i]}")
