import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import networkx as nx
from pyvis.network import Network
import json
import tempfile
import os
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Any

# Import the new literature harvester library
from literature_harvester import LiteratureHarvester, Config

# Page config
st.set_page_config(
    page_title="Literature Harvester Dashboard",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

@st.cache_data
def load_payload(file_path: str) -> Dict[str, Any]:
    """Load and cache JSON payload"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error loading file: {e}")
        return {}

def flatten_items(payload: Dict[str, Any]) -> pd.DataFrame:
    """Convert payload items to DataFrame"""
    items = payload.get('items', [])
    if not items:
        return pd.DataFrame()
    
    rows = []
    for item in items:
        citations = item.get('citations')
        openalex = item.get('openalex', {})
        icite = item.get('icite', {})
        
        # Get citation values - handle null cases safely
        sources = citations.get('sources', {}) if citations is not None else {}
        oa_citations = sources.get('openalex', {}).get('value') if sources.get('openalex') else None
        ic_citations = sources.get('icite', {}).get('value') if sources.get('icite') else None
        
        # Extract concepts
        concepts = openalex.get('concepts', [])
        concept_str = ', '.join(concepts[:3]) if concepts else ''
        
        # Extract authors
        authors = item.get('authors', [])
        author_names = [auth.get('name', '') for auth in authors]
        author_str = ', '.join(author_names[:3])
        if len(author_names) > 3:
            author_str += f' (+{len(author_names)-3} more)'
        
        # Extract institutions
        institutions = []
        for author in authors:
            for inst in author.get('institutions', []):
                inst_name = inst.get('name', '')
                if inst_name and inst_name not in institutions:
                    institutions.append(inst_name)
        
        row = {
            'pmid': item.get('pmid', ''),
            'title': item.get('title', ''),
            'journal': item.get('journal', ''),
            'pub_year': item.get('pub_year', 0),
            'doi': item.get('doi', ''),
            'citations_value': citations.get('value', 0) if citations is not None else 0,
            'citations_source': citations.get('source_of_truth', '') if citations is not None else '',
            'discrepancy': citations.get('discrepancy', 0) if citations is not None else 0,
            'openalex_citations': oa_citations if oa_citations is not None else 0,
            'icite_citations': ic_citations if ic_citations is not None else 0,
            'concepts': concept_str,
            'authors': author_str,
            'author_list': author_names,
            'institutions': institutions,
            'has_openalex': oa_citations is not None,
            'has_icite': ic_citations is not None,
            'has_both': oa_citations is not None and ic_citations is not None
        }
        rows.append(row)
    
    return pd.DataFrame(rows)

def build_coauthor_edges(df: pd.DataFrame, max_nodes: int = 150) -> Tuple[List[Tuple], Dict[str, int]]:
    """Build coauthor network edges"""
    if df.empty:
        return [], {}
    
    # Count author frequencies
    author_counts = Counter()
    for authors in df['author_list']:
        for author in authors:
            if author.strip():
                author_counts[author] += 1
    
    # Get top authors
    top_authors = [author for author, _ in author_counts.most_common(max_nodes)]
    top_author_set = set(top_authors)
    
    # Build edges
    edges = []
    for authors in df['author_list']:
        paper_authors = [a for a in authors if a in top_author_set]
        for i, auth1 in enumerate(paper_authors):
            for auth2 in paper_authors[i+1:]:
                edges.append((auth1, auth2))
    
    # Count edge weights
    edge_counts = Counter(edges)
    weighted_edges = [(a1, a2, count) for (a1, a2), count in edge_counts.items()]
    
    return weighted_edges, author_counts

def render_pyvis_network(edges: List[Tuple], name_map: Dict[str, int]) -> str:
    """Render PyVis network and return HTML content."""
    net = Network(height="500px", width="100%", bgcolor="#222222", font_color="white")
    net.barnes_hut()
    
    # Add nodes
    for author, count in name_map.items():
        if count > 0:  # Only add authors with papers
            size = min(10 + count * 2, 50)
            net.add_node(author, label=author, size=size, title=f"{author}\nPapers: {count}")
    
    # Add edges
    for auth1, auth2, weight in edges:
        if auth1 in name_map and auth2 in name_map:
            net.add_edge(auth1, auth2, width=min(weight, 10), title=f"Collaborations: {weight}")
    
    # Generate HTML with better file handling for Windows
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
            temp_file = f.name
            net.save_graph(temp_file)
        
        # Read the file content
        with open(temp_file, 'r', encoding='utf-8') as html_file:
            html_content = html_file.read()
        
        return html_content
    except Exception as e:
        st.error(f"Error generating network visualization: {str(e)}")
        return "<div>Error generating network visualization</div>"
    finally:
        # Clean up temporary file with retry mechanism for Windows
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except PermissionError:
                # On Windows, sometimes the file is still locked, try again after a short delay
                import time
                time.sleep(0.1)
                try:
                    os.unlink(temp_file)
                except:
                    pass  # If we still can't delete it, let the OS clean it up later

def main():
    st.title("📚 Literature Harvester Dashboard")
    
    # Sidebar
    st.sidebar.header("Configuration")
    
    # Runtime input section
    st.sidebar.subheader("🔍 Run New Search")
    with st.sidebar.expander("Search Parameters", expanded=False):
        search_query = st.text_input("Search Query", placeholder="e.g., covid, diabetes, cancer")
        col1, col2 = st.columns(2)
        with col1:
            start_year = st.number_input("Start Year", min_value=1900, max_value=2024, value=2023)
        with col2:
            end_year = st.number_input("End Year", min_value=1900, max_value=2024, value=2023)
        
        max_records = st.number_input("Max Records", min_value=1, max_value=100, value=10)
        
        col3, col4 = st.columns(2)
        with col3:
            citations_source = st.selectbox("Citations Source", 
                                          options=["openalex", "icite", "both"], 
                                          index=0)
        with col4:
            citations_policy = st.selectbox("Citations Policy", 
                                          options=["prefer_openalex", "prefer_icite", "reconcile"], 
                                          index=2)
        
        if st.button("🚀 Run Search", type="primary"):
            if search_query.strip():
                with st.spinner("Running literature search..."):
                    try:
                        # Initialize the harvester with configuration
                        config = Config()
                        harvester = LiteratureHarvester(config)
                        
                        # Show search parameters
                        st.info(f"Searching for: '{search_query}' ({start_year}-{end_year})")
                        
                        # Run the search using the library
                        output_file = f"results_{search_query.replace(' ', '_')}_{start_year}_{end_year}.json"
                        
                        payload = harvester.harvest(
                            query=search_query,
                            start_year=start_year,
                            end_year=end_year,
                            max_records=max_records,
                            citations_source=citations_source,
                            citations_policy=citations_policy,
                            output_file=output_file,
                            verbose=False  # Don't print to console in Streamlit
                        )
                        
                        st.success("✅ Search completed successfully!")
                        
                        # Display summary
                        total_count = payload.get('pubmed', {}).get('total_count', 0)
                        fetched_count = payload.get('pubmed', {}).get('fetched_count', 0)
                        
                        st.write(f"**Total PubMed hits:** {total_count:,}")
                        st.write(f"**Fetched articles:** {fetched_count:,}")
                        st.write(f"**Results saved to:** {output_file}")
                        
                        # Update the file path input to the new file
                        st.session_state['file_path'] = output_file
                        
                        # Force refresh of the page to load new data
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Error running search: {str(e)}")
                        st.exception(e)  # Show full traceback for debugging
            else:
                st.warning("Please enter a search query")
    
    st.sidebar.divider()
    
    # File input
    st.sidebar.subheader("📁 Load Existing Results")
    file_path = st.sidebar.text_input("JSON File Path", 
                                     value=st.session_state.get('file_path', 'results.json'),
                                     key='file_path_input')
    
    if not os.path.exists(file_path):
        st.error(f"File not found: {file_path}")
        st.info("💡 Use the 'Run New Search' section above to generate results, or check the file path.")
        return
    
    # Load data
    payload = load_payload(file_path)
    if not payload:
        st.error("Failed to load data")
        return
    
    df = flatten_items(payload)
    if df.empty:
        st.warning("No data found in the file")
        return
    
    # Sidebar filters
    st.sidebar.header("Filters")
    
    # Year filter
    if 'pub_year' in df.columns and df['pub_year'].max() > 0:
        year_min, year_max = int(df['pub_year'].min()), int(df['pub_year'].max())
        year_range = st.sidebar.slider("Publication Year", year_min, year_max, (year_min, year_max))
        df_filtered = df[(df['pub_year'] >= year_range[0]) & (df['pub_year'] <= year_range[1])]
    else:
        df_filtered = df
    
    # Citation source filter
    source_options = ['All'] + list(df_filtered['citations_source'].unique())
    selected_source = st.sidebar.selectbox("Citation Source", source_options)
    if selected_source != 'All':
        df_filtered = df_filtered[df_filtered['citations_source'] == selected_source]
    
    # Text search
    search_text = st.sidebar.text_input("Search (Title/Journal)")
    if search_text:
        mask = (df_filtered['title'].str.contains(search_text, case=False, na=False) |
                df_filtered['journal'].str.contains(search_text, case=False, na=False))
        df_filtered = df_filtered[mask]
    
    # KPIs
    st.header("📊 Key Performance Indicators")
    
    pubmed_data = payload.get('pubmed', {})
    total_count = pubmed_data.get('total_count', 0)
    fetched_count = pubmed_data.get('fetched_count', 0)
    coverage = (fetched_count / total_count * 100) if total_count > 0 else 0
    
    both_sources = df_filtered['has_both'].sum()
    high_discrepancy = 0
    if both_sources > 0:
        high_disc_mask = (df_filtered['has_both'] & 
                         (df_filtered['discrepancy'] / df_filtered[['openalex_citations', 'icite_citations']].max(axis=1) > 0.1))
        high_discrepancy = high_disc_mask.sum()
    
    high_disc_pct = (high_discrepancy / both_sources * 100) if both_sources > 0 else 0
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total PubMed Hits", f"{total_count:,}")
    with col2:
        st.metric("Fetched Articles", f"{fetched_count:,}")
    with col3:
        st.metric("Coverage", f"{coverage:.1f}%")
    with col4:
        st.metric("Both Sources", both_sources)
    with col5:
        st.metric("High Discrepancy", f"{high_disc_pct:.1f}%")
    
    # Charts
    st.header("📈 Visualizations")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Yearly publications
        st.subheader("Publications by Year")
        if 'pub_year' in df_filtered.columns:
            year_counts = df_filtered['pub_year'].value_counts().sort_index()
            fig1 = px.bar(x=year_counts.index, y=year_counts.values, 
                         labels={'x': 'Year', 'y': 'Count'})
            fig1.update_layout(showlegend=False)
            st.plotly_chart(fig1, width='stretch')
    
    with col2:
        # Citation scatter
        st.subheader("OpenAlex vs iCite Citations")
        scatter_df = df_filtered[df_filtered['has_both']].copy()
        if not scatter_df.empty:
            fig2 = px.scatter(scatter_df, x='openalex_citations', y='icite_citations',
                             hover_data=['title'], opacity=0.7)
            # Add diagonal line
            max_val = max(scatter_df['openalex_citations'].max(), scatter_df['icite_citations'].max())
            fig2.add_trace(go.Scatter(x=[0, max_val], y=[0, max_val], 
                                    mode='lines', name='y=x', line=dict(dash='dash')))
            st.plotly_chart(fig2, width='stretch')
        else:
            st.info("No articles with both citation sources")
    
    col3, col4 = st.columns(2)
    
    with col3:
        # Discrepancy histogram
        st.subheader("Citation Discrepancy Distribution")
        disc_df = df_filtered[df_filtered['has_both'] & (df_filtered['discrepancy'] > 0)]
        if not disc_df.empty:
            fig3 = px.histogram(disc_df, x='discrepancy', nbins=20)
            st.plotly_chart(fig3, width='stretch')
        else:
            st.info("No discrepancy data available")
    
    with col4:
        # Top authors
        st.subheader("Top Authors by Papers")
        author_counts = Counter()
        for authors in df_filtered['author_list']:
            for author in authors:
                if author.strip():
                    author_counts[author] += 1
        
        if author_counts:
            top_10 = author_counts.most_common(10)
            fig4 = px.bar(x=[count for _, count in top_10], 
                         y=[name for name, _ in top_10],
                         orientation='h', labels={'x': 'Papers', 'y': 'Author'})
            fig4.update_layout(yaxis={'categoryorder': 'total ascending'})
            st.plotly_chart(fig4, width='stretch')
    
    # Top institutions
    st.subheader("Top Institutions by Papers")
    inst_counts = Counter()
    for institutions in df_filtered['institutions']:
        for inst in institutions:
            if inst.strip():
                inst_counts[inst] += 1
    
    if inst_counts:
        top_10_inst = inst_counts.most_common(10)
        fig5 = px.bar(x=[name for name, _ in top_10_inst], 
                     y=[count for _, count in top_10_inst],
                     labels={'x': 'Institution', 'y': 'Papers'})
        fig5.update_xaxes(tickangle=45)
        st.plotly_chart(fig5, width='stretch')
    
    # Data table
    st.header("📋 Article Data")
    
    # Prepare display dataframe
    display_df = df_filtered.copy()
    if 'doi' in display_df.columns:
        display_df['doi_link'] = display_df['doi'].apply(
            lambda x: f"https://doi.org/{x}" if x else ""
        )
    
    # Select columns for display
    display_cols = ['pub_year', 'pmid', 'title', 'journal', 'doi', 
                   'citations_value', 'discrepancy', 'concepts']
    available_cols = [col for col in display_cols if col in display_df.columns]
    
    st.dataframe(
        display_df[available_cols],
        width='stretch',
        column_config={
            "doi": st.column_config.LinkColumn("DOI", display_text="Link"),
            "title": st.column_config.TextColumn("Title", width="large"),
            "concepts": st.column_config.TextColumn("Concepts", width="medium")
        }
    )
    
    # Coauthor network
    st.header("🕸️ Coauthor Network")
    
    if st.button("Generate Network"):
        with st.spinner("Building coauthor network..."):
            edges, name_map = build_coauthor_edges(df_filtered, max_nodes=150)
            
            if edges:
                html_content = render_pyvis_network(edges, name_map)
                st.components.v1.html(html_content, height=500)
                st.info(f"Network shows {len(name_map)} authors with {len(edges)} collaborations")
            else:
                st.warning("No coauthor relationships found in the data")

if __name__ == "__main__":
    main()