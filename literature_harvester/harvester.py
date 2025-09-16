"""
Main Literature Harvester class
Coordinates all data sources and provides a unified interface for literature harvesting.
"""

from datetime import datetime
from typing import Dict, List, Any, Optional

from .config import Config
from .pubmed import PubMedClient
from .openalex import OpenAlexClient
from .icite import ICiteClient
from .data_processor import merge_records, save_json, print_summary


class LiteratureHarvester:
    """
    Main class for literature harvesting operations
    Coordinates PubMed, OpenAlex, and iCite data sources
    """
    
    def __init__(self, config: Config = None):
        """Initialize the harvester with configuration"""
        self.config = config or Config()
        
        # Initialize clients
        self.pubmed = PubMedClient(self.config)
        self.openalex = OpenAlexClient(self.config)
        self.icite = ICiteClient(self.config)
    
    def harvest(self, query: str, start_year: int, end_year: int, 
                max_records: Optional[int] = None,
                citations_source: str = "openalex",
                citations_policy: str = "prefer_openalex",
                output_file: Optional[str] = None,
                verbose: bool = True) -> Dict[str, Any]:
        """
        Main harvesting function that coordinates all data sources
        
        Args:
            query: Search query
            start_year: Start year for search
            end_year: End year for search
            max_records: Maximum number of records to fetch
            citations_source: Preferred citation source ('openalex', 'icite', 'both')
            citations_policy: Citation reconciliation policy
            output_file: Output file path (optional)
            verbose: Whether to print progress information
            
        Returns:
            Dictionary containing harvested data and metadata
        """
        if verbose:
            print(f"Starting literature harvest for query: {query}")
            print(f"Year range: {start_year}-{end_year}")
        
        # Step 1: Get publication counts by year
        if verbose:
            print("Getting publication counts by year...")
        year_counts = self.pubmed.get_year_counts(query, start_year, end_year)
        total_count = sum(year_counts.values())
        
        if verbose:
            print(f"Total publications found: {total_count:,}")
            for year in sorted(year_counts.keys()):
                print(f"  {year}: {year_counts[year]:,}")
        
        # Step 2: Search and get WebEnv/QueryKey
        if verbose:
            print("Performing PubMed search...")
        search_term = self.pubmed.build_search_term(query, start_year, end_year)
        search_result = self.pubmed.search(search_term)
        
        # Extract webenv and querykey from the esearchresult
        esearch_result = search_result.get('esearchresult', {})
        webenv = esearch_result.get('webenv')
        query_key = esearch_result.get('querykey')
        
        if not webenv or not query_key:
            raise ValueError("Failed to get webenv or querykey from PubMed search. Check your search parameters and API access.")
        
        # Step 3: Fetch article summaries
        if verbose:
            print("Fetching article summaries...")
        pubmed_items = self.pubmed.fetch_summaries_paged(
            webenv, query_key, page_size=self.config.pubmed_batch_size, max_records=max_records
        )
        
        fetched_count = len(pubmed_items)
        if verbose:
            print(f"Fetched {fetched_count:,} article summaries")
        
        # Step 4: Supplement DOIs if needed
        pmids_without_doi = [item['pmid'] for item in pubmed_items if not item.get('doi')]
        if pmids_without_doi and verbose:
            print(f"Supplementing DOIs for {len(pmids_without_doi)} articles...")
        
        doi_map = self.pubmed.fetch_dois_batch(pmids_without_doi)
        
        # Update items with DOIs
        for item in pubmed_items:
            if not item.get('doi') and item['pmid'] in doi_map:
                item['doi'] = doi_map[item['pmid']]
        
        # Step 5: Fetch OpenAlex data
        pmids = [item['pmid'] for item in pubmed_items]
        if verbose:
            print(f"Fetching OpenAlex data for {len(pmids)} articles...")
        openalex_map = self.openalex.fetch_works_by_pmid_bulk(pmids)
        
        # Step 6: Fetch iCite data
        if verbose:
            print(f"Fetching iCite citation data for {len(pmids)} articles...")
        icite_map = self.icite.fetch_citations_bulk(pmids)
        
        # Step 7: Merge all data
        if verbose:
            print("Merging data from all sources...")
        merged_items = merge_records(
            pubmed_items, openalex_map, icite_map, 
            citations_source, citations_policy
        )
        
        # Step 8: Create final payload
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        
        payload = {
            "query": query,
            "year_range": {"start": start_year, "end": end_year},
            "harvested_at": now_iso,
            "pubmed": {
                "total_count": total_count,
                "fetched_count": fetched_count,
                "year_counts": year_counts
            },
            "citations": {
                "source_of_truth": citations_source,
                "policy": citations_policy
            },
            "items": merged_items
        }
        
        # Step 9: Save to file if requested
        if output_file:
            payload["output_file"] = output_file
            save_json(payload, output_file)
            if verbose:
                print(f"Results saved to: {output_file}")
        
        # Step 10: Print summary
        if verbose:
            print_summary(payload)
        
        return payload
    
    def get_year_counts(self, query: str, start_year: int, end_year: int) -> Dict[str, int]:
        """Get publication counts by year for a query"""
        return self.pubmed.get_year_counts(query, start_year, end_year)
    
    def search_pubmed(self, query: str, start_year: int, end_year: int) -> Dict[str, Any]:
        """Perform a PubMed search and return WebEnv/QueryKey"""
        search_term = self.pubmed.build_search_term(query, start_year, end_year)
        return self.pubmed.search(search_term)
    
    def fetch_articles(self, webenv: str, query_key: str, max_records: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch articles using webenv and query_key"""
        return self.pubmed.fetch_summaries_paged(webenv, query_key, page_size=self.config.pubmed_batch_size, max_records=max_records)