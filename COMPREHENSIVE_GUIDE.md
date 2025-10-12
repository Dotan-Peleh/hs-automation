# HS Trends: Complete System Documentation

## 1. Introduction & Architecture

### 1.1. Overview
This document provides a comprehensive guide to the **HS Trends** system, a full-stack application designed to provide real-time insights, automated analysis, and intelligent alerting for Help Scout conversations.

The system ingests support tickets, enriches them using a Large Language Model (LLM), calculates a dynamic severity score, and sends contextual alerts to Slack, all while continuously learning from user feedback.

### 1.2. System Architecture
The application consists of three main components that can be run locally or deployed independently:

- **FastAPI Backend (`/api`)**: The core of the system. A Python application responsible for:
  - Ingesting Help Scout webhooks.
  - Communicating with the Help Scout API.
  - Enriching ticket data via the Anthropic (Claude) LLM.
  - Running the severity analysis engine.
  - Storing data in a PostgreSQL or SQLite database.
  - Sending alerts to Slack.
  - Serving a REST API for the frontend dashboard.

- **Next.js Frontend (`/dashboard`)**: A web-based dashboard for visualizing ticket trends and insights. It is a React application that fetches all of its data from the FastAPI backend.

- **Database**: A SQL database (PostgreSQL for production, SQLite for local development) that stores conversation data, enrichment results, and user feedback.

### 1.3. Data Flow
The end-to-end data flow for a new ticket is as follows:
1. A customer sends a support ticket to Help Scout.
2. Help Scout triggers a webhook event, sending a payload to the FastAPI backend (`/helpscout/webhook`).
3. The backend fetches the full conversation details from the Help Scout API.
4. The ticket content is sent to the LLM for enrichment (summary, intent, root cause).
5. The **Severity Engine** calculates a severity score and bucket (`low`, `medium`, `high`) based on the content and the LLM's output.
6. The enriched data is saved to the database.
7. If an agent has not yet replied, a formatted alert is sent to a designated Slack channel.
8. The frontend dashboard polls the backend's API endpoints to display real-time trends and insights.

---

## 2. Core Logic & Features

### 2.1. LLM Enrichment & Intent Classification
The system uses the Anthropic (Claude) LLM to understand the user's message. This is configured in `api/engine/llm.py`.

- **Intent Classification**: The LLM categorizes each ticket into a specific `intent`. This is the primary driver for the system's logic. A full list of intents can be found in `API-REFERENCE.md`.
- **Summary & Root Cause**: The LLM also generates a concise summary and a likely root cause for the issue.
- **Empty & Unreadable Ticket Detection**: The system has pre-processing logic to detect and flag tickets that are empty or contain incomprehensible gibberish, preventing the LLM from hallucinating and ensuring these tickets are always marked as `low` severity.

### 2.2. Severity Engine
The severity of a ticket is determined by a multi-layered process designed to be both consistent and responsive to emerging trends.

#### 2.2.1. Intent-Based Overrides
The primary mechanism for assigning severity is a set of rules based on the LLM-detected `intent`. This ensures that ticket priority aligns with business rules.

| Intent                      | Severity | Logic                                                                   |
| --------------------------- | -------- | ----------------------------------------------------------------------- |
| `crash_report`              | `high`   | App crashes are always high priority.                                   |
| `billing_issue`             | `high`   | Default for payment-related issues.                                     |
| `charge twice` (keyword)    | `high`   | Specific billing issue that is always high priority.                    |
| `refund` (keyword)          | `medium` | Refund requests are medium priority.                                    |
| `lost_progress`             | `high`   | A critical issue that severely impacts the user experience.             |
| `app freezing/stuck`        | `medium` | A significant usability issue.                                          |
| `gameplay_issue`            | `low`    | **Dynamic**: Can be escalated to `medium` or `high` based on volume.    |
| `delete_account`            | `low`    | An administrative task, not a critical issue.                           |
| `question`, `feedback`      | `low`    | Standard, non-urgent tickets.                                           |
| `incomplete_ticket`, `unreadable` | `low` | **Final Override**: These are always low priority.                      |

#### 2.2.2. Dynamic Severity for Gameplay Issues
To catch widespread but individually low-priority issues, the system automatically escalates the severity of `gameplay_issue` tickets if a high volume is detected in a short period.

- **3+ complaints** in 48 hours -> Severity is escalated to `medium`.
- **5+ complaints** in 48 hours -> Severity is escalated to `high`.

### 2.3. Slack Alerts
The system sends detailed, contextual alerts to Slack to keep the team informed.

- **Spam Prevention**: Alerts are **only sent if an agent has not yet replied** to the ticket.
- **Rich Formatting**: Alerts are formatted to be easily scannable and include:
  - **Title**: The user's `intent`.
  - **Severity**: Color-coded for priority.
  - **Platform, Device, and UserID**.
  - **Time**: The exact time the message was received.
  - **Special Tags**: Visual tags are added for high-priority or unique intents:
    - `🚨 DELETE_REQUEST`
    - `📭 EMPTY_TICKET`
    - `❓ UNREADABLE`

### 2.4. Continuous Learning from Feedback
The system features a powerful continuous learning loop that allows it to learn from your expertise.

1. **You Correct a Tag**: When you fix an incorrect intent or severity on the dashboard, the correction is saved to the `TicketFeedback` table in the database.
2. **System Fetches Examples**: The next time a new ticket arrives, the system retrieves the 5 most recent corrections you've made.
3. **AI Learns in Real-Time**: These corrections are injected into the LLM's prompt as "few-shot examples," effectively teaching the AI how to categorize tickets according to your preferences.

This creates a feedback loop where the system's accuracy improves over time, adapting to new issue types without requiring any code changes.

---

## 3. Getting Started: Local Development

### 3.1. Prerequisites
- Python 3.10+
- Node.js v18+
- An ngrok account (for testing webhooks locally)

### 3.2. Setup Backend
1.  Navigate to the `api` directory:
    ```bash
    cd hs-trends/api
    ```
2.  Create and activate a Python virtual environment:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```
3.  Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Set up your environment variables. Create a `.env` file in the `hs-trends` root directory:
    ```env
    # hs-trends/.env

    # Help Scout
    HS_API_TOKEN="your_helpscout_api_token"
    HS_WEBHOOK_SECRET="a_strong_secret_for_webhook_validation"

    # Anthropic LLM
    ANTHROPIC_API_KEY="your_anthropic_api_key"

    # Slack
    SLACK_BOT_TOKEN="your_slack_bot_token"
    SLACK_DEFAULT_CHANNEL_ID="your_slack_channel_id"

    # Database (uses SQLite by default)
    USE_SQLITE=1
    ```
5.  Run the FastAPI server:
    ```bash
    uvicorn app:app --reload --port 8080
    ```
    The API will be available at `http://localhost:8080`.

### 3.3. Setup Frontend
1.  In a new terminal, navigate to the `dashboard` directory:
    ```bash
    cd hs-trends/dashboard
    ```
2.  Install the Node.js dependencies:
    ```bash
    npm install
    ```
3.  Create a `.env.local` file in the `dashboard` directory and point it to your local backend:
    ```env
    # dashboard/.env.local
    NEXT_PUBLIC_API_BASE="http://localhost:8080"
    ```
4.  Run the Next.js development server:
    ```bash
    npm run dev
    ```
    The dashboard will be available at `http://localhost:3000/dashboard`.

### 3.4. Testing Webhooks with ngrok
1.  Expose your local API to the internet with ngrok:
    ```bash
    ngrok http 8080
    ```
2.  Copy the HTTPS forwarding URL provided by ngrok (e.g., `https://<unique_id>.ngrok-free.app`).
3.  In Help Scout, go to **Manage > Apps > Webhooks** and set your webhook URL to:
    `https://<unique_id>.ngrok-free.app/helpscout/webhook`
4.  Ensure you use the same secret you defined in your `.env` file.

---

## 4. Deployment
The recommended deployment strategy is to use **Render** for the backend and **Vercel** for the frontend.

For a complete, step-by-step guide, please refer to `DEPLOYMENT.md`.

---

## 5. API Reference
The backend exposes a number of endpoints for data retrieval and administrative tasks.

- `POST /helpscout/webhook`: The main ingestion endpoint.
- `GET /admin/dashboard`: Provides aggregated data for the frontend dashboard.
- `GET /admin/insights`: Returns a paginated list of enriched tickets.
- `POST /admin/ticket/feedback`: The endpoint used by the frontend to submit your corrections.

For a complete list of endpoints and their parameters, please refer to `API-REFERENCE.md`.

---

## 6. Database Schema
The database schema is defined in `api/models.py` and includes the following key tables:

- `hs_conversation`: Stores the raw conversation data fetched from Help Scout.
- `hs_enrichment`: Caches the results of the LLM analysis for each conversation.
- `ticket_feedback`: Stores the manual corrections you provide, which are used for the continuous learning loop.

---

## 7. Troubleshooting

- **CORS Errors**: If the frontend is blocked from accessing the backend, it's almost always because the backend API is crashing on startup. Check the API logs (either in your local terminal or on Render) for errors, which are often related to missing environment variables.
- **Empty Dashboard**: If the dashboard is empty, ensure that data is being ingested. You can manually trigger a backfill of recent tickets by calling `GET http://localhost:8080/admin/backfill`.
- **Git Push is Stuck**: A canceled git process can leave a stale `.lock` file. If `git push` hangs, delete the lock file in your local `.git` directory to resolve the issue.
