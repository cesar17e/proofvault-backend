import json
import subprocess
from getpass import getpass
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from app.core.config import get_settings


settings = get_settings()

email = input("Development user email: ")
password = getpass("Password: ")
api_key = getpass("Supabase publishable key: ")

url = (
    f"{str(settings.supabase_url).rstrip('/')}"
    "/auth/v1/token?grant_type=password"
)

request = Request(
    url,
    data=json.dumps({
        "email": email,
        "password": password,
    }).encode(),
    headers={
        "apikey": api_key,
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with urlopen(request, timeout=15) as response:
        data = json.load(response)
except HTTPError as exc:
    print(f"Supabase sign-in failed: HTTP {exc.code}")
    raise SystemExit(1) from None

token = data["access_token"]

# Copy JWT to macOS clipboard without printing it.
subprocess.run(
    ["pbcopy"],
    input=token,
    text=True,
    check=True,
)

print("Access token copied to clipboard.")
print("Authenticated user ID:", data["user"]["id"])