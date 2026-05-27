# Agent Bluecollar V5 - Distributed Broadband Mapping Scraper

Agent Bluecollar is a highly resilient, multi-agent automation tool designed to extract reliable broadband connectivity data from the FCC Broadband Map. Built with Python, FastAPI, and Playwright, it utilizes stealth browser techniques to bypass basic bot protection and retrieve both mobile and fixed broadband availability data.

## 🚀 Key Features

* **Native & Containerized Execution:** Designed to run seamlessly as a native application or in a scaled Docker Swarm/Compose environment.
* **Cross-Container Staggering:** Implements a global file-system based lock mechanism (`fcntl`) across multiple Docker replicas to enforce strict delay intervals between requests, mimicking human traffic patterns and preventing IP bans.
* **Playwright Stealth & Xvfb:** Uses `playwright-stealth` combined with a virtual frame buffer (`Xvfb`) and a robust font package to render complete browser canvases, presenting a genuine Linux desktop signature.
* **Asynchronous Webhook Delivery:** Fully decoupled request processing. The agent receives target coordinates via a REST API, queues the scraping task, and dispatches the formatted Markdown results to a provided webhook URL upon completion.
* **Fail-Fast Data Extraction:** Intelligent DOM polling immediately detects "no data" states or empty tables, aborting the process early to save compute resources.

## 🏗️ Architecture

The system is built for horizontal scalability:
1.  **Nginx Loadbalancer:** Acts as the entry point, distributing incoming API requests via round-robin.
2.  **FastAPI Worker Replicas:** Multiple Playwright agents running in parallel, sharing a synchronized data volume to coordinate global wait times.
3.  **Headless Control:** Full control over UI rendering for debugging vs. production environments via `.env` configurations.

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
