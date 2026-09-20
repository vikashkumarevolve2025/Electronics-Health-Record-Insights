# EHR Insights

Zero-Trust Clinical RAG is an electronic health record (EHR) question-answering application. It retrieves relevant patient encounter data from PostgreSQL, redacts personally identifiable information (PII), and uses Amazon Bedrock Claude to answer historical-record questions while refusing diagnosis, prescribing, and medication-change requests.

> **Important:** This project is an engineering prototype and must not be used as a clinical decision-making system. Do not load real patient data until the required privacy, security, clinical safety, and regulatory reviews are complete.

## Problem Statement

EHR data is difficult to query safely because it is large, semi-structured, sensitive, and distributed across clinical records. A user may need to ask a focused question such as:

> What medications were prescribed to this patient upon discharge?

Traditional keyword search can miss relevant records, while sending raw EHR text directly to a large language model can expose PII and produce unsafe medical recommendations.

This project addresses those risks by combining:

- Patient-scoped retrieval from a PostgreSQL database.
- Semantic search using vector embeddings and `pgvector`.
- PII redaction before model invocation.
- Bedrock Claude generation grounded in retrieved context.
- Deterministic refusal rules for medical advice requests.
- A disclaimer that responses are summaries, not diagnoses.

## Solution Approach

```text
User question
		|
		v
Streamlit UI
		|
		v
FastAPI API
		|
		+--> Generate question embedding
		|
		+--> Search patient-scoped records in PostgreSQL + pgvector
		|
		+--> Redact PII with Microsoft Presidio
		|
		+--> Apply local medical-safety refusal rules
		|
		+--> Send approved, redacted context to Amazon Bedrock Claude
		|
		v
Grounded response with safety disclaimer
```

The current implementation uses a direct `boto3` Bedrock Runtime call. NeMo Guardrails is retained as a project dependency, but its Bedrock provider is not used because the installed provider registry does not support the required `bedrock` engine path.

## Main Features

- Semantic clinical-record retrieval using `SentenceTransformers`.
- PostgreSQL storage with the `pgvector` extension.
- Patient filtering before vector similarity search.
- PII redaction for names, phone numbers, email addresses, SSNs, locations, organizations, and dates.
- Custom Presidio recognizers for SSNs and selected hospital names.
- Amazon Bedrock Claude Sonnet integration through `Converse`.
- Local refusal for diagnosis, prescriptions, dosage changes, and treatment recommendations.
- FastAPI endpoints for chat, patient lookup, and a sample clinical query.
- Streamlit chat interface.
- Local development support with a Python virtual environment.

## Technology Stack

### Application

- Python 3.12
- FastAPI
- Uvicorn
- Streamlit
- SQLAlchemy
- Psycopg 3

### Data and retrieval

- PostgreSQL
- `pgvector`
- Pandas
- SentenceTransformers
- `NeuML/bioclinical-modernbert-base-embeddings`
- 768-dimensional clinical embeddings

### AI and safety

- Amazon Bedrock Runtime
- Claude Sonnet
- `boto3`
- Microsoft Presidio Analyzer
- Microsoft Presidio Anonymizer
- spaCy

### Planned AWS production services

- Amazon RDS for PostgreSQL or Aurora PostgreSQL
- Amazon S3
- Amazon ECS on Fargate or AWS App Runner
- Amazon Bedrock Guardrails
- AWS Secrets Manager
- AWS KMS
- Amazon Cognito or enterprise identity provider
- Amazon CloudWatch
- Optional Amazon Comprehend Medical for PHI detection

## Repository Structure

```text
.
|-- data/
|   `-- MIMIC_IV_Trasncript.csv       # Development input data
|-- scripts/
|   |-- 01_ingest_baseline_data.py   # Load CSV data into PostgreSQL
|   |-- 02_verify_ingestion.py       # Verify row counts and data
|   |-- 03_apply_vector_schema.py    # Add the pgvector column
|   |-- 04_generate_embeddings.py    # Generate and store embeddings
|   |-- 05_test_vector_search.py     # Test semantic retrieval
|   `-- 06_test_guardrails.py        # Test Bedrock and safety refusals
|-- src/
|   |-- api/main.py                  # FastAPI application
|   |-- database/schema.sql           # Database schema
|   |-- guardrails/
|   |   |-- bedrock_guardrail.py     # Direct Bedrock adapter and refusal rules
|   |   |-- config.yml                # Legacy guardrail configuration
|   |   `-- rails.co                  # Medical-safety policy examples
|   |-- pii_redaction/
|   |   `-- presidio_service.py      # PII detection and anonymization
|   `-- ui/app.py                    # Streamlit interface
|-- requirements.txt
|-- DATA_INGESTION_RUNBOOK.md
`-- AWS_DEPLOYMENT_RUNBOOK.md
```

## Local Setup

### Prerequisites

- Python 3.12.
- PostgreSQL with the `pgvector` extension.
- AWS CLI configured with access to Amazon Bedrock.
- Access to the selected Claude model in the configured AWS region.

Create or activate the project environment:

```powershell
ehr-env\Scripts\activate
ehr-env\Scripts\python.exe -m pip install -r requirements.txt
```

### Environment variables

Create a local `.env` file. Never commit it:

```text
DB_HOST=<database-host>
DB_PORT=5432
DB_NAME=<database-name>
DB_USER=<database-user>
DB_PASSWORD=<database-password>
AWS_PROFILE=foresight
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-20250514-v1:0
```

For AWS-hosted workloads, use an IAM role and AWS Secrets Manager instead of `AWS_PROFILE` and `.env` credentials.

### Database preparation

Enable the extension and create the schema:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Then run the scripts in order:

```powershell
ehr-env\Scripts\python.exe scripts\01_ingest_baseline_data.py
ehr-env\Scripts\python.exe scripts\02_verify_ingestion.py
ehr-env\Scripts\python.exe scripts\03_apply_vector_schema.py
ehr-env\Scripts\python.exe scripts\04_generate_embeddings.py
ehr-env\Scripts\python.exe scripts\05_test_vector_search.py
```

### Run the API

```powershell
uvicorn src.api.main:app --reload
```

The API is available at `http://127.0.0.1:8000`.

### Run the UI

In a second terminal:

```powershell
streamlit run src/ui/app.py
```

The UI expects the API at `http://localhost:8000` in the current implementation.

## API Endpoints

### `POST /api/v1/chat`

Performs patient-scoped vector retrieval, PII redaction, Bedrock generation, and safety checks.

Example request:

```json
{
	"patient_id": "10001",
	"messages": [
		{
			"role": "user",
			"content": "What medications were prescribed to this patient upon discharge?"
		}
	]
}
```

### `GET /api/v1/patients`

Returns patient IDs that have embedded records.

### `POST /api/v1/clinical-query`

Runs a sample clinical query against mock context. This endpoint is for development testing and is not a production data path.

## Safety and Privacy Design

The application currently provides defense in depth:

1. Patient ID is used to constrain database retrieval.
2. Retrieved context is passed through Presidio before model invocation.
3. Local refusal rules intercept common medical-advice requests.
4. The Bedrock system prompt limits the model to supplied clinical context.
5. The UI adds a non-diagnostic response disclaimer.

These controls are not sufficient for production PHI by themselves. Before production use, add authentication, patient-level authorization, audit logging, managed Bedrock Guardrails, encryption, retention controls, and a formal compliance review.

## AWS Deployment Direction

The recommended production architecture is:

```text
Streamlit on ECS/App Runner
					|
FastAPI on ECS/Fargate behind HTTPS
					|
RDS/Aurora PostgreSQL + pgvector
					|
S3 private data bucket
					|
Bedrock Claude + Bedrock Guardrails
```

Use:

- RDS/Aurora instead of PostgreSQL directly on EC2.
- S3 for raw, curated, and rejected data files.
- Private subnets for API tasks and the database.
- IAM task roles instead of long-lived AWS access keys.
- Secrets Manager for database credentials.
- KMS encryption for RDS, S3, logs, and secrets.
- CloudWatch for logs, metrics, alarms, and operational monitoring.
- Cognito or an enterprise identity provider for authentication.

The complete migration sequence is documented in [AWS_DEPLOYMENT_RUNBOOK.md](AWS_DEPLOYMENT_RUNBOOK.md). The existing database setup and ingestion instructions are in [DATA_INGESTION_RUNBOOK.md](DATA_INGESTION_RUNBOOK.md).

## Current Limitations

- The API does not yet authenticate users or enforce patient-level authorization.
- The current Streamlit UI uses a local API URL.
- The current embedding model loads into the API process and can make startup slow.
- The managed Bedrock Guardrail ID is not configured by default.
- The development database may still be hosted on EC2 rather than private RDS/Aurora.
- Error responses and operational audit logging need production hardening.
- The project has not been certified for clinical use, HIPAA, or any other regulatory requirement.

## Security Notes

- Never commit `.env`, database passwords, AWS access keys, private keys, or connection strings.
- Rotate any credential that has previously been committed or exposed.
- Do not expose PostgreSQL port `5432` publicly in production.
- Do not send unredacted patient data to a model without an approved data-flow review.
- Review AWS service eligibility, contractual requirements, and organizational policy before processing real PHI.

## License and Data

Add the project license before public distribution. Confirm that every dataset used with this repository may legally be redistributed. Do not publish patient-identifiable data or secrets to GitHub.