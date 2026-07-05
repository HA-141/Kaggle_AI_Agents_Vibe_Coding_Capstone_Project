import subprocess
import os

# Get the directory of this script
base_dir = os.path.dirname(os.path.abspath(__file__))

servers = [
    "clinical_trials.py",
    "cms_prescriber.py",
    "gdelt.py",
    "price_data.py",
    "pubmed.py",
    "usaspending.py"
]

processes = []
for server in servers:
    print(f"Starting {server}...")
    p = subprocess.Popen(["python", os.path.join(base_dir, server)])
    processes.append(p)

print("All servers started. Press Ctrl+C to stop.")
for p in processes:
    p.wait()