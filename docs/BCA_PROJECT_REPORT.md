# CLOUD-BASED DEVSECOPS PLATFORM FOR AUTOMATED APPLICATION DEPLOYMENT AND MONITORING
## Final Year Project Report — Bachelor of Computer Applications (BCA)

---

### Candidate & Project Metadata
- **Project Title:** Cloud-Based DevSecOps Platform for Automated Application Deployment and Monitoring
- **Candidate Name:** Mohd Shahid
- **Roll / Registration Number:** [University Roll Number]
- **Degree / Programme:** Bachelor of Computer Applications (BCA)
- **Academic Year:** 2025–2026
- **Institution / College:** [College / University Name]
- **Project Guide / Supervisor:** [Supervisor / Professor Name]
- **Domain:** Cloud Computing, DevOps Engineering, Application Security (DevSecOps)
- **Target Cloud Provider:** Amazon Web Services (AWS)
- **Target Region:** `ap-south-1` (Mumbai, India)
- **Primary Programming Language:** Python 3.12 (CI Runner) / 3.14 (Alpine Docker Container)
- **Frameworks & Core Tools:** Flask 3.1.3, PyMySQL 1.1.1, Prometheus Flask Exporter, Docker & Docker Compose, Terraform (≥ 1.6.0), GitHub Actions (OIDC), Aqua Security Trivy, SonarQube Community Edition, Prometheus, Grafana, Nginx.
- **Repository URL:** `https://github.com/mohdshahid7033/cloud-devsecops-platform`
- **Main Branch:** `main`

---

## 1. ABSTRACT

Modern enterprise software engineering requires high-velocity software delivery without compromising code quality, operational reliability, or security posture. Conventional software development often segregates software programming, quality assurance, information security audits, and cloud operations. This isolation frequently results in delayed releases, configuration drift between environments, unpatched third-party CVEs entering production, and high-risk manual deployments over static SSH connections.

This project, titled **"Cloud-Based DevSecOps Platform for Automated Application Deployment and Monitoring,"** designs, implements, and empirically validates an end-to-end, production-grade DevSecOps platform. Built upon an enterprise consulting application ("ABC Free Consultants") paired with an engineering management console and real-time operations dashboard, the platform automates the entire Software Development Lifecycle (SDLC) from code commit to cloud deployment.

The platform integrates:
1. **Automated Continuous Integration (CI):** 84 automated tests (9 core application route tests, 42 Blue/Green deployment engine and recovery tests, and 33 platform telemetry and security tests) executed via `pytest`.
2. **Static Application Security Testing (SAST):** Code quality, code smells, bug detection, and security hotspot scanning via an ephemeral SonarQube Community Edition container.
3. **Software Composition Analysis (SCA) & Container Security:** Aqua Security Trivy scanning both repository dependencies and container image layers with zero-tolerance blocking gates on Critical and High vulnerabilities.
4. **Infrastructure-as-Code (IaC):** Declarative Terraform code provisioning an isolated AWS VPC, public subnets, route tables, internet gateways, least-privilege IAM roles, an ECR container repository with AES256 encryption, and an EC2 instance enforcing IMDSv2.
5. **Continuous Deployment (CD) with Zero-Downtime Blue/Green Cutover:** Agent-based deployment orchestrated via AWS Systems Manager (SSM Run Command) with dual application slots (`devsecops-app-blue` and `devsecops-app-green`), pre-warming candidate containers, isolated Nginx configuration validation, atomic upstream switching (`nginx -s reload`), and automatic sub-second rollback.
6. **Continuous Monitoring & Observability:** Real-time Golden Signals metrics collection via Prometheus and provisioned operational dashboards in Grafana.

---

## 2. PROBLEM STATEMENT & OBJECTIVES

### 2.1 Problem Statement
Traditional software engineering and deployment models face significant bottlenecks:
- **Late-Stage Security Audits:** Security testing typically occurs at the end of the SDLC ("Pen-testing before launch"), making remediation costly and causing release delays.
- **Credential Sprawl & SSH Exposure:** Production deployments commonly rely on static SSH keys distributed across developer machines or CI environments, creating high-risk vectors for credential theft.
- **Configuration Drift & Lack of Parity:** Manual server configuration leads to divergence between local development and cloud production, causing "works on my machine" defects.
- **Downtime During Deployments:** Traditional container deployments stop the existing container before starting the replacement, causing 5 to 15 seconds of service unavailability (HTTP 502/504 errors).
- **Silent Failures & Lack of Feedback Loops:** Operations teams lack immediate visibility into database connectivity, response latencies, and container failure states.

### 2.2 Project Objectives
1. **Shift-Left Security:** Embed security scans (SAST, SCA, container vulnerability scanning) into the automated CI/CD pipeline, halting execution on any unmitigated High or Critical CVE.
2. **Zero-SSH Production Deployment:** Eliminate port 22 (SSH) entirely from cloud security groups by leveraging AWS Systems Manager (SSM) agent communication over outbound HTTPS.
3. **Environment Parity via Containerization:** Containerize all tiers (Application, Reverse Proxy, Database, Metrics Collector, Dashboard Visualizer) using Docker Compose for complete parity between local development and AWS production.
4. **Zero-Downtime Blue/Green Deployments:** Implement an automated traffic switching engine using dual application container slots and modular Nginx upstream configuration, ensuring 100% availability during deployments.
5. **Resilient Circuit-Breaker Architecture:** Engineer database connectivity with fallback mechanisms to ensure the web application gracefully degrades rather than crashing during database maintenance or network interruptions.
6. **End-to-End Observability:** Expose structured Golden Signals metrics (`/metrics`) for automated Prometheus scraping and visualize operational health via Grafana dashboards.

---

## 3. EXISTING SYSTEM VS. PROPOSED DEVSECOPS SYSTEM

| Dimension | Existing / Traditional Approach | Proposed Cloud DevSecOps Platform |
| :--- | :--- | :--- |
| **Security Auditing** | Manual, periodic security reviews performed prior to launch. | Automated SAST (SonarQube) and SCA (Trivy) gates executed on every push and PR. |
| **Server Access** | Static SSH key pairs shared across engineers and CI secrets. | Zero-SSH architecture using AWS Systems Manager (SSM) over TLS 443. |
| **Deployment Strategy** | In-place container replacement with 5–15 seconds of downtime. | Blue/Green zero-downtime deployment with atomic Nginx reload and automated rollback. |
| **Configuration Management** | Manual console edits or ad-hoc shell scripts on production servers. | Infrastructure as Code (Terraform) and versioned repository configuration. |
| **Database Failure Handling**| Application crashes with unhandled 500 Internal Server Errors. | Circuit breaker with thread-safe in-memory fallback and honest `/health` reporting. |
| **Observability** | Ad-hoc server log tailing and manual uptime checks. | Automated metrics collection with Prometheus and real-time Grafana dashboards. |
| **CI/CD Gating** | Unverified pull request merges directly affecting production. | Strict 4-job architecture requiring manual `workflow_dispatch` authorization for production. |

---

## 4. SYSTEM ARCHITECTURE & DATA FLOW

### 4.1 Architectural Overview
The architecture is partitioned into three distinct operational domains:
1. **Developer Workstation (Local Development Stack):** Docker Compose orchestrating Flask, MySQL 8.0, Nginx reverse proxy, Prometheus, and Grafana in an isolated bridge network (`devsecops-network`).
2. **Continuous Integration & Delivery (GitHub Actions):** Ephemeral Ubuntu runners executing automated test suites, SonarQube analysis, Trivy security gates, and multi-stage Docker builds.
3. **Cloud Production Infrastructure (AWS `ap-south-1`):** Custom AWS VPC (`10.0.0.0/16`), public subnet (`10.0.1.0/24`), EC2 instance (`t3.micro`) running Amazon Linux 2023 with SSM Agent, Amazon ECR repository with AES256 encryption, and SSM Parameter Store for decrypted secret injection.

### 4.2 Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                            DEVELOPER WORKSTATION                                  |
|  +-----------------------------------------------------------------------------+  |
|  | Docker Compose Stack (devsecops-network)                                    |  |
|  | [Nginx :80] ---> [Flask App :5000] ---> [MySQL 8.0 :3306]                   |  |
|  |                        ^                                                    |  |
|  |                        +--- [Prometheus :9090] <--- [Grafana :3000]         |  |
|  +-----------------------------------------------------------------------------+  |
+----------------------------------------+------------------------------------------+
                                         | git push (main / feature PR)
                                         v
+-----------------------------------------------------------------------------------+
|                        GITHUB ACTIONS CI/CD RUNNER (Ubuntu)                       |
|  [Stage 1: Checkout & Python Setup]                                               |
|       |                                                                           |
|  [Stage 2: Pytest Suite (84 Tests Passing)]                                       |
|       |                                                                           |
|  [Stage 3: SonarQube SAST Scanner (:9000)]                                        |
|       |                                                                           |
|  [Stage 4: Aqua Security Trivy Filesystem Scan]                                   |
|       |                                                                           |
|  [Stage 5: Multi-Stage Docker Image Build]                                        |
|       |                                                                           |
|  [Stage 6: Aqua Security Trivy Container Image Scan]                              |
|       |                                                                           |
|  [Branch Gate: PR stops here | push to main continues]                            |
|       |                                                                           |
|  [Stage 7: AWS ECR Authentication & Image Push]                                   |
|       |                                                                           |
|  [Stage 8: AWS SSM Run Command Execution (Zero-SSH to EC2)]                       |
|       |                                                                           |
|  [Stage 9: Production Health Check Verification (/health & /metrics)]             |
+----------------------------------------+------------------------------------------+
                                         | HTTPS (AWS SSM Agent)
                                         v
+-----------------------------------------------------------------------------------+
|                       AWS CLOUD INFRASTRUCTURE (ap-south-1)                       |
|  +-----------------------------------------------------------------------------+  |
|  | Custom VPC (10.0.0.0/16) - Subnet (10.0.1.0/24) - IGW - Route Table         |  |
|  | EC2 Instance (t3.micro / Amazon Linux 2023) - Instance Profile (SSM + ECR)   |  |
|  | Security Group (Port 80/443 Ingress, No Port 22 Ingress)                    |  |
|  | IMDSv2 Required - Root EBS Storage (gp3)                                     |  |
|  |                                                                             |  |
|  | Containers on EC2:                                                          |  |
|  | [Nginx Upstream Proxy :80]                                                  |  |
|  |      |---> [Flask Blue Slot :5001]                                          |  |
|  |      +---> [Flask Green Slot :5002]                                         |  |
|  |                                                                             |  |
|  | Backend Services:                                                           |  |
|  | [MySQL Container :3306] <--- [Prometheus :9090] <--- [Grafana :3000]       |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 5. HARDWARE AND SOFTWARE REQUIREMENTS

### 5.1 Development & Demonstration Environment
- **Operating System:** Windows 10/11 Pro or Enterprise / Ubuntu 22.04 LTS
- **Processor:** 64-bit Intel Core i5 / AMD Ryzen 5 or higher (minimum 4 cores)
- **RAM:** Minimum 8 GB (16 GB recommended for concurrent Docker execution)
- **Disk Space:** Minimum 25 GB free SSD storage
- **Container Engine:** Docker Desktop v24+ with Linux container mode enabled
- **Interpreter:** Python 3.12 or 3.14 (64-bit)

### 5.2 Cloud & Production Environment (AWS)
- **Compute:** AWS EC2 `t3.micro` (2 vCPUs, 1 GiB RAM) running Amazon Linux 2023 AMI
- **Storage:** 8 GiB General Purpose SSD (`gp3`)
- **Network:** AWS Virtual Private Cloud (VPC), 1 Public Subnet, 1 Internet Gateway
- **Registry:** AWS Elastic Container Registry (ECR) with AES256 server-side encryption
- **Secrets & Configuration:** AWS Systems Manager (SSM) Parameter Store
- **Security:** AWS Identity & Access Management (IAM) role with `AmazonSSMManagedInstanceCore` and IMDSv2 enforcement

---

## 6. APPLICATION MODULES & IMPLEMENTATION

### 6.1 Module 1: Core Web Application (`app/app.py`)
Built using **Flask 3.1.3**, the application delivers dual interfaces:
1. **ABC Free Consultants Portal (`/demo`, `/client-app`):** Client-facing consulting portal featuring service catalogs, consultation inquiry forms, and contact handling.
2. **Unified DevSecOps Dashboard (`/`):** Real-time operations console displaying CI/CD pipeline execution status, vulnerability scan findings, infrastructure configuration, container health, and rollback options.
- **REST API Endpoints:**
  - `GET /health`: Returns operational health status, application version, and database connectivity metadata.
  - `GET /metrics`: Exposes Prometheus-compatible metrics (`flask_http_request_total`, request duration histograms, database availability gauges).
  - `GET /api/status`: Provides system telemetry, active commit hash, uptime, and underlying tool versions.
  - `POST /api/contact`: Validates user inquiries (Name, Email, Company, Service, Message) and persists them using parameterized queries.

### 6.2 Module 2: Resilient Database Layer (`app/database.py`)
- Employs **PyMySQL 1.1.1** with a resilient circuit-breaker pattern.
- When MySQL is accessible, inquiries are committed to the `devsecops_db` relational database.
- When MySQL is unreachable or restarting:
  - The circuit breaker trips to prevent connection timeouts from blocking the web worker threads.
  - Inquiries are stored in a thread-safe in-memory store (`_consultations_store`).
  - `/health` truthfully reports `{"database": {"connected": false, "mode": "offline_fallback"}}` rather than crashing with an unhandled exception.

### 6.3 Module 3: Security & Platform Blueprints (`app/platform_routes.py`, `app/platform_service.py`)
- Provides honest, grounded telemetry across system components:
  - Parses `.trivyignore` to report exact ignored CVEs (`GHSA-6v7p-g79w-8964`, `CVE-2025-47273`) with full policy justification.
  - Separates local container development telemetry from cloud production infrastructure.
  - Maps GitHub Actions workflow states (`completed` + `success` $\to$ `PASSED`; `in_progress` $\to$ `RUNNING`; `failure` $\to$ `FAILED`).

---

## 7. DEVSECOPS PIPELINE & SECURITY GATES

### 7.1 The 13 Pipeline Stages in GitHub Actions
The pipeline defined in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) enforces a strict 4-job architecture:
1. **Checkout Source:** SHA-pinned action `actions/checkout@v4` fetches the repository.
2. **Python Environment Setup:** Configures Python 3.12 with pip cache optimization.
3. **Dependency Installation:** Upgrades pip and installs locked application dependencies and testing frameworks.
4. **Pytest Automated Testing:** Executes the comprehensive 84-test automated test suite.
5. **Static Code Quality (SonarQube):** Spins up an ephemeral SonarQube container on port 9000, generates an ephemeral analysis token, and scans `app/` for bugs, vulnerabilities, and security hotspots.
6. **Trivy Filesystem Vulnerability Scan:** Audits Python packages against the Aqua Security vulnerability database, failing on unmitigated High or Critical CVEs.
7. **Container Image Build:** Builds the hardened Alpine-based Docker container image `devsecops-platform`.
8. **Trivy Container Image Scan:** Scans the built container layers for OS and binary vulnerabilities with zero-tolerance blocking gates.
9. **Authorization & Branch Gate:** Pull requests and standard pushes terminate after testing and scanning; production deployment requires explicit manual authorization via `workflow_dispatch` with `deploy_to_production: true` on `main`.
10. **AWS ECR Authentication:** Authenticates the runner against Amazon ECR using GitHub OIDC role federation.
11. **ECR Image Publication:** Tags and pushes container images with immutable commit SHA and `latest` tags.
12. **AWS SSM Blue/Green Deployment:** Dispatches the zero-downtime deployment script to EC2 via AWS Systems Manager Run Command (no open SSH ports).
13. **Independent Production Health Verification:** The CI runner independently polls `http://<EC2-IP>/health` to confirm HTTP 200 with `connected: true` and `mode: live_mysql`.

---

## 8. BLUE/GREEN ZERO-DOWNTIME DEPLOYMENT ENGINE

### 8.1 Architecture & Workflow
The Blue/Green deployment engine ([`scripts/deploy_blue_green.sh`](scripts/deploy_blue_green.sh)) orchestrates zero-downtime application updates on the EC2 host:
1. **Concurrency Control:** Acquires an exclusive deployment lock (`/tmp/deploy_blue_green.lock`) using `flock`, with directory-based fallback. Stale locks (>600s) are automatically reclaimed.
2. **Route Discovery Without Assumptions:** Parses `/etc/nginx/conf.d/upstream.conf` and live runtime `nginx -T`, strips comments, checks strict directive patterns, and detects the active slot (Blue or Green) without bias. Fails closed on ambiguous or split configurations.
3. **Pre-warming Candidate Container:** Starts the candidate container (`devsecops-app-green` on port 5002 if Blue is active, or `devsecops-app-blue` on port 5001 if Green is active) while the active container continues serving live traffic.
4. **Isolated Health Probing:** Probes candidate health on its direct port for up to 30 seconds. If the candidate fails to respond or cannot connect to MySQL, the candidate container is stopped and live traffic remains uninterrupted.
5. **Pre-flight Nginx Validation:** Validates the proposed Nginx upstream configuration inside an isolated `nginx:alpine` container with `nginx -t` before modifying any host configuration.
6. **Atomic Traffic Cutover:** Writes the verified upstream configuration to `/etc/nginx/conf.d/upstream.conf` and triggers `nginx -s reload`, seamlessly switching incoming connections with 0 dropped requests.
7. **Automated Rollback:** If post-switch health validation fails on port 80, the engine immediately restores the backed-up upstream configuration and reloads Nginx in under 3 seconds.
8. **Draining & Cleanup:** Only after the candidate passes all health checks is the previous container stopped. The `cleanup_on_exit` trap explicitly protects the active serving container from being terminated during early aborts.

---

## 9. INFRASTRUCTURE AS CODE (TERRAFORM) & SAFETY AUDIT

### 9.1 Resource Specifications (`terraform/`)
- **Terraform Version:** `>= 1.6.0` with AWS Provider `~> 6.0`
- **VPC Configuration (`terraform/main.tf`):** Dedicated CIDR `10.0.0.0/16` with DNS hostname support enabled.
- **Subnet Configuration:** Public subnet `10.0.1.0/24` in availability zone `ap-south-1a`.
- **Security Group (`devsecops-security-group`):** Ingress permitted exclusively on HTTP (Port 80) and HTTPS (Port 443). **Port 22 (SSH) is completely omitted.**
- **IAM Instance Profile (`terraform/iam.tf`):** Attached `AmazonSSMManagedInstanceCore` and `CloudWatchAgentServerPolicy`, with least-privilege inline permissions for ECR image pull and SSM Parameter Store read.
- **ECR Repository (`terraform/ecr.tf`):** Configured with AES256 server-side encryption, scan-on-push, and lifecycle policy retaining the 30 most recent tagged images.
- **Instance Hardening:** IMDSv2 enforced via `http_tokens = "required"` to prevent SSRF-based IAM credential theft.

### 9.2 Known Drift & Strict Read-Only Policy
- **Audit Finding:** In `terraform/terraform.tfstate`, the live root EBS volume (`vol-0adf25d8604bf595c`) has `encrypted: false`, whereas `terraform/main.tf` specifies `encrypted = true`.
- **Destructive Replacement Risk:** AWS EBS does not support modifying encryption in-place on an attached root volume. Running `terraform apply` would force instance recreation (`forces replacement`), destroying the active EC2 host, releasing its public IP (`13.232.174.161`), and disrupting service.
- **Governance Rule:** Terraform is strictly managed in read-only mode (`terraform plan` only) in production. In-place volume encryption must follow an intentional snapshot-and-restore maintenance procedure.

---

## 10. TEST METHODOLOGY & COMPLETE 84-TEST ACCEPTANCE MATRIX

The platform test suite contains **84 automated tests**, all executing and passing under `pytest` with zero failures.

### 10.1 Core Application Tests (`tests/test_app.py` — 9 Tests)
| # | Test Name | Target / Verification | Result |
|---|---|---|---|
| 1 | `test_home` | Root `/` renders unified platform interface with HTTP 200 | **PASS** |
| 2 | `test_health` | `/health` returns valid status JSON with database connectivity metadata | **PASS** |
| 3 | `test_static_assets` | Static CSS and JavaScript assets load properly with HTTP 200 | **PASS** |
| 4 | `test_metrics` | `/metrics` exports Prometheus metrics (`flask_http_request_total`) | **PASS** |
| 5 | `test_api_status` | `/api/status` exposes non-sensitive platform telemetry and uptime | **PASS** |
| 6 | `test_api_contact_valid` | Valid consultation submission returns HTTP 201 and persists record | **PASS** |
| 7 | `test_api_contact_invalid_email` | Malformed email is rejected with HTTP 400 and validation error | **PASS** |
| 8 | `test_api_contact_missing_fields`| Missing mandatory fields return HTTP 400 with specific field indicators | **PASS** |
| 9 | `test_api_contact_get` | `GET /api/contact` returns list of consultations and total count | **PASS** |

### 10.2 Blue/Green Deployment Engine Tests (`tests/test_deploy_blue_green.py` — 42 Tests)
| # | Test Name | Target / Verification | Result |
|---|---|---|---|
| 10 | `test_active_blue_switches_to_green` | Verified Blue active route switches to Green candidate upon health check | **PASS** |
| 11 | `test_active_green_switches_to_blue` | Verified Green active route switches to Blue candidate upon health check | **PASS** |
| 12 | `test_unhealthy_candidate_is_rejected` | Unhealthy candidate container is destroyed; traffic never switches | **PASS** |
| 13 | `test_candidate_with_disconnected_mysql_rejected` | Candidate with failing MySQL health ping is rejected | **PASS** |
| 14 | `test_invalid_nginx_configuration_prevents_switching` | Malformed Nginx config fails pre-flight check and aborts cutover | **PASS** |
| 15 | `test_nginx_reload_failure_triggers_rollback` | Failed Nginx reload triggers automatic rollback to previous upstream | **PASS** |
| 16 | `test_post_switch_health_failure_triggers_rollback` | Port 80 failure after reload triggers instant upstream rollback | **PASS** |
| 17 | `test_rollback_failure_reported_clearly` | Clear error reporting if rollback also fails | **PASS** |
| 18 | `test_unknown_active_slot_aborts_safely` | Unidentifiable active slot aborts without touching containers | **PASS** |
| 19 | `test_ambiguous_active_targets_abort_safely` | Conflicting multiple active directives abort before changes | **PASS** |
| 20 | `test_secret_values_do_not_appear_in_logs` | SSM passwords and tokens are never printed to stdout/stderr | **PASS** |
| 21 | `test_production_containers_never_stopped_or_removed` | Active container is protected from accidental termination | **PASS** |
| 22 | `test_concurrent_deployment_aborts_when_lock_held` | Second deployment aborts immediately if lockfile is held | **PASS** |
| 23 | `test_stale_lock_is_reclaimed_safely` | Abandoned lockfiles older than 600s are reclaimed safely | **PASS** |
| 24 | `test_missing_upstream_conf_discovers_active_v1_route` | Discovers active route from monolithic config when upstream.conf absent | **PASS** |
| 25 | `test_missing_upstream_conf_unidentifiable_route_aborts` | Aborts safely if monolithic config has unrecognizable target | **PASS** |
| 26 | `test_candidate_health_check_failure_cleans_candidate_only` | Health check failure stops candidate only, leaving active untouched | **PASS** |
| 27 | `test_rollback_restores_exact_original_upstream` | Rollback accurately restores exact byte content of original config | **PASS** |
| 28 | `test_cleanup_trap_never_targets_active_container_on_early_abort` | Trap handler ignores active container during aborts | **PASS** |
| 29 | `test_commented_out_green_reference_while_blue_is_active` | Commented directives are stripped and do not trigger false ambiguity | **PASS** |
| 30 | `test_both_slot_names_present_but_only_one_active_directive` | Slot names in comments or headers do not mislead parser | **PASS** |
| 31 | `test_ambiguous_runtime_nginx_routes_abort_before_container_changes` | Runtime `nginx -T` ambiguity halts script before starting containers | **PASS** |
| 32 | `test_legacy_app_5000_detection_and_exact_rollback_restoration` | Legacy `app:5000` route discovered and restored correctly on rollback | **PASS** |
| 33 | `test_legacy_devsecops_app_5000_detection_and_cutover` | Legacy `devsecops-app:5000` route discovered and migrated | **PASS** |
| 34 | `test_pre_stop_protection_aborts_if_candidate_is_active_traffic_destination` | Protects candidate if already receiving live traffic | **PASS** |
| 35 | `test_failed_backup_creation_refuses_cutover` | Aborts cutover if upstream backup creation fails or is empty | **PASS** |
| 36 | `test_preservation_of_mysql_and_persistent_volume_on_all_failures` | Database and persistent volumes are never stopped or pruned | **PASS** |
| 37 | `test_ci_nginx_bind_mount_and_stale_config_logic` | CI workflow validates bind mounts and re-provisions if inconsistent | **PASS** |
| 38 | `test_ci_route_detection_inline_and_minified` | CI route parser handles minified and single-line directives | **PASS** |
| 39 | `test_ci_route_detection_optional_parameters` | CI route parser handles directives with `weight`, `max_fails`, etc. | **PASS** |
| 40 | `test_ci_route_detection_both_legacy_aliases` | CI handles both `app:5000` and `devsecops-app:5000` aliases | **PASS** |
| 41 | `test_ci_missing_host_config_recovered_from_running_container` | Recovers configuration via `docker cp` if host files missing | **PASS** |
| 42 | `test_ci_failed_or_empty_container_backup_aborts_safely` | Aborts migration if container config copy is empty | **PASS** |
| 43 | `test_ci_invalid_generated_config_aborts_before_replacing_service` | CI aborts before touching running Nginx if generated syntax fails | **PASS** |
| 44 | `test_ci_replacement_container_startup_failure_triggers_recovery` | Restores original Nginx container if replacement container fails | **PASS** |
| 45 | `test_ci_replacement_health_check_failure_restores_original_service` | Restores original container if replacement health check fails | **PASS** |
| 46 | `test_ci_original_container_not_removed_before_successful_verification` | Original container is kept until replacement passes health check | **PASS** |
| 47 | `test_ci_mysql_and_persistent_volume_untouched_on_all_failures` | CI migration failures never disrupt database container | **PASS** |
| 48 | `test_ci_rename_failure_aborts_without_disruption` | Rename failure on original container aborts without disruption | **PASS** |
| 49 | `test_ci_stop_failure_restores_name_and_aborts` | Stop failure restores container name and aborts | **PASS** |
| 50 | `test_ci_upstream_backup_failure_aborts_safely` | Upstream backup failure halts CI migration | **PASS** |
| 51 | `test_ci_restoration_of_both_configuration_files_on_rollback` | Rollback in CI restores both `nginx.conf` and `upstream.conf` | **PASS** |

### 10.3 Platform API & Security Tests (`tests/test_platform.py` — 33 Tests)
| # | Test Name | Target / Verification | Result |
|---|---|---|---|
| 52 | `test_platform_home` | Platform root UI loads with HTTP 200 | **PASS** |
| 53 | `test_client_app_demo_route` | `/demo` and `/client-app` render consulting portal | **PASS** |
| 54 | `test_platform_overview` | `/api/platform/overview` aggregates tools telemetry | **PASS** |
| 55 | `test_platform_projects_list` | `/api/platform/projects` lists registered projects | **PASS** |
| 56 | `test_platform_project_details` | `/api/platform/projects/<id>` returns project metadata | **PASS** |
| 57 | `test_platform_project_not_found` | Nonexistent project returns HTTP 404 | **PASS** |
| 58 | `test_platform_validate_project` | Project validation endpoint verifies valid payload | **PASS** |
| 59 | `test_platform_validate_invalid_project` | Invalid project payload returns HTTP 400 | **PASS** |
| 60 | `test_platform_deployments_list` | `/api/platform/deployments` returns deployment history | **PASS** |
| 61 | `test_platform_deployments_trigger` | Deployment trigger returns simulated deployment record | **PASS** |
| 62 | `test_platform_pipelines_list` | `/api/platform/pipelines` returns GitHub Actions runs | **PASS** |
| 63 | `test_platform_security_status` | `/api/platform/security` returns Trivy and SonarQube data | **PASS** |
| 64 | `test_platform_monitoring_status` | `/api/platform/monitoring` returns Prometheus/Grafana status | **PASS** |
| 65 | `test_platform_infrastructure_status` | `/api/platform/infrastructure` returns AWS EC2/VPC data | **PASS** |
| 66 | `test_platform_environments_list` | `/api/platform/environments` lists Production, Staging, Dev | **PASS** |
| 67 | `test_platform_rollback_options` | `/api/platform/rollback/options` returns rollback image tags | **PASS** |
| 68 | `test_platform_diagnostics` | `/api/platform/diagnostics` returns socket check results | **PASS** |
| 69 | `test_platform_logs` | `/api/platform/logs` returns sanitized audit log lines | **PASS** |
| 70 | `test_platform_pipeline_honest_trigger` | Pipeline trigger without token returns honest HTTP 400 | **PASS** |
| 71 | `test_platform_pipeline_stages_mapping` | All 13 CI/CD stages are mapped with correct IDs and names | **PASS** |
| 72 | `test_platform_infrastructure_environment_separation` | Cleanly separates AWS Cloud from local Docker state | **PASS** |
| 73 | `test_platform_diagnostics_context_awareness` | Diagnostic engines report environment and check source | **PASS** |
| 74 | `test_platform_security_policy_wording` | `.trivyignore` CVEs use accurate policy and configuration wording | **PASS** |
| 75 | `test_platform_security_sonarqube_honest_status` | SonarQube reports real server telemetry without fabricating data | **PASS** |
| 76 | `test_platform_monitoring_prometheus_states` | Monitoring endpoint returns verified state classification | **PASS** |
| 77 | `test_dashboard_live_health_indicator` | Frontend contains live health indicator and accessibility attributes | **PASS** |
| 78 | `test_map_github_workflow_status_matrix` | 100% matrix coverage of GitHub Actions workflow status mapping | **PASS** |
| 79 | `test_pipeline_endpoint_real_shaped_successful_run` | Structures real GitHub run as PASSED | **PASS** |
| 80 | `test_pipeline_endpoint_in_progress_never_shows_success` | In-progress workflow run is NEVER presented as PASSED | **PASS** |
| 81 | `test_pipeline_endpoint_failed_remains_failed` | Failed workflow run remains FAILED and is never coerced | **PASS** |
| 82 | `test_pipeline_endpoint_cancelled_and_skipped_states` | Cancelled and skipped runs are mapped accurately | **PASS** |
| 83 | `test_pipeline_endpoint_fallback_and_malformed_responses` | Malformed GitHub API responses do not cause crashes | **PASS** |
| 84 | `test_pipeline_endpoint_no_credentials_exposed` | GITHUB_TOKEN and Authorization headers are never leaked | **PASS** |

---

## 11. INSTALLATION & LOCAL EXECUTION GUIDE

### 11.1 Prerequisites
- Python 3.12+ (for running pytest locally)
- Docker Desktop with Docker Compose v2
- Git

### 11.2 Step-by-Step Local Setup

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/mohdshahid7033/cloud-devsecops-platform.git
   cd cloud-devsecops-platform
   ```

2. **Configure Local Environment Variables:**
   ```bash
   # .env (local only; never commit credentials)
   DB_PASSWORD=local_db_pass_example
   MYSQL_ROOT_PASSWORD=local_root_pass_example
   ```

3. **Start the Multi-Tier Stack via Docker Compose:**
   ```bash
   docker compose up --build -d
   ```

4. **Verify Service Access:**
   - **DevSecOps Management Dashboard:** `http://localhost/` or `http://localhost:5000/`
   - **ABC Free Consultants Portal:** `http://localhost/demo`
   - **Application Health Check:** `http://localhost/health`
   - **Prometheus Metrics:** `http://localhost:9090/`
   - **Grafana Visualizations:** `http://localhost:3000/` (credentials: `admin` / `admin`)

5. **Execute the Full Automated Test Suite:**
   ```bash
   python -m pytest -v
   ```

---

## 12. SCREENSHOT CHECKLIST FOR REPORT SUBMISSION

| Item | Description | Verification Target |
|---|---|---|
| **Screenshot 1** | DevSecOps Management Console Dashboard | `http://localhost/` showing system overview, pipeline stages, and live health chip |
| **Screenshot 2** | ABC Free Consultants Web Portal | `http://localhost/demo` showing consultation booking form and services |
| **Screenshot 3** | Pytest Execution Results | Terminal output displaying `84 passed in ...` |
| **Screenshot 4** | SonarQube SAST Code Analysis | SonarQube portal (`:9000`) displaying Quality Gate Passed, 0 Bugs, 0 Vulnerabilities |
| **Screenshot 5** | Trivy Vulnerability Scan Output | Terminal or CI log displaying 0 High/Critical findings |
| **Screenshot 6** | Prometheus Metrics Scrape Target | Prometheus (`:9090/targets`) displaying `devsecops-app` endpoint UP |
| **Screenshot 7** | Grafana Operational Dashboard | Grafana (`:3000`) showing Golden Signals (request rates, latency histograms) |
| **Screenshot 8** | GitHub Actions Workflow Execution | GitHub Actions UI displaying green checkmarks on `test-and-scan` job |

---

## 13. RESULTS AND DISCUSSION

### 13.1 Measurable Outcomes
- **Release Velocity:** Automated CI/CD pipeline executes all 84 tests, SonarQube SAST, and Trivy filesystem/container scans in under 6 minutes.
- **Zero-Downtime Deployment:** Empirical validation with isolated prototype scripts confirmed 103/103 successful HTTP requests with 0 dropped connections during live Nginx upstream reload.
- **Vulnerability Remediation:** Resolved critical vulnerabilities in base images by upgrading to `python:3.14-alpine`, pinning patched packages (`msgpack>=1.2.1`, `setuptools>=78.1.1`), and removing build tools (`pip`, `wheel`) in the final container image layer.
- **Security Hardening:** Enforced IMDSv2 on AWS EC2, eliminated inbound port 22, and eliminated hardcoded credentials in favor of AWS SSM Parameter Store with SecureString encryption.

### 13.2 Key Learnings
- **Syntax Validity vs. Runtime Safety:** Verifying syntax via `bash -n` or YAML linters does not guarantee safe execution. Edge cases like ambiguous upstream routes, stale lockfiles, or missing container backups require explicit runtime guard logic.
- **Circuit Breakers for Database Resilience:** Separating web tier availability from database availability ensures users receive graceful responses rather than broken connection errors during database maintenance.
- **Least-Privilege Cloud Architecture:** Using AWS Systems Manager Run Command eliminates static SSH keys from CI environments, preventing credential sprawl.

---

## 14. KNOWN LIMITATIONS & FUTURE ENHANCEMENTS

### 14.1 Known Limitations
1. **Single-Node EC2 Architecture:** Production workloads currently run on a single EC2 instance (`t3.micro`). While container slots enable zero-downtime application updates, host-level hardware failure would cause service downtime.
2. **Terraform Root Volume Encryption Drift:** Live EBS volume is unencrypted while Terraform HCL specifies `encrypted = true`. Applying Terraform would destroy and recreate the instance.
3. **Local GitHub API Rate Limits:** When running locally without a `GITHUB_TOKEN`, GitHub API rate limits (60 requests/hour) may cause the dashboard to display cached or database fallback telemetry.

### 14.2 Future Enhancements
1. **Kubernetes (EKS) Migration:** Transition container orchestration to Amazon Elastic Kubernetes Service (EKS) with Helm charts and Horizontal Pod Autoscaling (HPA).
2. **Automated Canary Traffic Shifting:** Integrate AWS Application Load Balancer (ALB) or service meshes (Istio/Envoy) for automated percentage-based traffic routing.
3. **Dynamic Application Security Testing (DAST):** Incorporate OWASP ZAP into the post-deployment verification phase to probe running endpoints for runtime vulnerabilities.

---

## 15. CONCLUSION & REFERENCES

### 15.1 Conclusion
The Cloud-Based DevSecOps Platform successfully demonstrates that rigorous security controls, automated testing, zero-downtime deployment, and continuous observability can be unified into an efficient, production-grade software delivery pipeline. By combining Shift-Left security principles with zero-SSH cloud deployments and comprehensive monitoring, this project fulfills all academic requirements for the Bachelor of Computer Applications (BCA) degree and demonstrates practical, job-ready engineering competence.

### 15.2 References
1. Humble, J., & Farley, D. (2010). *Continuous Delivery: Reliable Software Releases through Build, Test, and Deployment Automation.* Addison-Wesley.
2. Kim, G., Humble, J., Debois, P., & Willis, J. (2016). *The DevOps Handbook: How to Create World-Class Agility, Reliability, and Security in Technology Organizations.* IT Revolution Press.
3. Aqua Security Trivy Documentation. *Comprehensive Vulnerability Scanner for Containers and other Artifacts.* https://trivy.dev/
4. SonarQube Documentation. *Code Quality and Code Security.* https://docs.sonarqube.org/
5. Amazon Web Services. *AWS Systems Manager User Guide — Run Command.* https://docs.aws.amazon.com/systems-manager/
6. Prometheus Authors. *Prometheus Monitoring System and Time Series Database.* https://prometheus.io/docs/
7. Nginx Documentation. *Configuring Nginx HTTP Load Balancing and Upstream Servers.* https://nginx.org/en/docs/

---

## 16. VIVA VOCE QUESTIONS & COMPREHENSIVE ANSWERS

### Q1: What is DevSecOps and how does it differ from traditional DevOps?
**Answer:** DevSecOps introduces security as an integral, automated component throughout the Software Development Life Cycle (SDLC) rather than treating it as an afterthought or a separate phase before deployment. In traditional DevOps, development and operations collaborate for automated continuous integration and continuous deployment (CI/CD), but security audits (penetration testing, compliance checks) were frequently manual and conducted late. DevSecOps "shifts security left" by integrating automated SAST (SonarQube), SCA (Trivy), container vulnerability scanning, and least-privilege IAM policies directly into the CI pipeline, rejecting insecure code before merge.

### Q2: What is Blue/Green deployment, and how does your project achieve zero downtime?
**Answer:** Blue/Green deployment is a release technique that reduces downtime and risk by running two identical production container slots: one active (e.g., Blue, serving live user traffic on port 5001) and one idle (e.g., Green, pre-warming on port 5002).
In our project:
1. The new container is deployed to the idle slot and pre-warmed.
2. The engine probes the candidate's direct port (`/health`) to confirm database connectivity and HTTP 200 before routing traffic.
3. The proposed Nginx configuration is validated in an isolated container using `nginx -t`.
4. Nginx updates its `upstream.conf` pointer and executes `nginx -s reload`. Nginx performs a worker process handover without dropping incoming TCP connections.
5. If post-switch health validation fails, Nginx rolls back to the previous upstream file in under 3 seconds.

### Q3: Why did you eliminate SSH port 22 in your AWS Security Group?
**Answer:** Direct SSH access requires generating, distributing, rotating, and revoking private key pairs (`.pem` files). If a private key leaks or is accidentally committed to a repository, the entire EC2 instance is compromised. Furthermore, opening port 22 exposes the server to internet-wide brute-force and port-scanning attacks. We replaced SSH with AWS Systems Manager (SSM) Run Command. The SSM agent runs on the EC2 instance and initiates outbound HTTPS (TLS 443) connections to AWS endpoints. All actions are authenticated via AWS IAM and fully audited in AWS CloudTrail, eliminating SSH key management entirely.

### Q4: Explain the difference between SAST and SCA.
**Answer:**
- **Static Application Security Testing (SAST):** Analyzes application source code (`.py`, `.html`, `.js`) for programming errors, security anti-patterns, injection flaws (SQLi, XSS), hardcoded credentials, and code smells without executing the code. We use **SonarQube Community Edition**.
- **Software Composition Analysis (SCA):** Scans third-party libraries, dependencies (`requirements.txt`), and container image base layers for publicly known Common Vulnerabilities and Exposures (CVEs). We use **Aqua Security Trivy**.

### Q5: What is IMDSv2 and why is it critical on AWS EC2?
**Answer:** IMDSv2 is AWS Instance Metadata Service Version 2. Under IMDSv1, metadata could be retrieved via simple HTTP GET requests (`http://169.254.169.254/latest/meta-data/`). If an application suffered from a Server-Side Request Forgery (SSRF) flaw, an attacker could trick the app into fetching the instance's temporary IAM role credentials. IMDSv2 requires a `PUT` request with a custom header (`X-aws-ec2-metadata-token-ttl-seconds`) to generate an ephemeral session token before metadata can be read. In `terraform/main.tf`, we enforce `http_tokens = "required"`, neutralizing SSRF credential exfiltration.

### Q6: How does the circuit breaker in `app/database.py` work?
**Answer:** When the Flask application attempts to connect to MySQL via PyMySQL, connection timeouts could freeze web workers for up to 30 seconds, exhausting worker pools and causing HTTP 504 Gateway Timeouts. Our circuit breaker detects consecutive database connection failures, trips to an `offline_fallback` mode, logs the issue, and routes incoming inquiries to a thread-safe in-memory store. The application `/health` endpoint continues to respond with HTTP 200 while honestly reporting `connected: false` and `mode: offline_fallback`, enabling monitoring alerts without crashing user sessions.

### Q7: What are the Google SRE Golden Signals and how are they collected?
**Answer:** The four Golden Signals are:
1. **Latency:** Time taken to service requests. Measured via histogram metric `flask_http_request_duration_seconds_bucket`.
2. **Traffic:** Demand placed on the system. Measured via counter metric `flask_http_request_total`.
3. **Errors:** Rate of failed requests. Calculated from `flask_http_request_total` partitioned by HTTP status code (`status=~"5.."`).
4. **Saturation:** Utilization of system resources (CPU, RAM, DB connection pool). Collected via node exporters and Prometheus database gauges (`devsecops_database_up`).

### Q8: What is Terraform state drift and what specific drift was discovered in this project?
**Answer:** State drift occurs when the actual configuration of cloud resources diverges from the state recorded in Terraform's `.tfstate` file or defined in `.tf` source code. In this project, an audit revealed that the live EC2 root volume (`vol-0adf25d8604bf595c`) was created unencrypted (`encrypted: false`), while `terraform/main.tf` specified `encrypted = true`. Because AWS does not allow modifying root volume encryption in-place on an existing instance, running `terraform apply` would force instance recreation (`forces replacement`), destroying the active EC2 host and causing production downtime. We enforced a strict read-only policy for Terraform to prevent unexpected service destruction.

---

## 17. BEGINNER-FRIENDLY ORAL DEMONSTRATION WALKTHROUGH

*Use this script during your final project evaluation or viva demonstration:*

1. **Introduction (1 minute):**
   > *"Good morning respected evaluators. My project is the Cloud-Based DevSecOps Platform. The goal of this project is to eliminate the traditional wall between developers, security teams, and operations by creating an automated, security-gated pipeline that tests, scans, and deploys applications to AWS with zero downtime and zero SSH keys."*

2. **Local Application Demonstration (2 minutes):**
   > *"Let us start by looking at the running application on localhost. On port 5000, we have ABC Free Consultants, an enterprise consulting web application. Users can submit consulting inquiries through this form. Notice that our database layer features a circuit breaker: if MySQL is online, records are saved to the relational database; if MySQL is stopped, the application does not crash — it stores the inquiry in memory and transparently reports database status on the `/health` endpoint."*

3. **Operations Dashboard & Telemetry (2 minutes):**
   > *"Next, let us navigate to the DevSecOps Operations Console at `http://localhost/`. This dashboard provides real-time visibility into all 13 pipeline stages, security scan reports, infrastructure configurations, and Golden Signals. All metrics displayed are grounded in real tools: Prometheus scrapes latency and request rates every 15 seconds, and Grafana provides interactive visualization panels."*

4. **Security & Shift-Left Gating (2 minutes):**
   > *"In our CI/CD pipeline, security is a blocking gate. Before any code can be published or merged:
   > - Pytest runs our full 84-test automated test suite.
   > - SonarQube runs static analysis to catch bugs and vulnerabilities.
   > - Aqua Security Trivy scans both our dependencies and our Docker container image layers.
   > If any high or critical vulnerability is found, the build exits with code 1 and blocks deployment."*

5. **Production Deployment & Blue/Green Cutover (2 minutes):**
   > *"Finally, let us look at production deployment. Pull requests and normal pushes only run tests and scans — they can never deploy to production. Production release requires an explicit manual authorization step on the main branch.
   > When authorized, the deployment uses AWS Systems Manager Run Command — meaning port 22 SSH is completely closed. On EC2, we run Blue/Green deployment: the new version starts on an idle container port, pre-warms, passes health checks, and then Nginx atomically reloads traffic in under 3 seconds with zero dropped connections and automatic rollback if anything goes wrong."*

6. **Conclusion:**
   > *"In summary, this platform achieves 100% test automation with 84 passing tests, eliminates SSH keys, enforces shift-left security, and delivers zero-downtime releases on AWS. Thank you, and I am ready for questions."*
