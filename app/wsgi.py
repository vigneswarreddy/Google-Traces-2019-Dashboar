from flask import Flask, render_template, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime
import socket
import os
import re
import logging
import logging.handlers
import fcntl
import json

app = Flask(__name__, template_folder='render_template')

# Set up logging with RotatingFileHandler for thread-safety
os.makedirs("output", exist_ok=True)
log_file = "output/server_log.txt"
handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
formatter = logging.Formatter('%(asctime)s - App: %(app_name)s - Handled by: %(container_id)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Set up rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["500 per minute"]
)

# Function to get the app name from environment variable
def get_app_name():
    port = os.environ.get('PORT', '5000')
    port_to_app = {
        '5000': 'app1',
        '5001': 'app2',
        '5002': 'app3'
    }
    app_name = port_to_app.get(port, 'unknown')
    if app_name == 'unknown':
        logger.warning("Could not infer app name for port %s. Defaulting to 'unknown'.", port)
    return app_name

# Function to build a dynamic mapping of app names to container IDs from logs
def build_app_container_mapping():
    app_to_containers = {'app1': [], 'app2': [], 'app3': []}
    
    if not os.path.exists(log_file):
        return app_to_containers
    
    with open(log_file, "r") as f:
        lines = f.readlines()
    
    for line in lines:
        match = re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - App: (\S+) - Handled by: (\S+) - path: (.*)', line)
        if match:
            app_name = match.group(1)
            container_id = match.group(2)
            if app_name in app_to_containers and container_id not in app_to_containers[app_name]:
                app_to_containers[app_name].append(container_id)
                logger.info("Mapped container ID %s to app %s", container_id, app_name)
    
    return app_to_containers

# Helper function for logging requests
def log_request(path, status=None, payload=None):
    container_id = socket.gethostname()
    app_name = get_app_name()
    
    # Log the request
    extra = {'app_name': app_name, 'container_id': container_id}
    logger.info("path: %s", path, extra=extra)
    
    # Log specific cluster event with status if provided
    if status and path.startswith('/cluster/event/'):
        extra['status'] = status
        logger.info("%s | Status: %d", path, status, extra=extra)
    
    # Log the full payload if provided (for POST requests)
    if payload:
        extra['payload'] = json.dumps(payload, default=str)
        logger.info("Payload: %s", json.dumps(payload, default=str), extra=extra)
    
    return container_id

# Helper function to read all log entries
def read_logs():
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            return [line.strip() for line in f.readlines()]
    return []

# Helper function to filter logs by container IDs
def filter_logs(container_ids):
    all_logs = read_logs()
    filtered_logs = []
    for log in all_logs:
        for container_id in container_ids:
            if f"Handled by: {container_id}" in log or (f" | Status: " in log and container_id in all_logs[all_logs.index(log) - 1]):
                filtered_logs.append(log)
                break
    return filtered_logs

# Helper function to parse logs with container ID filtering
def parse_logs(container_ids):
    events = []
    
    if not os.path.exists(log_file):
        return events
    
    with open(log_file, "r") as f:
        lines = f.readlines()
    
    for i, line in enumerate(lines):
        general_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - App: \S+ - Handled by: (\S+) - path: (/cluster/event/[^?]+)(\?cpus=[\d.]+&memory=[\d.]+)?', line)
        if general_match:
            timestamp = general_match.group(1)
            container_id = general_match.group(2)
            path = general_match.group(3)
            query = general_match.group(4) or ''
            
            if container_ids and container_id not in container_ids:
                continue
            
            path_match = re.match(r'/cluster/event/([^/]+)/([^?]+)', path)
            if not path_match:
                continue
                
            event_type = path_match.group(1).upper()
            collection_id = path_match.group(2)
            
            # Extract cpus and memory from query string (GET request) or payload (POST request)
            cpu = memory = 0
            if query:  # GET request
                query_match = re.search(r'cpus=([\d.]+)&memory=([\d.]+)', query)
                if query_match:
                    cpu = float(query_match.group(1))
                    memory = float(query_match.group(2))
            else:  # POST request, look for payload in the next few lines
                for j in range(i + 1, min(i + 4, len(lines))):
                    payload_match = re.match(r'.*Payload: ({.*})', lines[j])
                    if payload_match:
                        try:
                            payload = json.loads(payload_match.group(1))
                            cpu = float(payload.get('cpus', 0))
                            memory = float(payload.get('memory', 0))
                        except (json.JSONDecodeError, ValueError):
                            logger.warning("Failed to parse payload for event at line %d", i)
                        break
            
            status = None
            for j in range(i + 1, min(i + 4, len(lines))):
                status_match = re.match(rf'.*path: {re.escape(path + query)}.*\| Status: (\d+)', lines[j])
                if status_match:
                    status = int(status_match.group(1))
                    break
            
            events.append({
                'timestamp': timestamp,
                'container_id': container_id,
                'event_type': event_type,
                'collection_id': collection_id,
                'cpu': cpu,
                'memory': memory,
                'status': status,
                'priority': 0
            })
    
    return events

# Helper function to extract CPU and memory usage
def extract_cpu_memory_usage(container_ids):
    events = parse_logs(container_ids)
    cpu_usage = [event['cpu'] for event in events]
    memory_usage = [event['memory'] for event in events]
    return cpu_usage[-100:], memory_usage[-100:]

@app.route('/')
def home():
    log_request("/")
    logs = read_logs()
    
    # Calculate metrics for success rate and avg priority
    events = parse_logs(None)  # Pass None to include all container IDs
    total_requests = len(events)
    success_rate = 0
    avg_priority = 0
    if total_requests > 0:
        success_requests = sum(1 for event in events if event['status'] == 200)
        success_rate = (success_requests / total_requests * 100)
        avg_priority = sum(event['priority'] for event in events) / total_requests
    
    return render_template('index.html', 
                         logs=logs, 
                         success_rate=round(success_rate, 1), 
                         avg_priority=round(avg_priority, 1))

@app.route('/<path:requested_path>')
def catch_all(requested_path):
    full_path = "/" + requested_path
    log_request(full_path)
    logs = read_logs()
    
    # Calculate metrics for success rate and avg priority
    events = parse_logs(None)  # Pass None to include all container IDs
    total_requests = len(events)
    success_rate = 0
    avg_priority = 0
    if total_requests > 0:
        success_requests = sum(1 for event in events if event['status'] == 200)
        success_rate = (success_requests / total_requests * 100)
        avg_priority = sum(event['priority'] for event in events) / total_requests
    
    return render_template('index.html', 
                         logs=logs, 
                         success_rate=round(success_rate, 1), 
                         avg_priority=round(avg_priority, 1))

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/cluster/event/<event_type>/<collection_id>', methods=['GET', 'POST'])
@limiter.limit("500 per minute")
def cluster_event(event_type, collection_id):
    container_id = socket.gethostname()
    
    if request.method == 'GET':
        # Existing GET request handling
        cpus = request.args.get('cpus', '0')
        memory = request.args.get('memory', '0')
        path = f"/cluster/event/{event_type}/{collection_id}?cpus={cpus}&memory={memory}"
        status = 500 if event_type.upper() == 'FAIL' else 200
        log_request(path, status=status)
    else:  # POST request
        try:
            payload = request.get_json()
            if not payload:
                logger.warning("Received POST request with no JSON payload")
                return jsonify({"error": "No JSON payload provided"}), 400
            
            # Extract cpus and memory for compatibility with existing dashboard
            cpus = payload.get('cpus', 0)
            memory = payload.get('memory', 0)
            path = f"/cluster/event/{event_type}/{collection_id}"
            status = 500 if event_type.upper() == 'FAIL' else 200
            log_request(path, status=status, payload=payload)
        except Exception as e:
            logger.error("Failed to process POST request: %s", str(e))
            return jsonify({"error": "Invalid JSON payload"}), 400
    
    logs = read_logs()
    return render_template('index.html', logs=logs)

@app.route('/metrics')
@limiter.limit("500 per minute")
def get_metrics():
    server_filter = request.args.get('server', 'all')
    app_to_containers = build_app_container_mapping()
    container_ids = app_to_containers.get(server_filter, []) if server_filter != 'all' else None
    events = parse_logs(container_ids)
    
    total_requests = len(events)
    if total_requests == 0:
        return jsonify({
            'total_requests': 0,
            'success_rate': 0,
            'avg_cpu': 0,
            'avg_memory': 0,
            'avg_priority': 0
        })
    
    success_requests = sum(1 for event in events if event['status'] == 200)
    success_rate = (success_requests / total_requests * 100) if total_requests > 0 else 0
    avg_cpu = sum(event['cpu'] for event in events) / total_requests
    avg_memory = sum(event['memory'] for event in events) / total_requests
    avg_priority = sum(event['priority'] for event in events) / total_requests
    
    return jsonify({
        'total_requests': total_requests,
        'success_rate': round(success_rate, 1),
        'avg_cpu': round(avg_cpu, 4),
        'avg_memory': round(avg_memory, 4),
        'avg_priority': round(avg_priority, 1)
    })

@app.route('/event_distribution')
@limiter.limit("500 per minute")
def get_event_distribution():
    server_filter = request.args.get('server', 'all')
    app_to_containers = build_app_container_mapping()
    container_ids = app_to_containers.get(server_filter, []) if server_filter != 'all' else None
    events = parse_logs(container_ids)
    
    event_counts = {'FAIL': 0, 'SCHEDULE': 0, 'FINISH': 0, 'ENABLE': 0, 'EVICT': 0, 'LOST': 0}
    for event in events:
        event_type = event['event_type']
        if event_type in event_counts:
            event_counts[event_type] += 1
    
    return jsonify(event_counts)

@app.route('/server_load')
@limiter.limit("500 per minute")
def get_server_load():
    server_filter = request.args.get('server', 'all')
    app_to_containers = build_app_container_mapping()
    container_ids = app_to_containers.get(server_filter, []) if server_filter != 'all' else None
    events = parse_logs(container_ids)
    
    server_counts = {'app1': 0, 'app2': 0, 'app3': 0}
    for event in events:
        for server, ids in app_to_containers.items():
            if event['container_id'] in ids:
                server_counts[server] += 1
                break
    
    return jsonify(server_counts)

@app.route('/cpu_memory_usage')
@limiter.limit("500 per minute")
def get_cpu_memory_usage():
    server_filter = request.args.get('server', 'all')
    app_to_containers = build_app_container_mapping()
    container_ids = app_to_containers.get(server_filter, []) if server_filter != 'all' else None
    cpu_usage, memory_usage = extract_cpu_memory_usage(container_ids)
    return jsonify({
        'cpu_usage': cpu_usage or [0],
        'memory_usage': memory_usage or [0]
    })

@app.route('/recent_traces')
@limiter.limit("500 per minute")
def get_recent_traces():
    server_filter = request.args.get('server', 'all')
    app_to_containers = build_app_container_mapping()
    container_ids = app_to_containers.get(server_filter, []) if server_filter != 'all' else None
    events = parse_logs(container_ids)
    
    recent_events = events[-5:]
    traces = []
    for event in recent_events:
        traces.append({
            'time': event['timestamp'],
            'instance': event['container_id'],
            'type': event['event_type'],
            'priority': event['priority'],
            'cpu': event['cpu'],
            'memory': event['memory'],
            'event': event['event_type']
        })
    
    return jsonify(traces)

@app.route('/logs')
@limiter.limit("500 per minute")
def get_logs():
    server_filter = request.args.get('server', 'all')
    app_to_containers = build_app_container_mapping()
    container_ids = app_to_containers.get(server_filter, []) if server_filter != 'all' else None
    if container_ids:
        logs = filter_logs(container_ids)
    else:
        logs = read_logs()
    return jsonify(logs)

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)