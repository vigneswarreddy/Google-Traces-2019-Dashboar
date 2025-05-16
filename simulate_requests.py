import time
import requests
import pandas as pd
import json
import sys
from collections import defaultdict

# Configuration
DATA_FILE = "app/data/google_cluster_data.csv"  # Path to the Google Cluster Data CSV
BASE_URL = "http://localhost:80"  # Pointing to NGINX reverse proxy
REQUEST_DELAY = 0.01  # Delay between requests in seconds
BATCH_SIZE = 1000  # Process rows in batches to avoid memory issues
TIMEOUT = 5  # Timeout for HTTP requests in seconds
REQUESTS_PER_CYCLE = 100  # Max requests per Round Robin cycle

# Counter for tracking progress
total_rows_processed = 0
successful_requests = 0
failed_requests = 0

def group_by_priority(df):
    """Group dataframe rows by priority and sort by descending priority."""
    priority_groups = defaultdict(list)
    for _, row in df.iterrows():
        priority = row['priority']
        if pd.isna(priority):
            priority = 0  # Default for missing priority
        priority_groups[priority].append(row)
    
    # Sort by priority (descending)
    sorted_groups = sorted(priority_groups.items(), key=lambda x: x[0], reverse=True)
    print(f"Grouped into {len(sorted_groups)} priority levels.")
    return sorted_groups

def process_chunk(df_chunk, chunk_index):
    """Process a chunk of the dataframe with priority-based Round Robin scheduling."""
    global total_rows_processed, successful_requests, failed_requests
    
    print(f"Processing chunk {chunk_index + 1} (rows {total_rows_processed + 1} to {total_rows_processed + len(df_chunk)})...")
    
    # Group rows by priority
    priority_groups = group_by_priority(df_chunk)
    
    # Initialize round-robin indices for each priority level
    current_indices = {priority: 0 for priority, _ in priority_groups}
    
    # Process requests in Round Robin manner
    cycle_requests = 0
    while cycle_requests < REQUESTS_PER_CYCLE and any(current_indices[priority] < len(traces) for priority, traces in priority_groups):
        for priority, traces in priority_groups:
            if current_indices[priority] >= len(traces):
                continue  # Skip if all traces in this priority level are processed
            
            # Get the next trace
            row = traces[current_indices[priority]]
            total_rows_processed += 1
            
            # Extract required fields
            collection_id = row['collection_id']
            event_type = row['event']
            priority_val = row['priority'] if not pd.isna(row['priority']) else 0
            
            # Check for missing required fields
            if pd.isna(collection_id) or pd.isna(event_type):
                print(f"Skipping row {total_rows_processed}: Missing collection_id or event_type")
                failed_requests += 1
                current_indices[priority] += 1
                continue
            
            # Convert collection_id to string
            try:
                collection_id_str = f"{int(float(collection_id))}"
            except (ValueError, TypeError) as e:
                print(f"Skipping row {total_rows_processed}: Invalid collection_id {collection_id} ({e})")
                failed_requests += 1
                current_indices[priority] += 1
                continue
            
            # Parse resource_request to extract cpus and memory
            resource_request = row['resource_request']
            try:
                resources = json.loads(resource_request.replace("'", '"'))
                cpus = resources.get('cpus', 0)
                memory = resources.get('memory', 0)
            except (json.JSONDecodeError, AttributeError) as e:
                print(f"Row {total_rows_processed}: Failed to parse resource_request ({e}), defaulting to cpus=0, memory=0")
                cpus = 0
                memory = 0
            
            # Prepare the full payload with all columns
            payload = row.to_dict()
            for key, value in payload.items():
                if pd.isna(value):
                    payload[key] = None
                elif isinstance(value, (pd.Series, pd.DataFrame)):
                    payload[key] = str(value)
                if key == 'collection_id':
                    payload[key] = collection_id_str
            
            # Add cpus, memory, and priority to the payload
            payload['cpus'] = cpus
            payload['memory'] = memory
            payload['priority'] = priority_val
            
            # Construct the endpoint URL
            path = f"/cluster/event/{event_type}/{collection_id_str}"
            full_url = BASE_URL + path
            
            # Send POST request
            try:
                response = requests.post(
                    full_url,
                    json=payload,
                    timeout=TIMEOUT
                )
                print(f"Row {total_rows_processed}: Priority {priority_val}, Event {event_type}, Status {response.status_code}")
                if response.status_code == 200:
                    successful_requests += 1
                else:
                    print(f"  Error: {response.json().get('error', 'Unknown error')}")
                    failed_requests += 1
            except requests.RequestException as e:
                print(f"Row {total_rows_processed}: Failed to POST {path}: {e}")
                failed_requests += 1
            
            # Update round-robin index
            current_indices[priority] += 1
            cycle_requests += 1
            
            # Add delay to avoid overwhelming the server
            time.sleep(REQUEST_DELAY)
            
            # Break if cycle limit reached
            if cycle_requests >= REQUESTS_PER_CYCLE:
                break

# Load the Google Cluster Data
print("Loading CSV file...")
try:
    df_chunks = pd.read_csv(DATA_FILE, chunksize=BATCH_SIZE, usecols=['event', 'collection_id', 'resource_request', 'priority'])
except FileNotFoundError:
    print(f"Error: CSV file {DATA_FILE} not found.")
    sys.exit(1)
except pd.errors.ParserError:
    print(f"Error: Failed to parse CSV file {DATA_FILE}.")
    sys.exit(1)

# Process each chunk
for chunk_index, df_chunk in enumerate(df_chunks):
    process_chunk(df_chunk, chunk_index)
    # Add a small delay between chunks
    time.sleep(0.5)

# Final summary
print(f"\nCompleted processing {total_rows_processed} rows.")
print(f"Successful requests: {successful_requests}")
print(f"Failed requests: {failed_requests}")