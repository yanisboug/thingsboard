"""
Helper script to create test devices for profiling scenarios
"""
import requests
import sys

BASE_URL = "http://localhost"

def create_devices(count=50):
    print(f"Creating {count} test devices...")

    # Login
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "tenant@thingsboard.org", "password": "tenant"}
    )

    if resp.status_code != 200:
        print(f"✗ Login failed: {resp.text}")
        return

    token = resp.json()["token"]
    headers = {"X-Authorization": f"Bearer {token}"}

    # Get default device profile
    resp = requests.get(
        f"{BASE_URL}/api/deviceProfiles?pageSize=1&page=0",
        headers=headers
    )

    if resp.status_code != 200:
        print(f"✗ Failed to get device profile: {resp.text}")
        return

    profile_id = resp.json()["data"][0]["id"]["id"]

    # Create devices
    created = 0
    for i in range(count):
        device_data = {
            "name": f"LoadTestDevice{i+1}",
            "type": "default",
            "label": f"Test Device {i+1}",
            "deviceProfileId": {"entityType": "DEVICE_PROFILE", "id": profile_id}
        }

        resp = requests.post(
            f"{BASE_URL}/api/device",
            headers=headers,
            json=device_data
        )

        if resp.status_code == 200:
            created += 1
            if (i + 1) % 10 == 0:
                print(f"Created {i+1}/{count} devices...")
        else:
            # Check if device already exists
            if "already exists" not in resp.text:
                print(f"✗ Failed to create device {i+1}: {resp.text}")

    print(f"\n✅ Created {created} devices successfully!")
    print(f"You can now run the profiling scenarios:")
    print(f"  - python scenario1_websocket_load.py 150")
    print(f"  - python scenario2_telemetry_ingestion.py 30 200")
    print(f"  - python scenario3_rest_api_burst.py 40 20")

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    create_devices(count)
