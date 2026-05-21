import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

base_url = "https://docs.aws.amazon.com/AmazonS3/latest/userguide/"

client = httpx.Client(
    headers={"User-Agent": "aws-docs-agent-bot/1.0"},
    timeout=15.0,
    follow_redirects=True,
)

# Test 1: Can we reach AWS docs at all?
print("=== Test 1: Fetching base URL ===")
try:
    resp = client.get(base_url)
    print(f"Status: {resp.status_code}")
    print(f"Final URL after redirects: {resp.url}")
    print(f"Content length: {len(resp.text)}")
except Exception as e:
    print(f"FAILED: {e}")

# Test 2: What links does the page contain?
print("\n=== Test 2: Extracting links ===")
resp = client.get(base_url)
soup = BeautifulSoup(resp.text, "lxml")
all_links = [a["href"] for a in soup.find_all("a", href=True)]
print(f"Total <a> tags found: {len(all_links)}")
print("Sample hrefs:", all_links[:10])

# Test 3: Apply your startswith filter
print("\n=== Test 3: Filter startswith base_url ===")
matched = []
for href in all_links:
    full_url = urljoin(str(resp.url), href)   # use final URL after redirect
    if full_url.startswith(base_url) and "#" not in full_url:
        matched.append(full_url)
print(f"Links passing filter: {len(matched)}")
print("Sample matched:", matched[:5])

# Test 4: Check what the actual final URL is vs base_url
print("\n=== Test 4: Redirect check ===")
print(f"base_url:  {base_url}")
print(f"final URL: {resp.url}")
print(f"Match: {str(resp.url) == base_url}")