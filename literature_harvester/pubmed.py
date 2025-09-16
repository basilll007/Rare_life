"""
PubMed API module for Literature Harvester
Handles all interactions with PubMed/NCBI E-utilities API.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any
from tqdm import tqdm

from .config import Config
from .utils import APISession


class PubMedClient:
    """Client for PubMed API operations"""
    
    def __init__(self, config: Config):
        self.config = config
        self.session = APISession(
            config.pubmed_base, 
            config.ncbi_rate,
            user_agent=f"LiteratureHarvester/1.0 ({config.email})"
        )
    
    def build_search_term(self, query: str, start_year: int, end_year: int) -> str:
        """Build PubMed search term with date range"""
        return f'({query}[Title/Abstract]) AND ("{start_year}"[dp] : "{end_year}"[dp])'
    
    def search(self, term: str, retmax: int = 0, retstart: int = 0, 
               usehistory: bool = True) -> Dict[str, Any]:
        """
        Execute PubMed ESearch query
        """
        params = {
            'db': 'pubmed',
            'term': term,
            'retmode': 'json',
            'retmax': retmax,
            'retstart': retstart,
            'datetype': 'pdat',
            'email': self.config.email
        }
        
        if usehistory:
            params['usehistory'] = 'y'
        
        if self.config.ncbi_api_key:
            params['api_key'] = self.config.ncbi_api_key
        
        response = self.session.request('GET', '/esearch.fcgi', params=params)
        return response.json()
    
    def get_year_counts(self, query: str, start_year: int, end_year: int) -> Dict[str, int]:
        """
        Get publication counts per year
        """
        year_counts = {}
        
        for year in range(start_year, end_year + 1):
            term = f'({query}[Title/Abstract]) AND ("{year}"[dp] : "{year}"[dp])'
            try:
                result = self.search(term, retmax=0, usehistory=False)
                count = int(result.get('esearchresult', {}).get('count', 0))
                year_counts[str(year)] = count
            except Exception as e:
                print(f"Warning: Failed to get count for year {year}: {e}")
                year_counts[str(year)] = 0
        
        return year_counts
    
    def fetch_summaries_paged(self, webenv: str, query_key: str, page_size: int, 
                             max_records: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetch article summaries using ESummary with paging
        """
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
                    'email': self.config.email
                }
                
                if self.config.ncbi_api_key:
                    params['api_key'] = self.config.ncbi_api_key
                
                try:
                    response = self.session.request('GET', '/esummary.fcgi', params=params)
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
    
    def fetch_dois_batch(self, pmids: List[str]) -> Dict[str, str]:
        """
        Fetch DOIs for articles using EFetch XML (for articles missing DOI in ESummary)
        """
        if not pmids:
            return {}
        
        dois = {}
        
        # Process in batches
        for i in range(0, len(pmids), self.config.pubmed_batch_size):
            batch_pmids = pmids[i:i + self.config.pubmed_batch_size]
            
            params = {
                'db': 'pubmed',
                'id': ','.join(batch_pmids),
                'retmode': 'xml',
                'email': self.config.email
            }
            
            if self.config.ncbi_api_key:
                params['api_key'] = self.config.ncbi_api_key
            
            try:
                response = self.session.request('GET', '/efetch.fcgi', params=params)
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