"""
OpenAlex API module for Literature Harvester
Handles all interactions with OpenAlex API for citation data and metadata.
"""

import re
from typing import Dict, List, Any

from .config import Config
from .utils import APISession


class OpenAlexClient:
    """Client for OpenAlex API operations"""
    
    def __init__(self, config: Config):
        self.config = config
        self.session = APISession(
            config.openalex_base, 
            config.openalex_rate,
            user_agent=config.openalex_email
        )
    
    def fetch_works_by_pmid_bulk(self, pmids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch OpenAlex data for articles by PMID
        """
        if not pmids:
            return {}
        
        openalex_data = {}
        
        # Process in batches
        for i in range(0, len(pmids), self.config.openalex_batch_size):
            batch_pmids = pmids[i:i + self.config.openalex_batch_size]
            # Use correct format - just the PMID numbers separated by |
            pmid_filter = '|'.join(batch_pmids)
            
            params = {
                'filter': f'ids.pmid:{pmid_filter}',
                'per-page': self.config.openalex_batch_size,
                'mailto': self.config.openalex_email  # Required for polite pool
            }
            
            try:
                response = self.session.request('GET', '/works', params=params)
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