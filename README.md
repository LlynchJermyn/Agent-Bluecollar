# Agent Bluecollar V5 - Distributed Broadband Mapping Scraper

Agent Bluecollar is a highly resilient, multi-agent automation tool designed to extract reliable broadband connectivity data from the FCC Broadband Map. Built with Python, FastAPI, and Playwright, it utilizes stealth browser techniques to bypass basic bot protection and retrieve both mobile and fixed broadband availability data.

## 🚀 Key Features

* **Native & Containerized Execution:** Designed to run seamlessly as a native application or in a scaled Docker Swarm/Compose environment.
* **Cross-Container Staggering:** Implements a global, cross-platform file-system based lock mechanism (`filelock`) across multiple Docker replicas to enforce strict delay intervals between requests, mimicking human traffic patterns and preventing IP bans.
* **Playwright Stealth & Xvfb:** Uses `playwright-stealth` combined with a virtual frame buffer (`Xvfb`) and a robust font package to render complete browser canvases, presenting a genuine Linux desktop signature.
* **Asynchronous Webhook Delivery:** Fully decoupled request processing. The agent receives target coordinates via a REST API, queues the scraping task, and dispatches the formatted Markdown results to a provided webhook URL upon completion.
* **Fail-Fast Data Extraction:** Intelligent DOM polling immediately detects "no data" states or empty tables, aborting the process early to save compute resources.

## 🏗️ Architecture

The system is built for horizontal scalability:
1.  **Nginx Loadbalancer:** Acts as the entry point, distributing incoming API requests via round-robin with dynamic internal DNS resolution.
2.  **FastAPI Worker Replicas:** Multiple Playwright agents running in parallel, sharing a synchronized data volume to coordinate global wait times using Semaphores.
3.  **Headless Control:** Full control over UI rendering for debugging vs. production environments via `.env` configurations.

## ⚙️ Configuration (Environment Variables)

The agent is entirely configured via a `.env` file. Create a `.env` file in the root directory based on the following structure before starting the system:

```env
# Agent Control
HEADLESS=true
API_PORT=8001
LOG_LEVEL=INFO

# Resource Management (Browsers per container)
MAX_CONCURRENT_BROWSERS=2

# Akamai & Bot-Protection
GLOBAL_STAGGER_SECONDS=10.0
TYPING_DELAY_MS=40
HOVER_DELAY_MS=400

# Timeouts & Polling
PAGE_TIMEOUT_MS=40000
POLLING_TIMEOUT_MS=40000
POLLING_INTERVAL_MS=500

# System (Internal)
SHARED_LOCK_FILE=/shared/stagger.lock


## 📋 API Usage

**Endpoint:** `POST /api/v1/fcc_agent_bluecollar`

**Payload Example:**
```json
{
  "store_id": 1045,
  "address": "123 Main St, New York, NY",
  "lat": 40.7128,
  "lon": -74.0060,
  "broadband_type": "mobile" OR "fixed",
  "webhook_url": "[https://your-backend.com/webhook/receive](https://your-backend.com/webhook/receive)"
}
