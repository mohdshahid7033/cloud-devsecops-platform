# Cloud-Based DevSecOps Platform

[![CI](https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/mohdshahid7033/cloud-devsecops-platform/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-v1.0.1--final-blue)
![Python](https://img.shields.io/badge/python-3.12%20%28CI%29%20%7C%203.14%20%28Docker%29-blue)
![Flask](https://img.shields.io/badge/Flask-3.1.3-green)
![AWS](https://img.shields.io/badge/AWS-ap--south--1-orange)

> A production-deployed, cloud-native DevSecOps platform demonstrating end-to-end automated CI/CD pipelines with integrated security scanning, containerised deployment, and real-time observability — built as a Final Year BCA Project.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [CI/CD Pipeline](#3-cicd-pipeline)
4. [Technology Stack](#4-technology-stack)
5. [Repository Structure](#5-repository-structure)
6. [Local Development Setup](#6-local-development-setup)
7. [Testing](#7-testing)
8. [Security](#8-security)
9. [Infrastructure (Terraform)](#9-infrastructure-terraform)
10. [Monitoring](#10-monitoring)
11. [Production Deployment](#11-production-deployment)
12. [Project Outcomes & Key Learnings](#12-project-outcomes--key-learnings)

---

## 1. Project Overview

The **Cloud-Based DevSecOps Platform** is a full-stack web application and management console that demonstrates a complete, production-grade DevSecOps workflow. It integrates development, security, and operations tooling into a single, automated pipeline — from code commit to production deployment.

The platform serves a dual purpose:
- **A live Flask web application** acting as a consulting portal (ABC Free Consultants), complete with a MySQL-backed contact system, a Prometheus metrics endpoint, and a full REST API.
- **A DevSecOps management console** that provides a real-time dashboard showing the state of the CI/CD pipeline, security scans, infrastructure, and monitoring stack — sourced from live GitHub Actions and AWS APIs.

**Key DevSecOps Principles Demonstrated:**
- Security as a blocking gate, not an afterthought
- Infrastructure-as-Code (Terraform) for reproducible cloud environments
- Automated vulnerability scanning at both filesystem and container image layers
- Zero-SSH production deployment via AWS Systems Manager
- Containerised services with Docker Compose for local parity
- Real-time observability with Prometheus metrics and Grafana dashboards

### Project Context
This project was developed as a **Final Year BCA project**. The production environment is deployed on AWS (ap-south-1 / Mumbai region).

---

## 2. Architecture

The following diagram shows the complete system architecture across three layers: the CI/CD pipeline, the AWS production infrastructure, and the local development stack. The canonical, editable Mermaid source is maintained in [`docs/architecture.mmd`](docs/architecture.mmd).

```mermaid
flowchart LR

    %% Actors
    DEV["Developer Workstation"]
    USER["End User / Browser"]

    %% AREA 1: Local Development
    subgraph LOCAL["Area 1: Local Development Stack (Docker Compose)"]
        direction TB

        subgraph DC["Docker Compose Environment (devsecops-network)"]
            direction TB
            L_NGINX["Nginx:alpine<br/>Reverse Proxy :80"]
            L_APP["Flask Application<br/>Python 3.14-alpine :5000"]
            L_MYSQL["MySQL 8.0<br/>devsecops_db :3306"]
            L_PROM["Prometheus<br/>Metrics Scraper :9090"]
            L_GRAFANA["Grafana<br/>Dashboards :3000"]

            L_NGINX -->|proxy_pass :5000| L_APP
            L_APP -->|TCP :3306| L_MYSQL
            L_PROM -->|Scrapes /metrics| L_APP
            L_GRAFANA -->|Queries metrics :9090| L_PROM
        end
    end

    %% Developer Actions
    DEV -->|docker compose up<br/>Local testing & parity| DC
    DEV -->|git push / Pull Request| GH["GitHub Repository<br/>main branch"]

    %% AREA 2: CI/CD Pipeline
    subgraph CICD["Area 2: CI/CD & Security Pipeline (GitHub Actions)"]
        direction TB

        GH --> S1["1. Checkout Source<br/>actions/checkout@v4"]
        S1 --> S2["2. Check Python<br/>actions/setup-python@v5 (3.12)"]
        S2 --> S3["3. Install Dependencies<br/>pip install requirements, pytest, awscli"]
        S3 --> S4["4. Run Tests (Pytest)<br/>84 Unit, Platform & Deployment Tests (Blocking)"]

        subgraph QUALITY_SEC["Code Quality & Vulnerability Scanning"]
            direction TB
            S4 --> S5["5. SonarQube SAST Analysis<br/>sonarqube:community :9000 & Scanner 7.0.2"]
            S5 --> S6["6. Trivy Filesystem Scan<br/>HIGH / CRITICAL Gate (Blocking)"]
            S6 --> S7["7. Build Docker Image<br/>Single-stage python:3.14-alpine"]
            S7 --> S8["8. Scan Docker Image (Trivy)<br/>devsecops-platform:latest (Blocking)"]
        end

        S8 --> S9["9. Configure AWS Credentials<br/>aws-actions/configure-aws-credentials@v4 (OIDC)"]
        S9 --> S10["10. Login to Amazon ECR<br/>aws-actions/amazon-ecr-login@v2"]
        S10 --> S11["11. Push Image to ECR<br/>devsecops-platform:latest & :SHA"]
        S11 --> S12["12. Blue/Green Deploy via SSM<br/>Zero-Downtime Traffic Switch (Zero-SSH)"]
        S13["13. Application Health Check<br/>curl /health (Independent Verification)"]
        S12 --> S13
    end

    %% AREA 3: AWS Production
    subgraph AWS["Area 3: AWS Production Environment (ap-south-1)"]
        direction TB

        ECR["Amazon ECR Registry<br/>devsecops-platform:latest"]
        SSM_STORE["AWS SSM Parameter Store<br/>/devsecops/db_* Runtime Secrets"]

        subgraph VPC["AWS VPC (10.0.0.0/16) - Subnet (10.0.1.0/24)"]
            direction TB

            subgraph EC2["EC2 Instance (t3.micro - Amazon Linux 2023)"]
                direction TB

                SSM_AGENT["SSM Agent<br/>Executes Deployment Script"]

                subgraph CONTAINERS["Docker Containers (devsecops-network)"]
                    direction TB

                    P_NGINX["Nginx:alpine<br/>Upstream Reverse Proxy :80"]
                    P_BLUE["Flask Blue Slot<br/>devsecops-app-blue :5001"]
                    P_GREEN["Flask Green Slot<br/>devsecops-app-green :5002"]
                    P_MYSQL["MySQL 8.0 Container<br/>devsecops_db :3306 (Persistent Volume)"]
                    P_PROM["Prometheus Container<br/>Metrics Scraper :9090"]
                    P_GRAFANA["Grafana Container<br/>Dashboards :3000"]

                    P_NGINX -->|upstream app_backend| P_BLUE
                    P_NGINX -.->|zero-downtime cutover| P_GREEN
                    P_BLUE -->|TCP :3306| P_MYSQL
                    P_GREEN -->|TCP :3306| P_MYSQL
                    P_PROM -->|Scrapes /metrics| P_NGINX
                    P_GRAFANA -->|Queries metrics :9090| P_PROM
                end

                SSM_AGENT -->|1. docker pull| ECR
                SSM_AGENT -->|2. aws ssm get-parameter| SSM_STORE
                SSM_AGENT -->|3. Blue/Green switch & reload| CONTAINERS
            end
        end
    end

    %% Inter-Area Connections
    S11 -->|Push latest image| ECR
    S12 -->|Trigger zero-SSH script| SSM_AGENT
    S13 -->|HTTP GET /health - validates healthy status and live_mysql| P_NGINX

    %% End User Access
    USER -->|HTTP Request :80| P_NGINX
```

### Component Summary

| Component | Role | Technology | Port |
|---|---|---|---|
| Flask App | Core API & DevSecOps console | Python 3.14 / Flask 3.1.3 | 5000 |
| MySQL | Data persistence | MySQL 8.0 | 3306 |
| Nginx | Reverse proxy / ingress | nginx:alpine | 80 |
| Prometheus | Metrics collection | prom/prometheus | 9090 |
| Grafana | Observability dashboard | grafana/grafana | 3000 |
| SonarQube | SAST scanning (CI only) | sonarqube:community | 9000 |

---

## 3. CI/CD Pipeline

The pipeline is defined in [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Continuous integration (testing and security scanning) triggers automatically on every push and pull request targeting the `main` branch. Production publication and blue/green deployment are strictly guarded behind an explicit manual `workflow_dispatch` trigger requiring `deploy_to_production: true` on `main`. All security gates are **blocking** — a scan failure causes `exit 1` and halts the pipeline immediately.

```mermaid
flowchart TD
    subgraph CI["1. Continuous Integration (test-and-scan) — Runs on PRs & Main Pushes"]
        A([Pull Request or Push to main]) --> B[Checkout code]
        B --> C[Setup Python 3.12]
        C --> D[Install dependencies]
        D --> E{Run Pytest\nUnit & Integration}
        E -->|PASS| F[SonarQube SAST\nAnalysis :9000]
        E -->|FAIL| Z([Pipeline FAILED])
        F -->|PASS| G[Trivy Filesystem Scan\nHIGH/CRITICAL Gate]
        F -->|FAIL| Z
        G -->|PASS| H[Build Docker Image\nSingle-stage Alpine]
        G -->|FAIL| Z
        H --> I[Trivy Image Scan\nHIGH/CRITICAL Gate]
        I -->|FAIL| Z
        I -->|PASS| J([CI Validation PASSED])
    end

    subgraph CD["2-4. Continuous Deployment — Manual workflow_dispatch on main only"]
        K([Manual Dispatch\ndeploy_to_production: true]) --> L[Configure AWS Credentials\nGitHub OIDC Federation]
        L --> M[Build, Tag & Push to ECR\n:SHA & :latest]
        M --> N[AWS SSM Blue/Green Deploy\nZero-Downtime Traffic Switch]
        N --> O[Verify Production Health\nIndependent HTTP Check]
        O --> P([Production Release SUCCESS])
    end

    J -.->|Requires Manual Authorization| K
```

### Modular Pipeline Jobs

| Job | Trigger & Conditions | Key Operations & Security Gates |
|---|---|---|
| **1. `test-and-scan`** | Pull requests & pushes to `main` | Runs 42 app tests, SonarQube SAST, Trivy filesystem & container CVE scans. Blocking gate. |
| **2. `publish-ecr`** | Manual `workflow_dispatch` on `main` only (`deploy_to_production: true`) | Assumes AWS OIDC role (`secrets.AWS_ROLE_ARN`). Builds and pushes immutable image tag `${{ github.sha }}` and `latest` to Amazon ECR. |
| **3. `deploy-blue-green`** | Manual `workflow_dispatch` on `main` only (`deploy_to_production: true`) | Discovers target EC2 instance, checks single-instance guard (`NUM_INSTANCES == 1`), packages and executes `scripts/deploy_blue_green.sh` via SSM. Pre-warms candidate, validates Nginx config sandbox, switches upstream, and auto-rolls back on failure. |
| **4. `verify-production`** | Manual `workflow_dispatch` on `main` only (`deploy_to_production: true`) | Resolves public IP of production EC2 and polls `/health` (asserts `status: healthy`, `connected: true`, `mode: live_mysql`). |

> **Note on Python versions:** The CI runner uses **Python 3.12** (set by `setup-python`) to run tests and SonarQube analysis. The built Docker image uses **`python:3.14-alpine`** as its base, matching local development and production runtime.

---

## 4. Technology Stack

### Application

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.12 (CI) / 3.14 (Docker) | Runtime |
| Flask | 3.1.3 | Web framework & REST API |
| PyMySQL | 1.1.1 | MySQL database driver |
| prometheus-flask-exporter | 0.23.2 | Metrics endpoint `/metrics` |
| cryptography | ≥ 42.0.0 | Secure dependency |

### Infrastructure

| Technology | Version | Purpose |
|---|---|---|
| Terraform | ≥ 1.6.0 | Infrastructure as Code |
| AWS Provider | ~> 6.0 | AWS resource management |
| Docker | Latest | Containerisation |
| Docker Compose | v2 | Local orchestration |
| Nginx | alpine | Reverse proxy |
| MySQL | 8.0 | Database |

### Security Tooling

| Tool | Integration | Purpose |
|---|---|---|
| Aqua Trivy | GitHub Actions (CI) | Filesystem & Docker image CVE scanning |
| SonarQube Community | GitHub Actions (CI) | Static application security testing (SAST) |
| AWS SSM Parameter Store | Production runtime | Secrets management (DB credentials) |
| `.trivyignore` | Trivy configuration | Documented CVE exception policy |

### Monitoring

| Tool | Purpose |
|---|---|
| Prometheus | Scrapes Flask `/metrics` for HTTP request telemetry |
| Grafana | Visualises Prometheus data via auto-provisioned dashboard |
| `/health` endpoint | Structured JSON health check used by CI pipeline as a deployment gate |

---

## 5. Repository Structure

```
cloud-devsecops-platform/
│
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI/CD pipeline (13 steps)
│
├── app/
│   ├── app.py                  # Flask application entry point
│   ├── database.py             # MySQL connection, ORM helpers, health queries
│   ├── platform_routes.py      # REST API routes for the DevSecOps console
│   ├── platform_service.py     # Service layer: GitHub API, Trivy, SonarQube, AWS telemetry
│   ├── requirements.txt        # Python dependencies
│   ├── static/                 # CSS, JS, images
│   └── templates/
│       ├── index.html          # DevSecOps management console UI
│       └── client_app.html     # ABC Free Consultants demo application UI
│
├── docker/
│   └── Dockerfile              # Multi-stage Alpine build (python:3.14-alpine)
│
├── monitoring/
│   ├── prometheus/
│   │   └── prometheus.yml      # Prometheus scrape config (Flask target)
│   └── grafana/
│       ├── provisioning/       # Auto-provisioned datasource & dashboard configs
│       └── dashboards/         # Grafana dashboard JSON
│
├── nginx/
│   └── nginx.conf              # Reverse proxy config (port 80 → Flask 5000)
│
├── terraform/
│   ├── main.tf                 # AWS VPC, Subnet, IGW, Security Group, EC2
│   ├── variables.tf            # Input variables (region, AMI, instance type)
│   └── outputs.tf              # Output values (instance IP, etc.)
│
├── tests/
│   ├── test_app.py             # 9 tests — Flask routes, API, health endpoint
│   └── test_platform.py        # 25 tests — DevSecOps console API, security, monitoring
│
├── docker-compose.yml          # Local dev stack (5 services)
├── sonar-project.properties    # SonarQube project configuration
├── pytest.ini                  # Pytest configuration (testpaths = tests/)
└── .trivyignore                # Documented CVE exception list
```

---

## 6. Local Development Setup

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with Docker Compose v2)
- Python 3.12+ (for running tests locally)
- Git

### 1. Clone the repository

```bash
git clone https://github.com/mohdshahid7033/cloud-devsecops-platform.git
cd cloud-devsecops-platform
```

### 2. Configure environment variables

The Docker Compose stack uses environment variables for database credentials. Create a `.env` file in the project root:

```bash
# .env (do NOT commit this file)
DB_PASSWORD=your_local_db_password
MYSQL_ROOT_PASSWORD=your_local_root_password
```

> **Note:** The `docker-compose.yml` file uses `${DB_PASSWORD:-local_db_pass_example}` with safe fallback defaults. If no `.env` file is provided, the fallback values are used for local development only. **Never use default credentials in any non-local environment.**

### 3. Start the full stack

```bash
docker compose up --build
```

This starts five services: `mysql`, `app`, `prometheus`, `grafana`, and `nginx`.

### 4. Verify the stack

| Service | URL |
|---|---|
| Application (via Nginx) | http://localhost |
| Flask app (direct) | http://localhost:5000 |
| Health endpoint | http://localhost/health |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

A healthy response from `/health` looks like:

```json
{
  "status": "healthy",
  "service": "devsecops-platform",
  "database": {
    "connected": true,
    "mode": "live_mysql"
  }
}
```

### 5. Install Python dependencies (for local testing)

```bash
python -m pip install -r app/requirements.txt
python -m pip install pytest
```

---

## 7. Testing

The test suite uses **[Pytest](https://docs.pytest.org/)** and is split across two files.

### Running Tests

```bash
# Run all 84 tests
python -m pytest

# Run with verbose output
python -m pytest -v

# Run individual test suites
python -m pytest tests/test_app.py
python -m pytest tests/test_platform.py
python -m pytest tests/test_deploy_blue_green.py
```

### Test Configuration

Pytest is configured in [`pytest.ini`](pytest.ini):

```ini
[pytest]
pythonpath = .
testpaths = tests
```

### Test Summary

| File | Tests | Coverage |
|---|---|---|
| `tests/test_app.py` | 9 | Core Flask routes (`/`, `/health`, `/metrics`, `/api/status`, `/api/contact` validation & storage) |
| `tests/test_platform.py` | 33 | DevSecOps console API (pipeline status, security scans, monitoring, infrastructure, diagnostics, rollback, telemetry) |
| `tests/test_deploy_blue_green.py` | 42 | Automated Blue/Green deployment engine tests (route detection, slot switching, unhealthy candidate rejection, lock handling, Nginx pre-flight validation, container preservation, rollback) |
| **Total** | **84** | **100% Automated Test Suite Passing (84/84 Passed)** |

**Locally verified result:** All 84 tests passing (Python 3.12 / 3.14, pytest)

**In CI:** Core test suite executed on GitHub Actions runner with zero test failures.

> `test_platform.py` uses a `pytest.fixture(autouse=True)` to mock external API calls during test runs, ensuring tests are deterministic and do not depend on live external services. `test_deploy_blue_green.py` validates the deployment script logic and edge cases using mock isolated environments.

### Notable Test Cases

| Test | What It Verifies |
|---|---|
| `test_health` | `/health` returns `status: healthy` and `service: devsecops-platform` |
| `test_metrics` | `/metrics` exposes `flask_http_request_total` Prometheus counter |
| `test_platform_pipeline_honest_trigger` | Pipeline trigger without a GitHub token returns an honest `400` error |
| `test_platform_security_policy_wording` | `.trivyignore` CVEs are reported with accurate policy and rationale |
| `test_platform_infrastructure_environment_separation` | API cleanly separates AWS Production from local Docker state |
| `test_platform_diagnostics_context_awareness` | Each diagnostic engine includes `environment` and `check_source` — no fabricated states |
| `test_active_blue_switches_to_green` | Verified Blue active route switches to Green candidate upon successful health verification |
| `test_unhealthy_candidate_is_rejected` | Candidate failing health check is destroyed; live traffic never switches |
| `test_rollback_restores_exact_original_upstream` | Verification failure triggers immediate automatic restoration of original upstream |
| `test_production_containers_never_stopped_or_removed` | Active serving container is protected from cleanup or premature termination |

---

## 8. Security

### Security Gate Policy

All security checks in the CI pipeline are **blocking gates** with `--exit-code 1`. A scan failure aborts the pipeline immediately — there is no `|| true` or other suppression applied to security steps.

### Trivy Vulnerability Scanning

Trivy performs two independent scans on every CI run:

1. **Filesystem scan** — scans `app/requirements.txt` and project files for known CVEs in Python dependencies.
2. **Docker image scan** — scans the built `devsecops-platform:latest` container image for OS-level and package CVEs.

Both scans target `--severity HIGH,CRITICAL` with `--exit-code 1`.

#### `.trivyignore` — CVE Exception Policy

Two CVEs are explicitly ignored via [`.trivyignore`](.trivyignore):

| CVE ID | Reason for Acceptance |
|---|---|
| `GHSA-6v7p-g79w-8964` | Accepted by project policy after review. Not directly exploitable in the project's usage context. |
| `CVE-2025-47273` | Accepted by project policy after review. No fix available at the time of release; flagged for future re-evaluation. |

> These exceptions are declared explicitly and transparently in `.trivyignore`. They are not silently suppressed.

### SonarQube SAST Analysis

SonarQube Community Edition runs as a Docker **service container** inside the GitHub Actions runner. The CI step:

1. Waits for the SonarQube server to be healthy before proceeding.
2. **Rotates the default admin password** to an ephemeral, randomly generated password (`EphemeralAdminPass_${RANDOM}_$(openssl rand -hex 8)`) using `::add-mask::` to prevent log exposure.
3. Generates a short-lived analysis token (`::add-mask::` applied).
4. Runs `sonar-scanner` version 7.0.2 against the `app/` source directory.

This ensures no default or reused credentials exist within any CI run.

### AWS SSM Zero-SSH Deployment

Production deployments use **AWS Systems Manager (SSM) Run Command** with the `AWS-RunShellScript` document. This means:

- **No SSH keys are required** on the EC2 instance and no SSH port (22) is opened in the Security Group.
- The deployment script is sent as an encrypted payload through the SSM agent, which runs natively on the EC2 instance.
- The EC2 Security Group only permits **port 80 (HTTP) inbound** and all outbound.
- The CI workflow polls `get-command-invocation` until the SSM command reaches a terminal state (`Success`, `Failed`, `TimedOut`). A non-`Success` status causes the pipeline to fail.

### Secrets Management

All production database credentials are stored in **AWS SSM Parameter Store**, not in the repository or environment files:

| Parameter | Type |
|---|---|
| `/devsecops/db_name` | String |
| `/devsecops/db_user` | String |
| `/devsecops/db_password` | SecureString (encrypted) |
| `/devsecops/db_root_password` | SecureString (encrypted) |

The deployment script retrieves these at runtime using `aws ssm get-parameter --with-decryption` directly on the EC2 instance, so credentials are never logged or transmitted through the CI runner environment.

---

## 9. Infrastructure (Terraform)

AWS infrastructure is provisioned declaratively using **Terraform** (≥ 1.6.0) with the AWS provider (~> 6.0). The configuration is located in [`terraform/`](terraform/).

### Resources Provisioned

| Resource | Name | Details |
|---|---|---|
| VPC | `devsecops-vpc` | CIDR: `10.0.0.0/16`, DNS support enabled |
| Subnet | `devsecops-subnet` | CIDR: `10.0.1.0/24`, public IP on launch |
| Internet Gateway | `devsecops-igw` | Attached to VPC |
| Route Table | `devsecops-route-table` | Default route `0.0.0.0/0` → IGW |
| Security Group | `devsecops-security-group` | Inbound: TCP 80 only; Outbound: all |
| EC2 Instance | `devsecops-ec2` | t3.micro, Amazon Linux, ap-south-1 |

### Key Design Decisions

- **Port 80 only inbound:** No SSH (22) is exposed. All management is performed via SSM.
- **Public subnet with controlled SG:** The EC2 instance receives a public IP but ingress is restricted to HTTP only.

### Infrastructure Safety & Known Drift Warning

> [!CAUTION]
> **STRICT READ-ONLY POLICY:** Do **NOT** run `terraform apply` or `terraform destroy` against the live infrastructure.
> - **Known Drift:** The active EC2 production instance (`i-0fb9dcbeb35b4fdbe`) has an unencrypted root EBS volume (`encrypted: false` in state), whereas `terraform/main.tf` specifies `encrypted = true`.
> - **Replacement Risk:** AWS EBS does not support in-place encryption changes on an active root block device. Running `terraform apply` would **force instance replacement** (`forces replacement`), destroying the production EC2 host, reallocating a new public IP, and causing service downtime.
> - **Safe Migration Protocol:** When encryption is required, take a snapshot of the root EBS volume, create an encrypted copy with a KMS key, generate an AMI, and perform a scheduled cutover.

### Read-Only Inspection

```bash
cd terraform
terraform init
terraform plan  # View plan only; do NOT apply
```

---

## 10. Monitoring

The monitoring stack is composed of Prometheus and Grafana, automatically provisioned on both the local Docker Compose stack and the production EC2 instance.

### Prometheus

- **Configuration:** [`monitoring/prometheus/prometheus.yml`](monitoring/prometheus/prometheus.yml)
- Scrapes the Flask application's `/metrics` endpoint every 15 seconds.
- Collects `flask_http_request_total` labelled by HTTP status code, enabling request rate and status distribution analysis.

### Grafana

- **Datasource provisioning:** auto-configured to connect to Prometheus via the `devsecops-network` Docker network.
- **Dashboard provisioning:** the DevSecOps Application Monitoring dashboard is automatically provisioned on startup from [`monitoring/grafana/dashboards/`](monitoring/grafana/dashboards/).
- The dashboard is also embedded into the production deployment via the CI pipeline (the Grafana dashboard JSON is base64-encoded and injected into the SSM deployment script via `sed` to avoid shell escaping issues).

### Application Health Endpoint

`GET /health` returns a structured JSON payload used as a deployment gate by the CI pipeline:

```json
{
  "status": "healthy",
  "service": "devsecops-platform",
  "version": "1.0.1",
  "database": {
    "connected": true,
    "mode": "live_mysql",
    "latency_ms": 1.23
  }
}
```

The CI pipeline asserts that the response contains `status: healthy`, `connected: true`, and `mode: live_mysql` before declaring the deployment successful.

---

## 11. Production Deployment

### Deployment Mechanism

Production deployments are strictly guarded: an ordinary merge or push to `main` runs tests and scans only. Deploying to AWS requires an explicitly authorized manual dispatch (`workflow_dispatch`) on `main` with `deploy_to_production: true`.

The deployment executes an automated zero-downtime Blue/Green cutover via AWS Systems Manager (SSM) on the EC2 host:

1. **ECR Authentication** — Authenticate Docker to Amazon ECR via `aws ecr get-login-password`.
2. **Pull Candidate Image** — Pull the verified immutable container image tag (`${{ github.sha }}`).
3. **Atomic Deployment Lock** — Acquire exclusive deployment lock (`/tmp/deploy_blue_green.lock`) via `flock` (with directory lock fallback). Stale locks (>600s or dead PID) are reclaimed.
4. **Pre-warm Candidate Container** — Spin up the idle slot (`devsecops-app-green` or `devsecops-app-blue`) on an isolated host port (5001 or 5000).
5. **Candidate Health Probing** — Probe `http://localhost:<candidate_port>/health` for up to 30s. If candidate fails, candidate container is immediately destroyed; live traffic is never switched.
6. **Sandbox Nginx Configuration Testing** — In an isolated `nginx:alpine` container, validate the complete candidate Nginx configuration with `nginx -t` before touching the host configuration.
7. **Zero-Downtime Upstream Cutover** — Atomically swap `upstream.conf` and issue `nginx -s reload` to switch ingress traffic with zero dropped requests.
8. **Post-Switch Verification & Automated Rollback** — Verify public health through Nginx on port 80. If health check fails, **immediately revert** Nginx upstream to the previous slot and reload.
9. **Drain & Cleanup** — Once the candidate is verified healthy, stop the previous container.
10. **External Independent Verification** — GitHub Actions independently polls `http://<ec2_public_ip>/health` to confirm healthy application status and live database connection.

### Container Image

The production Docker image is built from [`docker/Dockerfile`](docker/Dockerfile):

- **Base:** `python:3.14-alpine`
- **Hardening:** `pip`, `setuptools`, and `wheel` are removed after installation to reduce attack surface.
- **Security packages:** `msgpack ≥ 1.2.1` and `setuptools ≥ 78.1.1` are pinned to patched versions.
- **Port:** 5000 (exposed; proxied via Nginx on port 80).

### Production Release

| Item | Value |
|---|---|
| Git Tag | `v1.0.1-final` |
| Commit | `fb305208d3be4ebe331890fb8daadd556e75171a` |
| AWS Region | `ap-south-1` (Mumbai) |
| ECR Repository | `devsecops-platform` |
| Deployment method | AWS SSM `AWS-RunShellScript` |

---

## 12. Project Outcomes & Key Learnings

This project demonstrates the following DevSecOps concepts through practical, production-deployed implementation:

### What Was Built and Deployed

| Outcome | Detail |
|---|---|
| **Automated CI/CD pipeline** | 13-step GitHub Actions workflow from code to production |
| **Security-as-code** | Trivy and SonarQube integrated as non-optional, blocking pipeline gates |
| **Infrastructure-as-Code** | Complete AWS environment defined and reproducible via Terraform |
| **Zero-SSH cloud deployment** | AWS SSM eliminates the need for SSH keys or exposed ports |
| **Secrets management** | All production credentials stored and retrieved from AWS SSM Parameter Store |
| **Containerised application** | Docker multi-stage Alpine build; five-service Compose stack |
| **Real-time observability** | Live Prometheus scraping + auto-provisioned Grafana dashboard |
| **Honest telemetry** | Platform dashboard reflects real GitHub Actions and AWS API state |

### Key Learnings

- **DevSecOps is a cultural and architectural decision:** Integrating Trivy and SonarQube as pipeline gates early forces security considerations into every code change.
- **Infrastructure parity matters:** Using Docker Compose locally with the same service definitions as production significantly reduces "works on my machine" failures.
- **Secrets management complexity in CI/CD:** Passing secrets to SSM commands without logging them required careful use of `sed` for script injection, runtime Parameter Store retrieval, and `::add-mask::` in Actions.
- **Disk space and idempotency in production:** Long-running SSM deployments require idempotent container management (`docker stop || true`, `docker rm || true`) and monitoring of EC2 disk usage.
- **Honest observability:** A monitoring dashboard that fabricates data is worse than no dashboard. The platform service layer is designed to honestly report `UNAVAILABLE` states rather than show false-positive health.

---

*This project was developed as a Final Year BCA project. The production environment is deployed on AWS and may not remain active after the project submission period.*
