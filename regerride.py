# The script is for reference and/or educational purposes and not intended for production use
# SPDX-License-Identifier: BlueOak-1.0.0
# To use this script you need to export a Tidelift API as an enviornment variable.
# Always ensure that you are saving your API keys and secrets in a secure secret store when running from CI/CD systems!

import aiohttp
import asyncio
import regex as re
import csv
import os
from urllib.parse import quote
from datetime import datetime

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
RATE_LIMIT_PER_MINUTE = 35
DELAY_BETWEEN_REQUESTS = 60 / RATE_LIMIT_PER_MINUTE  # Delay in seconds
CONCURRENCY_LIMIT = 5

semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

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
                
            return violations
        else:
            print(f"Error fetching initial violations: {response.status}")
            return []

# Async to post a violation override 
async def post_violation_override(session, violation_id, max_retries=3):
    url = f"{base_url}/{ORGANIZATION}/catalogs/{CATALOG_NAME}/violations/{quote(violation_id)}/overrides?status={OVERRIDE_STATUS}"
    data = {
        "status": OVERRIDE_STATUS,
        "reason": "Matched known regex pattern"
    }

    for attempt in range(max_retries):
        async with semaphore:
            async with session.post(url, headers=headers, json=data) as response:
                if response.status == 201:
                    print(f"Successfully posted override for violation ID: {violation_id}")
                    return
                else:
                    print(f"Failed to post override for violation ID: {violation_id}, Status code: {response.status}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

# Check if a package name matches any of the regex patterns
def matches_regex(package_name):
    return any(re.match(pattern, package_name) for pattern in REGEX_PATTERNS)

# Async process violations
async def process_violations(session, violations):
    unmatched_violations = []
    tasks = []

    for violation in violations:
        package_name = violation.get('package_name')
        violation_id = violation.get('violation_id')

        if package_name and violation_id:
            if matches_regex(package_name):
                tasks.append(post_violation_override(session, violation_id))
            else:
                unmatched_violations.append(violation)

    await asyncio.gather(*tasks)
    return unmatched_violations

# Write unmatched violations to a CSV file
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

# Main async function
async def main():
    async with aiohttp.ClientSession() as session:
        violations = await fetch_all_violations(session)
        if violations:
            print(f"Fetched {len(violations)} violations.")
            unmatched_violations = await process_violations(session, violations)
            write_report(unmatched_violations)
            print("Report of unmatched violations written to unmatched_violations_report.csv")
        else:
            print("No violations fetched.")

# Run the script
if __name__ == "__main__":
    asyncio.run(main())
