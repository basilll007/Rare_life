"""
Configuration module for Literature Harvester
Contains all constants, API endpoints, and configuration settings.
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Endpoints
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_BASE = "https://api.openalex.org"
ICITE_BASE = "https://icite.od.nih.gov"

# Rate limiting constants (requests per second)
NCBI_RATE_WITH_KEY = 10
NCBI_RATE_WITHOUT_KEY = 3
OPENALEX_RATE = 10
ICITE_RATE = 10

# Batch sizes - Updated to maximum allowed values
PUBMED_BATCH_SIZE = 10000  # Maximum for ESummary per NCBI documentation
OPENALEX_BATCH_SIZE = 200
ICITE_BATCH_SIZE = 500

# Default values
DEFAULT_PAGE_SIZE = 10000  # Updated to match maximum batch size
DEFAULT_OUTPUT_FILE = "results.json"
DEFAULT_CITATIONS_SOURCE = "openalex"
DEFAULT_CITATIONS_POLICY = "prefer_openalex"


class Config:
    """Configuration class for Literature Harvester"""
    
    def __init__(self):
        self.email = os.getenv('ENTREZ_EMAIL')
        self.ncbi_api_key = os.getenv('NCBI_API_KEY')
        self.openalex_email = os.getenv('OPENALEX_MAILTO', self.email)
        
        # API settings
        self.pubmed_base = PUBMED_BASE
        self.openalex_base = OPENALEX_BASE
        self.icite_base = ICITE_BASE
        
        # Rate limits
        self.ncbi_rate = NCBI_RATE_WITH_KEY if self.ncbi_api_key else NCBI_RATE_WITHOUT_KEY
        self.openalex_rate = OPENALEX_RATE
        self.icite_rate = ICITE_RATE
        
        # Batch sizes
        self.pubmed_batch_size = PUBMED_BATCH_SIZE
        self.openalex_batch_size = OPENALEX_BATCH_SIZE
        self.icite_batch_size = ICITE_BATCH_SIZE
        
        # Defaults
        self.default_page_size = DEFAULT_PAGE_SIZE
        self.default_output_file = DEFAULT_OUTPUT_FILE
        self.default_citations_source = DEFAULT_CITATIONS_SOURCE
        self.default_citations_policy = DEFAULT_CITATIONS_POLICY
    
    def validate(self) -> bool:
        """Validate configuration"""
        if not self.email:
            raise ValueError("Email address is required. Set ENTREZ_EMAIL environment variable.")
        return True
    
    def set_email(self, email: str):
        """Set email address"""
        self.email = email
        if not self.openalex_email:
            self.openalex_email = email
    
    def set_ncbi_api_key(self, api_key: str):
        """Set NCBI API key and update rate limit"""
        self.ncbi_api_key = api_key
        self.ncbi_rate = NCBI_RATE_WITH_KEY