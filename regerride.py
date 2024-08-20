import aiohttp
import asyncio
import regex as re
import csv
import os
from urllib.parse import quote
from datetime import datetime
from aiohttp import ClientSession

# Retrieve the API key from the environment variable
# This script requires a user api key in order to match the override to a user for audit purposes
API_KEY = os.environ.get('TIDELIFT_API_KEY')
if not API_KEY:
    print("API key not found in environment variables.")
    exit()

# Set organization and other constants
ORGANIZATION = '<organization_name>' # replace with your organization name 
CATALOG_NAME = '<catalog_name>'  # replace with your catalog name
CATALOG_STANDARD = 'known_packages' 
OVERRIDE_STATUS = 'approved' # status can be 'approved' or 'denied'

# Read regex patterns from the external file
with open('package_patterns.txt', 'r') as file:
    REGEX_PATTERNS = [line.strip() for line in file if line.strip()]

# Define the headers for the API requests
headers = {
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type': 'application/json'
}

# Set the rate limit parameters to stay within the 120 request per minute limit https://support.tidelift.com/hc/en-us/articles/18135603270164-Data-APIs-overview#01HNXG55PY9X1VDSH6C851MN6M
RATE_LIMIT_PER_MINUTE = 30
DELAY_BETWEEN_REQUESTS = 60 / RATE_LIMIT_PER_MINUTE
CONCURRENCY_LIMIT = 2

semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
last_request_time = asyncio.Queue(maxsize=1)

# Base URL for Tidelift API
base_url = 'https://api.tidelift.com/external-api/v1'

# Async to fetch all violations
async def fetch_all_violations(session):
    url = f"{base_url}/{ORGANIZATION}/catalogs/{CATALOG_NAME}/violations?catalog_standards[]={CATALOG_STANDARD}"
    violations = []
    
    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            data = await response.json()
            total_pages = data.get('total_pages', 1)
            
            for page in range(total_pages, 0, -1):
                paged_url = f"{url}&page={page}"
                async with semaphore:
                    async with session.get(paged_url, headers=headers) as paged_response:
                        if paged_response.status == 200:
                            paged_data = await paged_response.json()
                            violations.extend(paged_data.get('results', []))
                            await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
                        else:
                            print(f"Error fetching page {page}: {paged_response.status}")
                
            print(f"Fetched {len(violations)} violations.")
            return violations
        else:
            print(f"Error fetching initial violations: {response.status}")
            return []

# Async generate the report
async def generate_report(session):
    url = f"{base_url}/{ORGANIZATION}/reports/all_projects_violations/generate?catalog_name={CATALOG_NAME}"
    async with session.post(url, headers=headers) as response:
        if response.status == 200:
            print("Report generation initiated successfully.")
            return await response.json()
        else:
            print(f"Error generating report: {response.status}")
            print("Response text:", await response.text())
            return None

# Async fetch the report status
async def fetch_report_status(session, report_id):
    url = f"{base_url}/{ORGANIZATION}/reports/all_projects_violations/status/?report_id={report_id}"
    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            print("Report status fetched successfully.")
            return await response.json()
        else:
            print(f"Error fetching report status: {response.status}")
            return None

# Async fetch the report data
async def fetch_report_data(session, report_id):
    url = f"{base_url}/{ORGANIZATION}/reports/all_projects_violations?report_id={report_id}"
    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            print("Report data fetched successfully.")
            return await response.json()
        else:
            print(f"Error fetching report data: {response.status}")
            return None

# Check if a package name matches any of the regex patterns
def matches_regex(package_name):
    return any(re.match(pattern, package_name) for pattern in REGEX_PATTERNS)

# Async perform package lookup in report data (returns all violating versions)
async def package_lookup_in_report(platform, package_name, report_data):
    versions = []
    for entry in report_data.get('report', []):
        if entry.get('platform') == platform and entry.get('violating_package') == package_name:
            versions.append(entry.get('violating_version'))
    return versions

async def rate_limiter():
    await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

async def post_violation_override(session, violation_id, package_name, package_platform, version=None, max_retries=3):
    url = f"{base_url}/{ORGANIZATION}/catalogs/{CATALOG_NAME}/violations/{quote(violation_id)}/overrides"
    data = {
        "status": OVERRIDE_STATUS,
        "note": "Matched known regex pattern",
        "platform": package_platform,  
        "package_name": package_name  
    }
    if version:
        data["version"] = version

    #print(f"Posting override with the following data: {data}")

    for attempt in range(max_retries):
        async with semaphore:
            try:
                print(f"Attempt {attempt + 1} for violation ID: {violation_id}")
                await rate_limiter()  # rate limiting applied
                async with session.post(url, headers=headers, json=data) as response:
                    if response.status == 201:
                        print(f"Successfully posted override for violation ID: {violation_id}, Version: {version}")
                        break
                    else:
                    
                        print(f"Failed to post override for violation ID: {violation_id}, Status code: {response.status}")
                        await asyncio.sleep(2 * (attempt + 1)) # Exponential backoff
            except Exception as e:
                print(f"Exception occurred: {e}")
                await asyncio.sleep(2 * (attempt + 1))  # Exponential backoff

# Async process violations
async def process_violations(session, violations, report_data):
    unmatched_violations = []
    tasks = []

    for violation in violations:
        package_name = violation.get('package_name')
        violation_id = violation.get('violation_id')
        platform = violation.get('package_platform')

        if package_name and violation_id and platform:
            if matches_regex(package_name):
                versions = await package_lookup_in_report(platform, package_name, report_data)
                if versions:
                    for version in versions:
                        tasks.append(post_violation_override(session, violation_id, package_name, platform, version))
                else:
                    tasks.append(post_violation_override(session, violation_id, package_name, platform))
            else:
                unmatched_violations.append(violation)

    await asyncio.gather(*tasks)
    return unmatched_violations


# Function to write unmatched violations to a CSV file
def write_report(unmatched_violations):
    with open('unmatched_violations_report.csv', 'w', newline='') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['catalog_standard', 'violation_id', 'title', 'package_name', 'package_platform', 'task_id'])
        for violation in unmatched_violations:
            writer.writerow([
                violation.get('catalog_standard', ''),
                violation.get('violation_id', ''),
                violation.get('title', ''),
                violation.get('package_name', ''),
                violation.get('package_platform', ''),
                violation.get('task_id', '')
            ])
    print("Report of unmatched violations written to unmatched_violations_report.csv")

# Main async function
async def main():
    async with aiohttp.ClientSession() as session:
        report = await generate_report(session)
        if not report:
            return

        report_id = report.get('report_id')
        if not report_id:
            print("No report ID found.")
            return

        while True:
            status = await fetch_report_status(session, report_id)
            if status and status.get('status') == 'completed':
                break
            print("Report not ready yet, waiting...")
            await asyncio.sleep(10)  # Wait before checking status again

        report_data = await fetch_report_data(session, report_id)
        if not report_data:
            return

        violations = await fetch_all_violations(session)
        if violations:
            unmatched_violations = await process_violations(session, violations, report_data)
            write_report(unmatched_violations)

# Run the script
if __name__ == "__main__":
    asyncio.run(main())
