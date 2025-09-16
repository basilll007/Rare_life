"""
Utility functions for Literature Harvester
Contains common functionality like API session management, retry logic, and data processing.
"""

import json
import random
import time
from typing import Dict, Any
import requests


class APISession:
    """Manages API sessions with rate limiting and retry logic"""
    
    def __init__(self, base_url: str, rate_limit: float, user_agent: str = None):
        self.session = requests.Session()
        self.base_url = base_url
        self.rate_limit = rate_limit
        self.last_request_time = 0
        
        if user_agent:
            self.session.headers.update({'User-Agent': user_agent})
    
    def _wait_for_rate_limit(self):
        """Enforce rate limiting"""
        if self.rate_limit > 0:
            time_since_last = time.time() - self.last_request_time
            min_interval = 1.0 / self.rate_limit
            if time_since_last < min_interval:
                time.sleep(min_interval - time_since_last)
        self.last_request_time = time.time()
    
    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make rate-limited request with retry logic"""
        self._wait_for_rate_limit()
        full_url = f"{self.base_url}/{url.lstrip('/')}" if not url.startswith('http') else url
        return retry_request(self.session, method, full_url, **kwargs)


def retry_request(session: requests.Session, method: str, url: str, max_retries: int = 5, **kwargs) -> requests.Response:
    """
    Retry HTTP requests with exponential backoff and jitter
    """
    for attempt in range(max_retries + 1):
        try:
            response = session.request(method, url, **kwargs)
            
            # Handle rate limiting
            if response.status_code == 429:
                if attempt == max_retries:
                    response.raise_for_status()
                
                # Extract retry-after header or use exponential backoff
                retry_after = response.headers.get('Retry-After')
                if retry_after:
                    wait_time = float(retry_after)
                else:
                    wait_time = min(60, (2 ** attempt) + random.uniform(0, 1))
                
                print(f"Rate limited, waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            
            # Handle server errors
            if response.status_code >= 500:
                if attempt == max_retries:
                    response.raise_for_status()
                
                wait_time = min(60, (2 ** attempt) + random.uniform(0, 1))
                print(f"Server error {response.status_code}, retrying in {wait_time:.1f}s...")
                time.sleep(wait_time)
                continue
            
            # Success or client error
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                raise
            
            wait_time = min(60, (2 ** attempt) + random.uniform(0, 1))
            print(f"Request failed ({e}), retrying in {wait_time:.1f}s...")
            time.sleep(wait_time)
    
    # Should never reach here
    raise Exception("Max retries exceeded")


def save_json(payload: Dict[str, Any], file_path: str):
    """Save payload to JSON file with pretty formatting"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def print_summary(payload: Dict[str, Any]):
    """Print summary of harvested data"""
    print("\n" + "="*60)
    print("LITERATURE HARVEST SUMMARY")
    print("="*60)
    
    # Basic info
    print(f"Query: {payload.get('query', 'N/A')}")
    year_range = payload.get('year_range', {})
    print(f"Year range: {year_range.get('start', 'N/A')}-{year_range.get('end', 'N/A')}")
    
    # PubMed stats
    pubmed_stats = payload.get('pubmed', {})
    print(f"Total PubMed articles: {pubmed_stats.get('total_count', 0):,}")
    print(f"Articles fetched: {pubmed_stats.get('fetched_count', 0):,}")
    
    # Year breakdown
    year_counts = pubmed_stats.get('year_counts', {})
    if year_counts:
        print("\nYear-by-year breakdown:")
        for year in sorted(year_counts.keys()):
            print(f"  {year}: {year_counts[year]:,} articles")
    
    # Citation stats
    items = payload.get('items', [])
    if items:
        citations_available = sum(1 for item in items if item.get('citations_value') is not None)
        print(f"\nCitation data available: {citations_available:,}/{len(items):,} articles")
        
        if citations_available > 0:
            citations = [item['citations_value'] for item in items if item.get('citations_value') is not None]
            print(f"Citation range: {min(citations)}-{max(citations)}")
            print(f"Average citations: {sum(citations)/len(citations):.1f}")
    
    # DOI stats
    dois_available = sum(1 for item in items if item.get('doi'))
    print(f"DOIs available: {dois_available:,}/{len(items):,} articles")
    
    print(f"\nResults saved to: {payload.get('output_file', 'N/A')}")
    print("="*60)