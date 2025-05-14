Google Traces 2019 Dashboard

The Google Traces 2019 Dashboard is a distributed web application that processes, analyzes, and visualizes Google Cluster Data 2019. It uses NGINX for load balancing, Flask for backend processing, Docker for containerization, and two interactive dashboards for real-time monitoring and log analysis. The system processes cluster events with priority-based round-robin scheduling and logs data to a shared file.
Features

Main Dashboard (index.html):
Displays total requests, average CPU/memory usage, event distribution (pie chart), server load (bar chart), CPU/memory usage (scatter chart), recent traces, and server logs.
Supports server filtering (all, app1, app2, app3), auto-refresh (every 1 second), and manual refresh.
Includes an educational section on load balancing, NGINX, Docker, and resumable downloads.


Log Analysis Dashboard (log_analysis.html):
Shows requests per app, handlers per app, event types, payload details, average CPU/memory utilization (bar chart), and priority distribution (histogram).
Auto-refreshes every 10 seconds.


Backend (wsgi.py):
Handles cluster event requests (/cluster/event/<event_type>/<collection_id>), serves API endpoints, and logs events with rate limiting (500 requests/minute).


Load Balancing (nginx.conf):
NGINX distributes requests across three Flask instances with round-robin scheduling and failover.


Data Processing (data_processor.py):
Processes Google Cluster Data CSV with priority-based round-robin scheduling, sending events to the backend.


Containerization (docker-compose.yml, Dockerfile):
Runs NGINX and Flask instances in Docker containers with shared logging.



Architecture
The system follows a microservices architecture, with components orchestrated by Docker Compose:
[Data Processor] --> [NGINX:80] --> [Flask Instances: app1:5000, app2:5001, app3:5002]
                        |                    |
                        v                    v
                 [Client: Browser]    [Shared Log: server_log.txt]
                 [Main Dashboard]     [Log Analysis Dashboard]


Data Processor: Reads CSV and sends POST requests to NGINX.
NGINX: Load balances requests to Flask instances.
Flask Instances: Process events, log to server_log.txt, and serve APIs.
Shared Log File: Stores event logs, read by dashboards.
Client (Browser): Visualizes data via dashboards.

Prerequisites

Docker and Docker Compose
Python 3.9+ (for running data_processor.py)
Google Cluster Data CSV (place in app/data/google_cluster_data.csv)

Installation

Clone the Repository:
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>


Prepare the CSV File:

Download the Google Cluster Data 2019 CSV and place it in app/data/google_cluster_data.csv.
Ensure it has columns: event, collection_id, resource_request, priority.


Build and Run Containers:
docker-compose up --build


This starts NGINX (http://localhost:80) and Flask instances (app1, app2, app3).
The output directory will be created for server_log.txt.


Run the Data Processor:
python Simulate_requets.py


Processes the CSV and sends events to the backend.



Usage

Access the Main Dashboard:

Open http://localhost in a browser.
View metrics, charts, traces, logs, and educational content.
Use the server filter (all, app1, app2, app3) and refresh button.


Access the Log Analysis Dashboard:

Start a local web server:cd app/render_template
python -m http.server 8000


Open http://localhost:8000/log_analysis.html.
View tables and charts for log analysis, auto-refreshing every 10 seconds.


Stop Containers:
docker-compose down



Technologies

Frontend: HTML5, CSS3, JavaScript, Chart.js, Font Awesome, Google Fonts (Poppins, Inter)
Backend: Flask, Flask-Limiter, Python logging
Load Balancing: NGINX
Containerization: Docker, Docker Compose
Data Processing: Pandas, Requests, JSON
Dependencies: Flask (2.0.1), Flask-Limiter (3.5.0), Pandas (1.5.3), NumPy (1.23.5), Redis (4.5.4, unused), Requests (2.28.1), Werkzeug (2.0.3)

Contributing

Fork the repository.
Create a feature branch (git checkout -b feature/your-feature).
Commit changes (git commit -m "Add your feature").
Push to the branch (git push origin feature/your-feature).
Open a pull request.


