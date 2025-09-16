"""
iCite API module for Literature Harvester
Handles all interactions with NIH iCite API for citation metrics.
"""

from typing import Dict, List, Any

from .config import Config
from .utils import APISession


class ICiteClient:
    """Client for iCite API operations"""
    
    def __init__(self, config: Config):
        self.config = config
        self.session = APISession(config.icite_base, config.icite_rate)
    
    def fetch_citations_bulk(self, pmids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch iCite citation data for articles
        """
        if not pmids:
            return {}
        
        icite_data = {}
        
        # Process in batches
        for i in range(0, len(pmids), self.config.icite_batch_size):
            batch_pmids = pmids[i:i + self.config.icite_batch_size]
            
            params = {
                'pmids': ','.join(batch_pmids)
            }
            
            try:
                response = self.session.request('GET', '/api/pubs', params=params)
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