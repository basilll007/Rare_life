"""
Data processing module for Literature Harvester
Handles data merging, citation unification, and output formatting.
"""

import json
from datetime import datetime
from typing import Dict, List, Any


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