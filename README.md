# Enterprise Agent Orchestrator (`crewctl`)

An enterprise-grade, **no-code AI agent orchestration framework** built on top of CrewAI. It allows organizations to orchestrate teams of specialized AI agents to execute complex, multi-system workflows using simple text configurations (`.yaml` files).

---

## 🎯 When to Use `crewctl` vs. `crewai`

Understanding the landscape of AI frameworks helps identify where this orchestrator excels compared to writing vanilla CrewAI code:

| Feature / Aspect | `crewai` (Vanilla) | `crewctl` (This Framework) |
| :--- | :--- | :--- |
| **Configuration** | Code-first. Requires writing verbose Python files to declare agents, tasks, and crews. | **No-Code / Configuration-first**. Define your entire workforce in simple, readable YAML files (`agents.yaml`, `tasks.yaml`). |
| **Security & Access Control** | None out of the box. Agents can call any Python functions or tools imported in scope. | **Enterprise Security**. Built-in Role-Based Access Control (`rbac.yaml`) restricting exactly which agents can run which tool/connector methods. |
| **Monitoring & Audit Logs** | Basic terminal logs or Third-party integrations (e.g. Agentops). | **Full Observability**. CLI audit playback (`crewctl audit`), detailed run event tracking, and an out-of-the-box Web UI dashboard (`crewctl ui`). |
| **Data / RAG Ingestion** | Requires writing custom Python loaders and chunkers manually. | **Declarative Knowledge Base**. Configure local PDFs/Confluence in `memory.yaml` and index automatically using `crewctl index`. |
| **Enterprise Connectors** | Must write manual code to integrate Jira, SAP, ServiceNow, Outlook, etc. | **Pre-built Connectors**. Standard suite of enterprise-grade integrations (Jira, SAP, ServiceNow, Outlook, SharePoint) usable via YAML. |

---

## 🏢 4 Detailed Enterprise Workflow Examples

These examples illustrate how different agents collaborate from start to end to solve real business challenges.

### Example 1: Corporate Financial Auditing & SEC Compliance
*   **Business Problem:** A compliance department needs to continuously monitor SEC filings, audit internal financial records, and flag compliance anomalies against regulatory frameworks.
*   **The Workflow:**
    ```
    [SEC Filing/Ledger PDF Uploaded] 
          │
          ▼
    [1. SEC Data Ingester Agent] ──(Extracts Balance Sheet details)──► [2. Internal Audit Auditor Agent]
                                                                               │
                                                                       (Matches ledger items)
                                                                               │
                                                                               ▼
    [Report Compiled] ◄──(Validates SOX compliance)── [3. Compliance Inspector Agent]
    ```
    *   **Agent 1 (SEC Data Ingester):** Uses `knowledge.search` to scan SEC filings and extract target financial metrics (debts, equity, revenue).
    *   **Agent 2 (Internal Audit Auditor):** Uses `sap.query_inventory` or SQL database queries to match internal transactional ledgers against the SEC filing numbers.
    *   **Agent 3 (Compliance Inspector):** Cross-references discrepancies with stored Sarbanes-Oxley (SOX) compliance rules in the local RAG vector store and compiles a PDF audit report.
*   **End Output:** A detailed Compliance Audit Report highlighting any financial anomalies or compliance risks.

---

### Example 2: Enterprise IT Service Triage & Patching (ServiceNow to Jira)
*   **Business Problem:** Helpdesks spend hundreds of hours triaging tickets, identifying bugs, creating tickets for developers, and replying to users.
*   **The Workflow:**
    ```
    [ServiceNow Incident Triggered]
          │
          ▼
    [1. Support Triage Agent] ──(Parses system error messages)──► [2. Database Diagnostics Agent]
                                                                              │
                                                                   (Queries database logs)
                                                                              │
                                                                              ▼
    [Confirmation Email] ◄──(Updates status & files bug)── [3. System Administrator Agent]
    ```
    *   **Agent 1 (Support Triage):** Fetches the incident payload via the `servicenow` connector, identifies the system error codes, and summarizes the affected user details.
    *   **Agent 2 (Database Diagnostics):** Uses the database connector to inspect recent server errors matching the incident timestamp.
    *   **Agent 3 (System Administrator):** Creates a high-priority bug ticket in Jira via the `jira` connector, updates the ServiceNow incident status, and sends a diagnostic summary to the customer via `outlook.send_email`.
*   **End Output:** Automatically filed developer bug report in Jira, updated ServiceNow ticket, and customer status update email.

---

### Example 3: Automated Procurement & SAP Invoice Matching
*   **Business Problem:** Accounts Payable departments must manually match incoming vendor invoice documents against SAP Purchase Orders (PO) to verify prices before making payments.
*   **The Workflow:**
    ```
    [Inbound Vendor Invoice PDF]
          │
          ▼
    [1. Invoice Extractor Agent] ──(Extracts Line Items & PO #)──► [2. SAP Purchase Order Auditor Agent]
                                                                               │
                                                                    (Fetches matching POs)
                                                                               │
                                                                               ▼
    [Approval Released] ◄──(Flags matching issues)── [3. Financial Approver Agent]
    ```
    *   **Agent 1 (Invoice Extractor):** Parses vendor invoices from a local folder, extracting total costs, line items, and Purchase Order numbers.
    *   **Agent 2 (SAP Purchase Order Auditor):** Connects to SAP using the `sap` connector, retrieves the corresponding PO records, and compares line item prices.
    *   **Agent 3 (Financial Approver):** Checks for price variances. If the variance is under 2%, it calls SAP transaction tools to release the payment. If above 2%, it flags the invoice for manual review.
*   **End Output:** Invoice automatically approved/paid in SAP, or routed to a manual queue with detailed discrepancy reasons.

---

### Example 4: Customer Feedback Analysis & CRM Enrichment
*   **Business Problem:** Customer success teams need to process hundreds of customer survey feedbacks, categorize issues, update CRM profiles, and trigger escalations.
*   **The Workflow:**
    ```
    [Feedback Survey Received]
          │
          ▼
    [1. Sentiment Classifier Agent] ──(Extracts core frustration)──► [2. Solutions Engineer Agent]
                                                                                │
                                                                     (Queries knowledge base)
                                                                                │
                                                                                ▼
    [Salesforce/CRM Updated] ◄──(Schedules follow-up email)── [3. Account Manager Agent]
    ```
    *   **Agent 1 (Sentiment Classifier):** Reads survey text, scores customer sentiment (positive, neutral, negative), and tags topics (billing, usability, bug).
    *   **Agent 2 (Solutions Engineer):** For negative responses, searches the local Confluence knowledge database (`knowledge.search`) for troubleshooting guides.
    *   **Agent 3 (Account Manager):** Logs the sentiment and tags into the customer CRM database, drafts a personalized recovery email via Outlook, and schedules a follow-up task.
*   **End Output:** Auto-enriched CRM profiles and personalized response drafts generated instantly.

---

## 🛠️ Step-by-Step Setup Guide

Follow these steps to set up the orchestrator on your local machine.

### Prerequisites
Make sure you have python installed. You can check this by running:
```bash
python --version
```
*(If Python is not installed, download **Python 3.12** from [python.org](https://www.python.org/downloads/)).*

---

### Step 1: Download the Project
Clone this repository to your computer and change to its directory:
```bash
git clone <repository_url>
cd enterprise-agent
```

### Step 2: Create a Virtual Environment
A virtual environment ensures the project's dependencies do not interfere with other software on your system.

*   **On macOS or Linux:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```
*   **On Windows (Command Prompt):**
    ```cmd
    python -m venv .venv
    .venv\Scripts\activate.bat
    ```
*   **On Windows (PowerShell):**
    ```powershell
    python -m venv .venv
    .venv\Scripts\Activate.ps1
    ```

### Step 3: Install the Package
Install all required libraries and dependencies:
```bash
pip install -e .
```

### Step 4: Configure API Credentials
You need to provide your API keys to authorize agents to communicate with LLM providers. Run the command matching your provider in your terminal:

*   **For OpenAI Models (e.g. GPT-4o):**
    ```bash
    export OPENAI_API_KEY="your-openai-api-key"
    ```
*   **For Anthropic Models (e.g. Claude 3.5 Sonnet):**
    ```bash
    export ANTHROPIC_API_KEY="your-anthropic-api-key"
    ```
*   **For Google Gemini Models:**
    ```bash
    export GEMINI_API_KEY="your-gemini-api-key"
    ```
*(On Windows Command Prompt, use `set` instead of `export`, for example: `set OPENAI_API_KEY="your-key"`).*

---

### Step 5: Configure the Workforce (No-Code Configuration)

Customize the `.yaml` files in the root folder using any text editor:
1.  **`config.yaml`**: Set global parameters (default LLM model, execution style like `sequential` or `parallel`).
2.  **`agents.yaml`**: Specify agent roles, backstories, and which tools they have access to.
3.  **`tasks.yaml`**: Define instructions, outputs, and dependencies for each task.
4.  **`rbac.yaml`**: Authorize permissions for agents to use specific connectors.
5.  **`memory.yaml`**: Configure corporate PDFs or Confluence pages for the local search index.

---

### Step 6: Start Ingestion & Execution

1.  **Ingest Knowledge Sources (Optional RAG Ingestion):**
    If you configured PDF/Confluence files in `memory.yaml`, ingest them into the vector database:
    ```bash
    crewctl index
    ```
    *This computes source hashes, chunks text incrementally, and saves it to a local vector store.*

2.  **Run the Workflows:**
    Execute the entire agent crew:
    ```bash
    crewctl run
    ```
    *All agent thoughts, tool execution results, costs, and token tallies will stream directly to your terminal.*

---

## 🔌 Adding a Custom Connector (Tool)

You can easily extend the orchestrator with custom tools or third-party APIs. Follow these steps to build and register a new connector:

1. **Create the Connector Class:**
   Create a new Python file in the `connectors/` directory (e.g., `connectors/mytool.py`) and subclass `BaseConnector` from [connectors/base.py](file:///Users/anishtejwani/Desktop/projects/enterprise-agent/connectors/base.py). Each public method in the class automatically becomes a callable tool for your agents:
   ```python
   from connectors.base import BaseConnector

   class MyToolConnector(BaseConnector):
       def my_method(self, arg1: str) -> str:
           """
           Provide a detailed docstring explaining what the tool does.
           The LLM uses this description to understand when to invoke this tool.
           """
           return f"Executed my_method with {arg1}"
   ```

2. **Register the Connector:**
   Add your new connector to `CONNECTOR_MAP` in [runtime/orchestrator.py](file:///Users/anishtejwani/Desktop/projects/enterprise-agent/runtime/orchestrator.py):
   ```python
   from connectors.mytool import MyToolConnector

   CONNECTOR_MAP: Dict[str, Any] = {
       # ... existing connectors ...
       "mytool": MyToolConnector,
   }
   ```

3. **Grant RBAC Permissions:**
   Declare the tool in `rbac.yaml` under the appropriate agent role so that the security validator permits its execution:
   ```yaml
   roles:
     my_agent_role:
       allowed_tools:
         - mytool.my_method
   ```

4. **Reference in YAML Configurations:**
   Assign the tool to your agent in `agents.yaml`:
   ```yaml
   tools:
     - mytool.my_method
   ```
