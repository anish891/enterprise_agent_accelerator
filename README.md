# Enterprise Agent Orchestrator (`crewctl`)

An enterprise-grade, no-code AI agent orchestration framework built on top of CrewAI. It supports sequential, hierarchical, and parallel task execution, local RAG (Knowledge Memory), RBAC security, and custom enterprise connectors.

---

## Getting Started

Follow these step-by-step instructions to set up and run the orchestrator on your local machine.

### Step 1: Clone the Repository
Clone the codebase and navigate into the project directory:
```bash
git clone <repository_url>
cd enterprise-agent
```

### Step 2: Create a Virtual Environment (Python 3.12)
Create a clean virtual environment using Python 3.12:
```bash
python3.12 -m venv .venv
```

### Step 3: Activate the Virtual Environment
Activate the environment based on your operating system:
* **macOS / Linux:**
  ```bash
  source .venv/bin/activate
  ```
* **Windows (Command Prompt):**
  ```cmd
  .venv\Scripts\activate.bat
  ```
* **Windows (PowerShell):**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```

### Step 4: Install the Package in Editable Mode
Install the project and its dependencies in development/editable mode:
```bash
pip install -e .
```

---

## Configuration

### 1. Configure the LLM
The LLM settings are managed in `config.yaml`. You can set the default model used by your agents:

```yaml
# config.yaml
secrets_backend: env             # env / vault / aws
max_steps_default: 15
process: parallel                # parallel / sequential / hierarchical

# Default LLM for all agents
default_llm: azure/gpt-4o
```

Supported LLM providers include:
* **Azure OpenAI:** `azure/gpt-4o`
* **OpenAI Direct:** `openai/gpt-4o`
* **Anthropic:** `anthropic/claude-3-5-sonnet-20241022`
* **Google Gemini:** `google/gemini-1.5-pro`

### 2. Configure Environment Secrets
Set the required API keys in your terminal environment depending on the provider you configured:

* **For Azure OpenAI:**
  ```bash
  export AZURE_OPENAI_API_KEY="your-azure-api-key"
  # Optional overrides (defaults are configured in runtime):
  export AZURE_OPENAI_ENDPOINT="https://your-endpoint.cognitiveservices.azure.com"
  export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
  export AZURE_OPENAI_API_VERSION="2024-08-01-preview"
  ```
* **For OpenAI:**
  ```bash
  export OPENAI_API_KEY="your-openai-api-key"
  ```
* **For Anthropic Claude:**
  ```bash
  export ANTHROPIC_API_KEY="your-anthropic-api-key"
  ```

---

## Defining Agents and Tasks

Configurations are declared in `agents.yaml` and `tasks.yaml`.

### 1. Defining Agents (`agents.yaml`)
Create or edit `agents.yaml` in your workspace. Here is a template:

```yaml
# agents.yaml
stock_analyst:
  role: Stock Research Analyst
  goal: Fetch the current stock price and key metrics for target companies.
  backstory: >
    You are an expert financial analyst. You specialize in tracking equity prices,
    company earnings, and market news to compile reports.
  llm: azure/gpt-4o  # Optional: defaults to config.yaml's default_llm
  tools:
    - web_search.get_stock
    - web_search.search
```

### 2. Defining Tasks (`tasks.yaml`)
Create or edit `tasks.yaml`. Tasks can depend on other tasks:

```yaml
# tasks.yaml
fetch_stock_prices:
  agent: stock_analyst
  description: "Fetch the current stock price and key metrics for Apple (AAPL)."
  expected_output: "A clean price summary table for AAPL."
  depends_on: []

write_research_report:
  agent: stock_analyst
  description: "Write a short summary report based on the fetched stock prices."
  expected_output: "A markdown formatted stock research report."
  depends_on: [fetch_stock_prices]
```

---

## Writing and Configuring Custom Tools

Custom tools are structured as **Connectors**. Public methods in a connector class are automatically reflected and exposed as CrewAI tools.

### Step 1: Create the Connector
Create a new file in `connectors/` (e.g., `connectors/database.py`):

```python
# connectors/database.py
from typing import Any
from connectors.base import BaseConnector

class DatabaseConnector(BaseConnector):
    """
    Custom connector to interface with the enterprise database.
    """
    def query_user_records(self, user_id: str) -> str:
        """
        Queries the database for records associated with a specific user ID.
        
        Args:
            user_id (str): The unique ID of the user.
        """
        # Your custom tool logic goes here
        # E.g., db queries, API calls, etc.
        return f"Database record for user {user_id}: Active, Tier: Enterprise"
```

### Step 2: Register the Connector
Register your new connector in the `CONNECTOR_MAP` inside [runtime/orchestrator.py](file:///Users/anishtejwani/Desktop/projects/enterprise-agent/runtime/orchestrator.py):

```python
# runtime/orchestrator.py
from connectors.database import DatabaseConnector  # Import your connector

CONNECTOR_MAP: Dict[str, Any] = {
    # ... existing connectors
    "database": DatabaseConnector,  # Register with a unique key
}
```

### Step 3: Configure Role-Based Access Control (RBAC)
You must authorize agents to use your new tool by adding it to `rbac.yaml`:

```yaml
# rbac.yaml
roles:
  stock_research_analyst:
    allowed_tools:
      - database.query_user_records  # Explicit permission
      # Or authorize all methods of the connector:
      # - database.*
```

### Step 4: Add the Tool to your Agent
Add the tool in `agents.yaml` using the `<connector_name>.<method_name>` syntax:

```yaml
# agents.yaml
stock_analyst:
  ...
  tools:
    - database.query_user_records
```

---

## Running the Orchestrator

To start the agent execution, simply run:
```bash
crewctl run
```
All agent outputs, thoughts, tool calls, and execution steps will be streamed directly to your terminal.
