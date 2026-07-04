import requests
import sys

BASE_URL = "http://127.0.0.1:8000"

print("1. Registering test user...")
reg_data = {
    "email": "test_mfa_user@example.com",
    "password": "Password123",
    "mfa_method": "email"
}
res = requests.post(f"{BASE_URL}/auth/register", json=reg_data)
print(f"Register status: {res.status_code}")
print(f"Register body: {res.text}")

temp_token = None
if res.status_code == 200:
    temp_token = res.json().get("temp_token")
elif res.status_code == 400 and "already exists" in res.text:
    print("User already exists, attempting login...")
    login_data = {
        "email": "test_mfa_user@example.com",
        "password": "Password123"
    }
    res = requests.post(f"{BASE_URL}/auth/login", json=login_data)
    print(f"Login status: {res.status_code}")
    print(f"Login body: {res.text}")
    temp_token = res.json().get("temp_token")

if not temp_token:
    print("Error: No temp_token retrieved!")
    sys.exit(1)

print(f"Using temp_token: {temp_token[:20]}...")

print("2. Attempting to resend OTP...")
res = requests.post(f"{BASE_URL}/auth/resend-otp", json={"temp_token": temp_token})
print(f"Resend status: {res.status_code}")
print(f"Resend body: {res.text}")
