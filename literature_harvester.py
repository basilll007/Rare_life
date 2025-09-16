#!/usr/bin/env python3
"""
Literature Harvester - Production-quality PubMed literature mining tool
Queries PubMed, OpenAlex, and iCite APIs to collect comprehensive article data
"""

import argparse
import json
import math
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlencode

import requests
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# API Endpoints
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_BASE = "https://api.openalex.org"
ICITE_BASE = "https://icite.od.nih.gov"

# Rate limiting constants
NCBI_RATE_WITH_KEY = 10  # requests per second
NCBI_RATE_WITHOUT_KEY = 3  # requests per second
OPENALEX_RATE = 10  # requests per second
ICITE_RATE = 10  # requests per second

# Batch sizes
PUBMED_BATCH_SIZE = 200
OPENALEX_BATCH_SIZE = 200
ICITE_BATCH_SIZE = 500


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
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            if attempt == max_retries:
                raise
            
            wait_time = min(60, (2 ** attempt) + random.uniform(0, 1))
            print(f"Request failed: {e}, retrying in {wait_time:.1f}s...")
            time.sleep(wait_time)
    
    raise Exception("Max retries exceeded")


def build_pubmed_term(query: str, start_year: int, end_year: int) -> str:
    """Build PubMed search term with date range"""
    return f'({query}[Title/Abstract]) AND ("{start_year}"[dp] : "{end_year}"[dp])'


def pubmed_esearch(term: str, email: str, api_key: Optional[str] = None, retmax: int = 0, retstart: int = 0, 
                  usehistory: bool = True) -> Dict[str, Any]:
    """
    Execute PubMed ESearch query
    """
    rate_limit = NCBI_RATE_WITH_KEY if api_key else NCBI_RATE_WITHOUT_KEY
    session = APISession(PUBMED_BASE, rate_limit)
    
    params = {
        'db': 'pubmed',
        'term': term,
        'retmode': 'json',
        'retmax': retmax,
        'retstart': retstart,
        'datetype': 'pdat',
        'email': email
    }
    
    if usehistory:
        params['usehistory'] = 'y'
    
    if api_key:
        params['api_key'] = api_key
    
    response = session.request('GET', '/esearch.fcgi', params=params)
    return response.json()


def pubmed_year_counts(query: str, start_year: int, end_year: int, email: str, api_key: Optional[str] = None) -> Dict[str, int]:
    """
    Get publication counts per year
    """
    year_counts = {}
    
    for year in range(start_year, end_year + 1):
        term = f'({query}[Title/Abstract]) AND ("{year}"[dp] : "{year}"[dp])'
        try:
            result = pubmed_esearch(term, email, api_key, retmax=0, usehistory=False)
            count = int(result.get('esearchresult', {}).get('count', 0))
            year_counts[str(year)] = count
        except Exception as e:
            print(f"Warning: Failed to get count for year {year}: {e}")
            year_counts[str(year)] = 0
    
    return year_counts


def pubmed_esummary_paged(webenv: str, query_key: str, page_size: int, email: str, 
                         api_key: Optional[str] = None, max_records: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Fetch article summaries using ESummary with paging
    """
    rate_limit = NCBI_RATE_WITH_KEY if api_key else NCBI_RATE_WITHOUT_KEY
    session = APISession(PUBMED_BASE, rate_limit)
    
    articles = []
    retstart = 0
    
    with tqdm(desc="Fetching PubMed articles", unit="articles") as pbar:
        while True:
            if max_records and len(articles) >= max_records:
                break
            
            current_page_size = min(page_size, max_records - len(articles)) if max_records else page_size
            
            params = {
                'db': 'pubmed',
                'query_key': query_key,
                'WebEnv': webenv,
                'retmode': 'json',
                'retstart': retstart,
                'retmax': current_page_size,
                'email': email
            }
            
            if api_key:
                params['api_key'] = api_key
            
            try:
                response = session.request('GET', '/esummary.fcgi', params=params)
                data = response.json()
                
                result = data.get('result', {})
                if not result or 'uids' not in result:
                    break
                
                uids = result['uids']
                if not uids:
                    break
                
                for uid in uids:
                    if uid in result:
                        article_data = result[uid]
                        
                        # Extract authors
                        authors = []
                        author_list = article_data.get('authors', [])
                        for i, author in enumerate(author_list):
                            authors.append({
                                'name': author.get('name', ''),
                                'order': i + 1
                            })
                        
                        # Extract publication year
                        pub_year = None
                        pub_date = article_data.get('pubdate', '')
                        if pub_date:
                            year_match = re.search(r'\b(19|20)\d{2}\b', pub_date)
                            if year_match:
                                pub_year = int(year_match.group())
                        
                        # Extract DOI from article IDs
                        doi = None
                        article_ids = article_data.get('articleids', [])
                        for aid in article_ids:
                            if aid.get('idtype') == 'doi':
                                doi = aid.get('value')
                                break
                        
                        article = {
                            'pmid': uid,
                            'title': article_data.get('title', ''),
                            'journal': article_data.get('fulljournalname', ''),
                            'pub_year': pub_year,
                            'doi': doi,
                            'authors': authors
                        }
                        
                        articles.append(article)
                        pbar.update(1)
                
                retstart += len(uids)
                
                if len(uids) < current_page_size:
                    break
                    
            except Exception as e:
                print(f"Error fetching articles at offset {retstart}: {e}")
                break
    
    return articles


def pubmed_efetch_doi_batch(pmids: List[str], email: str, api_key: Optional[str] = None) -> Dict[str, str]:
    """
    Fetch DOIs for articles using EFetch XML (for articles missing DOI in ESummary)
    """
    if not pmids:
        return {}
    
    rate_limit = NCBI_RATE_WITH_KEY if api_key else NCBI_RATE_WITHOUT_KEY
    session = APISession(PUBMED_BASE, rate_limit)
    
    dois = {}
    
    # Process in batches
    for i in range(0, len(pmids), PUBMED_BATCH_SIZE):
        batch_pmids = pmids[i:i + PUBMED_BATCH_SIZE]
        
        params = {
            'db': 'pubmed',
            'id': ','.join(batch_pmids),
            'retmode': 'xml',
            'email': email
        }
        
        if api_key:
            params['api_key'] = api_key
        
        try:
            response = session.request('GET', '/efetch.fcgi', params=params)
            root = ET.fromstring(response.content)
            
            for article in root.findall('.//PubmedArticle'):
                pmid_elem = article.find('.//PMID')
                if pmid_elem is None:
                    continue
                
                pmid = pmid_elem.text
                doi = None
                
                # Look for DOI in ELocationID
                for elocation in article.findall('.//ELocationID'):
                    if elocation.get('EIdType') == 'doi':
                        doi = elocation.text
                        break
                
                # Look for DOI in ArticleIdList
                if not doi:
                    for article_id in article.findall('.//ArticleId'):
                        if article_id.get('IdType') == 'doi':
                            doi = article_id.text
                            break
                
                if doi:
                    dois[pmid] = doi
                    
        except Exception as e:
            print(f"Error fetching DOIs for batch: {e}")
    
    return dois


def openalex_works_by_pmid_bulk(pmids: List[str], email: str) -> Dict[str, Dict[str, Any]]:
    """
    Fetch OpenAlex data for articles by PMID
    """
    if not pmids:
        return {}
    
    session = APISession(OPENALEX_BASE, OPENALEX_RATE, user_agent=email)
    openalex_data = {}
    
    # Process in batches
    for i in range(0, len(pmids), OPENALEX_BATCH_SIZE):
        batch_pmids = pmids[i:i + OPENALEX_BATCH_SIZE]
        # Fix: Use correct format - just the PMID numbers separated by |
        pmid_filter = '|'.join(batch_pmids)
        
        params = {
            'filter': f'ids.pmid:{pmid_filter}',  # Fix: Correct format without double pmid prefix
            'per-page': OPENALEX_BATCH_SIZE,
            'mailto': email  # Fix: Add required mailto parameter for polite pool
        }
        
        try:
            response = session.request('GET', '/works', params=params)
            data = response.json()
            
            for work in data.get('results', []):
                # Extract PMID from IDs
                pmid = None
                for id_entry in work.get('ids', {}).values():
                    if isinstance(id_entry, str) and 'pubmed' in id_entry.lower():
                        pmid_match = re.search(r'(\d+)$', id_entry)
                        if pmid_match:
                            pmid = pmid_match.group(1)
                            break
                
                if not pmid:
                    continue
                
                # Extract concepts
                concepts = [concept.get('display_name', '') for concept in work.get('concepts', [])]
                
                # Extract authorships with institutions
                authorships = []
                for authorship in work.get('authorships', []):
                    author = authorship.get('author', {})
                    institutions = []
                    
                    for institution in authorship.get('institutions', []):
                        institutions.append({
                            'name': institution.get('display_name', ''),
                            'ror': institution.get('ror', ''),
                            'country_code': institution.get('country_code', '')
                        })
                    
                    authorships.append({
                        'author_id': author.get('id', ''),
                        'display_name': author.get('display_name', ''),
                        'institutions': institutions
                    })
                
                openalex_data[pmid] = {
                    'id': work.get('id', ''),
                    'doi': work.get('doi', ''),
                    'cited_by_count': work.get('cited_by_count', 0),
                    'is_retracted': work.get('is_retracted', False),
                    'concepts': concepts,
                    'authorships': authorships
                }
                
        except Exception as e:
            print(f"Error fetching OpenAlex data for batch: {e}")
    
    return openalex_data


def icite_citations_bulk(pmids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch iCite citation data for articles
    """
    if not pmids:
        return {}
    
    session = APISession(ICITE_BASE, ICITE_RATE)
    icite_data = {}
    
    # Process in batches
    for i in range(0, len(pmids), ICITE_BATCH_SIZE):
        batch_pmids = pmids[i:i + ICITE_BATCH_SIZE]
        
        params = {
            'pmids': ','.join(batch_pmids)
        }
        
        try:
            response = session.request('GET', '/api/pubs', params=params)
            data = response.json()
            
            for article in data.get('data', []):
                pmid = str(article.get('pmid', ''))
                if pmid:
                    icite_data[pmid] = {
                        'cited_by': article.get('cited_by', 0)
                    }
                    
        except Exception as e:
            print(f"Error fetching iCite data for batch: {e}")
    
    return icite_data


def unify_citations(openalex_map: Dict[str, Dict[str, Any]], icite_map: Dict[str, Dict[str, Any]], 
                   policy: str, default_source: str, now_iso: str) -> Dict[str, Dict[str, Any]]:
    """
    Unify citation counts from OpenAlex and iCite based on policy
    """
    results = {}
    for pmid in set(list(openalex_map.keys()) + list(icite_map.keys())):
        oa_val = None
        if pmid in openalex_map:
            try: 
                oa_val = int(openalex_map[pmid].get("cited_by_count") or 0)
            except: 
                oa_val = None
        
        ic_val = None
        if pmid in icite_map:
            try: 
                ic_val = int(icite_map[pmid].get("cited_by") or 0)
            except: 
                ic_val = None
        
        sources = {
            "openalex": {"value": oa_val, "fetched_at": now_iso},
            "icite": {"value": ic_val, "fetched_at": now_iso}
        }
        
        discrepancy = abs(oa_val - ic_val) if oa_val is not None and ic_val is not None else 0
        pick, source_of_truth = None, default_source
        
        # Default selection
        if default_source == "openalex":
            pick, source_of_truth = (oa_val, "openalex") if oa_val is not None else (ic_val, "icite")
        elif default_source == "icite":
            pick, source_of_truth = (ic_val, "icite") if ic_val is not None else (oa_val, "openalex")
        elif default_source == "both":
            pick, source_of_truth = (oa_val, "both") if oa_val is not None else (ic_val, "both")
        
        # Policy overrides
        if policy == "prefer_openalex":
            pick, source_of_truth = (oa_val, "openalex") if oa_val is not None else (ic_val, "icite")
        elif policy == "prefer_icite":
            pick, source_of_truth = (ic_val, "icite") if ic_val is not None else (oa_val, "openalex")
        elif policy == "max" and oa_val is not None and ic_val is not None:
            pick, source_of_truth = (max(oa_val, ic_val), "reconciled")
        elif policy == "min" and oa_val is not None and ic_val is not None:
            pick, source_of_truth = (min(oa_val, ic_val), "reconciled")
        elif policy == "reconcile" and oa_val is not None and ic_val is not None:
            hi, lo = max(oa_val, ic_val), min(oa_val, ic_val)
            if lo > 0 and (hi - lo) / lo <= 0.10:
                pick = round((oa_val + ic_val) / 2)
            else:
                pick = hi
            source_of_truth = "reconciled"
        
        results[pmid] = {
            "value": pick or 0,
            "source_of_truth": source_of_truth,
            "sources": sources,
            "discrepancy": discrepancy
        }
    
    return results


def merge_records(pubmed_items: List[Dict[str, Any]], openalex_map: Dict[str, Dict[str, Any]], 
                 icite_map: Dict[str, Dict[str, Any]], citations_source: str, citations_policy: str) -> List[Dict[str, Any]]:
    """
    Merge PubMed, OpenAlex, and iCite data
    """
    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    citations_map = unify_citations(openalex_map, icite_map, citations_policy, citations_source, now_iso)
    
    merged_items = []
    
    for item in pubmed_items:
        pmid = item['pmid']
        merged_item = item.copy()
        
        # Add OpenAlex data
        openalex_data = openalex_map.get(pmid, {})
        if openalex_data:
            # Enrich DOI if missing
            if not merged_item.get('doi') and openalex_data.get('doi'):
                merged_item['doi'] = openalex_data['doi']
            
            # Add OpenAlex author IDs and institutions to existing authors
            openalex_authorships = openalex_data.get('authorships', [])
            for i, author in enumerate(merged_item.get('authors', [])):
                if i < len(openalex_authorships):
                    authorship = openalex_authorships[i]
                    author['openalex_author_id'] = authorship.get('author_id', '')
                    author['institutions'] = authorship.get('institutions', [])
            
            merged_item['openalex'] = {
                'id': openalex_data.get('id', ''),
                'cited_by_count': openalex_data.get('cited_by_count', 0),
                'is_retracted': openalex_data.get('is_retracted', False),
                'concepts': openalex_data.get('concepts', [])
            }
        
        # Add iCite data
        icite_data = icite_map.get(pmid, {})
        if icite_data:
            merged_item['icite'] = icite_data
        
        # Add unified citations
        c = citations_map.get(pmid)
        merged_item["citations"] = c
        
        # Handle citation source preferences
        if citations_source == 'openalex' and not openalex_data and icite_data:
            # Fallback to iCite if OpenAlex not available
            pass
        elif citations_source == 'icite' and not icite_data and openalex_data:
            # Fallback to OpenAlex if iCite not available
            pass
        
        merged_items.append(merged_item)
    
    return merged_items


def save_json(payload: Dict[str, Any], file_path: str):
    """
    Save data to JSON file with proper formatting
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def print_summary(payload: Dict[str, Any]):
    """
    Print a summary of the harvesting results
    """
    total_count = payload.get('pubmed', {}).get('total_count', 0)
    fetched_count = payload.get('pubmed', {}).get('fetched_count', 0)
    year_counts = payload.get('pubmed', {}).get('year_counts', {})
    citations_source = payload.get('citations', {}).get('source_of_truth', 'N/A')
    
    # Calculate citation statistics
    items = payload.get('items', [])
    both_sources_count = 0
    high_discrepancy_count = 0
    
    for item in items:
        citations = item.get('citations', {})
        sources = citations.get('sources', {})
        
        oa_val = sources.get('openalex', {}).get('value')
        ic_val = sources.get('icite', {}).get('value')
        
        if oa_val is not None and ic_val is not None:
            both_sources_count += 1
            discrepancy = citations.get('discrepancy', 0)
            if oa_val > 0 and ic_val > 0:
                discrepancy_pct = discrepancy / max(oa_val, ic_val)
                if discrepancy_pct > 0.10:
                    high_discrepancy_count += 1
    
    print("\n" + "="*50)
    print("LITERATURE HARVESTER SUMMARY")
    print("="*50)
    print(f"Query: {payload.get('query', 'N/A')}")
    print(f"Year Range: {payload.get('year_range', {}).get('start', 'N/A')}-{payload.get('year_range', {}).get('end', 'N/A')}")
    print(f"Total PubMed Hits: {total_count:,}")
    print(f"Fetched Articles: {fetched_count:,}")
    
    if total_count > 0:
        coverage = (fetched_count / total_count) * 100
        print(f"Coverage: {coverage:.1f}%")
    
    print(f"Citation Source: {citations_source}")
    
    # Citation statistics
    if both_sources_count > 0:
        high_discrepancy_pct = (high_discrepancy_count / both_sources_count) * 100
        print(f"\nCitation Statistics:")
        print(f"  Items with both sources: {both_sources_count}")
        print(f"  Items with >10% discrepancy: {high_discrepancy_count} ({high_discrepancy_pct:.1f}%)")
    
    print(f"\nYear-by-Year Counts:")
    for year in sorted(year_counts.keys()):
        print(f"  {year}: {year_counts[year]:,}")
    
    print(f"\nOutput saved to: {payload.get('output_file', 'N/A')}")


def main():
    """
    Main CLI entry point
    """
    parser = argparse.ArgumentParser(
        description="Literature Harvester - Mine PubMed literature with citation data",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('query', help='Search query for PubMed')
    parser.add_argument('startyear', type=int, help='Start year for search range')
    parser.add_argument('endyear', type=int, help='End year for search range')
    parser.add_argument('--email', help='Email address for API requests (default from .env)')
    
    parser.add_argument('--pagesize', type=int, default=200, 
                       help='Page size for API requests (default: 200)')
    parser.add_argument('--citationssource', choices=['openalex', 'icite', 'both'], 
                       default='openalex', help='Citation data source (default: openalex)')
    parser.add_argument('--citationspolicy', choices=['prefer_openalex', 'prefer_icite', 'max', 'min', 'reconcile'], 
                       default='prefer_openalex', help='Citation policy (default: prefer_openalex)')
    parser.add_argument('--outfile', default='results.json', 
                       help='Output JSON file (default: results.json)')
    parser.add_argument('--ncbiapikey', help='NCBI API key (or set NCBI_API_KEY env var)')
    parser.add_argument('--maxrecords', type=int, 
                       help='Maximum number of records to fetch (for development)')
    
    args = parser.parse_args()
    
    # Get email from argument, environment, or prompt user
    email = args.email or os.getenv('ENTREZ_EMAIL')
    if not email:
        print("Error: Email address is required. Provide via --email argument or set ENTREZ_EMAIL in .env file")
        return 1
    
    # Get API key from argument or environment
    api_key = args.ncbiapikey or os.getenv('NCBI_API_KEY')
    
    # Validate year range
    if args.startyear > args.endyear:
        print("Error: Start year must be <= end year")
        return 1
    
    print(f"Starting literature harvest for query: '{args.query}'")
    print(f"Year range: {args.startyear}-{args.endyear}")
    print(f"Citation source: {args.citationssource}")
    print(f"Email: {email}")
    if api_key:
        print(f"Using NCBI API key: {api_key[:8]}...")
    
    try:
        # Step 1: Get total counts and year-by-year breakdown
        print("\n1. Getting publication counts...")
        search_term = build_pubmed_term(args.query, args.startyear, args.endyear)
        
        # Get total count
        search_result = pubmed_esearch(search_term, email, api_key, retmax=0)
        total_count = int(search_result.get('esearchresult', {}).get('count', 0))
        
        # Get year-by-year counts
        year_counts = pubmed_year_counts(args.query, args.startyear, args.endyear, email, api_key)
        
        print(f"Found {total_count:,} total articles")
        
        # Step 2: Fetch article details
        print("\n2. Fetching article details...")
        
        # Get search history for paging
        search_result = pubmed_esearch(search_term, email, api_key, retmax=0, usehistory=True)
        webenv = search_result.get('esearchresult', {}).get('webenv')
        query_key = search_result.get('esearchresult', {}).get('querykey')
        
        if not webenv or not query_key:
            print("Error: Could not establish search history")
            return 1
        
        # Fetch articles using ESummary
        articles = pubmed_esummary_paged(webenv, query_key, args.pagesize, email, api_key, args.maxrecords)
        
        print(f"Fetched {len(articles)} article summaries")
        
        # Step 3: Fetch missing DOIs
        print("\n3. Fetching missing DOIs...")
        missing_doi_pmids = [article['pmid'] for article in articles if not article.get('doi')]
        
        if missing_doi_pmids:
            print(f"Fetching DOIs for {len(missing_doi_pmids)} articles...")
            doi_map = pubmed_efetch_doi_batch(missing_doi_pmids, email, api_key)
            
            # Update articles with DOIs
            for article in articles:
                if not article.get('doi') and article['pmid'] in doi_map:
                    article['doi'] = doi_map[article['pmid']]
        
        # Step 4: Fetch citation data
        pmids = [article['pmid'] for article in articles]
        openalex_map = {}
        icite_map = {}
        
        # Use email from environment for OpenAlex if available
        openalex_email = os.getenv('OPENALEX_MAILTO', email)
        
        if args.citationssource in ['openalex', 'both']:
            print("\n4. Fetching OpenAlex data...")
            openalex_map = openalex_works_by_pmid_bulk(pmids, openalex_email)
            print(f"Retrieved OpenAlex data for {len(openalex_map)} articles")
        
        if args.citationssource in ['icite', 'both']:
            print("\n5. Fetching iCite data...")
            icite_map = icite_citations_bulk(pmids)
            print(f"Retrieved iCite data for {len(icite_map)} articles")
        
        # Step 5: Merge all data
        print("\n6. Merging data...")
        merged_items = merge_records(articles, openalex_map, icite_map, args.citationssource, args.citationspolicy)
        
        # Step 6: Create output payload
        payload = {
            'query': args.query,
            'year_range': {
                'start': args.startyear,
                'end': args.endyear
            },
            'pubmed': {
                'total_count': total_count,
                'year_counts': year_counts,
                'fetched_count': len(merged_items)
            },
            'citations': {
                'source_of_truth': args.citationssource
            },
            'items': merged_items,
            'output_file': args.outfile
        }
        
        # Step 7: Save and summarize
        print(f"\n7. Saving results to {args.outfile}...")
        save_json(payload, args.outfile)
        
        print_summary(payload)
        
        return 0
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    exit(main())