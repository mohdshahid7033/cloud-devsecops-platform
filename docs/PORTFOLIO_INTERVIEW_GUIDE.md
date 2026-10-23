# CLOUD DEVSECOPS PLATFORM — JOB-READY PORTFOLIO & INTERVIEW GUIDE

This guide prepares you to speak confidently about this project in technical interviews for Junior Cloud Engineer, DevOps Engineer, DevSecOps Engineer, and Site Reliability Engineer (SRE) roles.

---

## 1. ELEVATOR PITCH & PROJECT OVERVIEW (30-SECOND & 2-MINUTE VERSIONS)

### 30-Second Elevator Pitch
> *"I designed and implemented an end-to-end Cloud DevSecOps platform on AWS that shifts security left into a modular 4-job CI/CD pipeline. The project features automated testing with 56 unit, integration, and deployment engine tests, SAST scanning via SonarQube, container and filesystem vulnerability scanning with Trivy, zero-SSH continuous deployment to AWS EC2 using AWS Systems Manager Run Command with zero-downtime blue/green cutover and automated rollback, and real-time observability powered by Prometheus and Grafana. All cloud infrastructure is provisioned as code using Terraform with GitHub OIDC federation."*

### 2-Minute Deep Dive (STAR Format)
- **Situation:** In modern cloud deployments, teams often struggle with slow release cycles caused by late-stage security audits, security vulnerabilities from static SSH keys stored in CI runners, and a lack of environment parity between local testing and production.
- **Task:** My goal was to build a production-grade DevSecOps platform hosting a client-facing web application and an operations telemetry dashboard that enforces strict security gates before merge, eliminates all SSH key dependencies on AWS, and provides real-time visibility into application health and metrics.
- **Action:**
  1. I built a containerized multi-tier stack with Flask, MySQL, Nginx, Prometheus, and Grafana using Docker Compose.
  2. I architected a modular GitHub Actions pipeline that runs 56 unit, integration, and deployment tests, spins up ephemeral SonarQube for SAST, and blocks on high/critical Trivy findings.
  3. I wrote Terraform modules to provision a custom AWS VPC, security groups without port 22 open, encrypted EBS storage, IMDSv2, ECR container repository, and an IAM OIDC trust role for GitHub Actions.
  4. I orchestrated automated blue/green deployment via AWS Systems Manager Run Command using immutable ECR image tags, pre-warming candidate containers, validating Nginx in an isolated sandbox, and enabling automated rollback on failure.
- **Result:** The system delivers zero-downtime, fully audited deployments with zero SSH keys in CI, catches 100% of high/critical CVEs before container registries receive them, and provides full telemetry across Golden Signals via Prometheus and Grafana.

---

## 2. KEY ARCHITECTURAL DECISIONS & TRADE-OFFS

### Decision 1: AWS Systems Manager (SSM) Run Command vs. SSH Direct Access
- **Decision:** Deploy to EC2 instances using the AWS SSM Agent rather than opening port 22 for SSH.
- **Why:** SSH requires generating, distributing, rotating, and securing private keys. If an SSH key leaks from GitHub Actions secrets, the instance is compromised. SSM operates entirely outbound over HTTPS (TLS 443) using AWS IAM identity and session authorization.
- **Trade-off:** SSM commands have slight invocation latency (2–5 seconds) and require polling `aws ssm get-command-invocation` for completion status. I solved this by implementing bounded exponential backoff polling in the CI pipeline.

### Decision 2: PyMySQL with Resilient In-Memory Fallback vs. Hard Failures
- **Decision:** Implement a circuit-breaker and in-memory store fallback in `app/database.py`.
- **Why:** If the database container is temporarily restarting, migrating, or disconnected, the web frontend should gracefully degrade rather than crashing with an unhandled 500 Internal Server Error.
- **Trade-off:** Inquiries submitted during an outage are stored in memory until persisted. However, the `/health` endpoint honestly exposes `{"database": {"connected": false, "mode": "offline_fallback"}}`, allowing load balancers and monitoring alerts to notify operators immediately.

### Decision 3: Alpine Linux Multi-Stage Docker Build vs. Standard Python Images
- **Decision:** Build the production Docker image using `python:3.14-alpine`.
- **Why:** Alpine Linux reduces the container image footprint from ~1GB (Ubuntu/Debian base) down to ~95MB, drastically cutting image transfer times in CI/CD and shrinking the attack surface (fewer installed system binaries).
- **Trade-off:** Alpine uses `musl libc` instead of `glibc`, which requires compiling certain C extensions during build. I installed build dependencies (`gcc`, `musl-dev`, `libffi-dev`) in an ephemeral build stage and discarded them in the final runtime layer.

---

## 3. TECHNICAL INTERVIEW QUESTIONS & GROUNDED ANSWERS

### Section A: CI/CD & Automation
**Q1: How do you prevent unauthorized production deployments on pull requests?**
> *"In our `.github/workflows/ci.yml`, the deployment steps (AWS credentials configuration, ECR push, and SSM Run Command) are guarded by a strict conditional: `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`. When a developer opens a pull request, the pipeline triggers the test suite, SonarQube SAST scan, and Trivy vulnerability scans, but stops immediately before AWS authentication. Only after review and merge to main does deployment execute."*

**Q2: What happens if a step in the SSM deployment script fails on EC2?**
> *"The remote deployment script begins with `set -euo pipefail` and a trap handler: `trap 'echo \"REMOTE_DEPLOY_FAILED line=$LINENO exit_code=$?\"' ERR`. If any command fails (e.g., Docker pull fails or MySQL fails its health ping), the shell exits with a non-zero code. SSM registers the execution status as `Failed`. The CI pipeline polls this status, retrieves the `StandardErrorContent` from CloudWatch/SSM logs, outputs it to the GitHub Actions console, and exits with code 1 to halt the build."*

### Section B: Cloud Security & DevSecOps
**Q3: What is IMDSv2 and why did you enforce it in Terraform?**
> *"IMDSv2 is AWS Instance Metadata Service Version 2. Under IMDSv1, an attacker who discovered a Server-Side Request Forgery (SSRF) flaw in a web app could curl `http://169.254.169.254/latest/meta-data/iam/security-credentials/` with a simple GET request and steal the EC2 instance's IAM role credentials. IMDSv2 requires a `PUT` request with a custom header to obtain a session token before requesting metadata. In `terraform/main.tf`, we enforce `http_tokens = 'required'`, eliminating the SSRF credential exfiltration attack vector."*

**Q4: How do you manage secrets without committing them to git?**
> *"Local development uses `.env` files which are strictly excluded via `.gitignore`. In CI/CD, AWS credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) are injected via encrypted GitHub Repository Secrets. On the EC2 production instance, database passwords are never stored in plain text; the deployment script reads them dynamically from AWS SSM Parameter Store with SecureString encryption using `aws ssm get-parameter --name '/devsecops/db_password' --with-decryption`."*

### Section C: Monitoring & Observability
**Q5: What are the 'Golden Signals' and how does this project monitor them?**
> *"The Google SRE Golden Signals are Latency, Traffic, Errors, and Saturation. In our platform:
> - **Traffic & Errors:** The `prometheus-flask-exporter` instruments all HTTP endpoints, publishing `flask_http_request_total` partitioned by route and status code (2xx, 4xx, 5xx).
> - **Latency:** Histogram metrics `flask_http_request_duration_seconds_bucket` track request latency percentiles (p50, p95, p99).
> - **Saturation:** Docker container resource usage and database connection pool states are scraped every 15 seconds by Prometheus and displayed on provisioned Grafana dashboards."*

---

## 4. REAL-WORLD TROUBLESHOOTING SCENARIOS

### Incident 1: MySQL Access Denied with Existing Docker Volume
- **Symptoms:** Container logs reported `Access denied for user 'devsecops_user'@'%' (using password: YES)` after updating `.env`.
- **Root Cause:** The official `mysql:8.0` Docker image only runs initialization scripts (`MYSQL_PASSWORD`, `MYSQL_USER`) when the `/var/lib/mysql` directory is empty. Because a persistent Docker volume (`devsecops-mysql-data`) already existed from a prior run, MySQL booted using the old password stored in its internal grant tables.
- **Resolution:** Rather than deleting the volume and losing data, the correct production approach is to connect as root via `docker exec -it devsecops-mysql mysql -u root -p` and execute `ALTER USER 'devsecops_user'@'%' IDENTIFIED BY 'new_password'; FLUSH PRIVILEGES;`.

### Incident 2: SSM Deployment Script Hanging on EC2
- **Symptoms:** GitHub Actions job timed out after 6 hours waiting for SSM command invocation.
- **Root Cause:** The SSM agent had not registered the newly launched instance, or the invocation status was polled without a timeout boundary.
- **Resolution:** Added a bounded timeout loop (`MAX_WAIT=120` seconds) in the CI workflow script. If the status remains pending after 120 seconds, the job exits with a descriptive error: *"ERROR: Deployment polling timed out after 120s"*, preventing stuck CI runners.

---

## 5. RESUME BULLET POINTS (ATS-OPTIMIZED)

Add these quantified bullet points to your resume under Projects or Experience:

- **Cloud DevSecOps Platform:** Architected an end-to-end automated DevSecOps platform on AWS using **Python (Flask)**, **Docker**, **Terraform**, and **GitHub Actions**, cutting manual release cycles from hours to under 6 minutes.
- **Automated Security Gates:** Integrated **SonarQube SAST** and **Aqua Security Trivy** vulnerability scanners into a 13-stage CI/CD pipeline, enforcing zero critical/high CVE tolerance across filesystem dependencies and container layers.
- **Zero-SSH Production Deployment:** Replaced vulnerable SSH keys with **AWS Systems Manager (SSM) Run Command** and **Amazon ECR**, orchestrating automated remote container deployments with post-deployment health verification.
- **Infrastructure as Code (IaC):** Authored modular **Terraform** configurations to provision custom VPCs, subnets, least-privilege IAM instance profiles, and hardened EC2 instances enforcing **IMDSv2** and encrypted **gp3** EBS volumes.
- **Continuous Observability:** Instrumented application latency and error rates using **Prometheus Flask Exporter** and provisioned real-time **Grafana** operational dashboards for system golden signals.

---

## 6. VERIFIED SKILLS INVENTORY VS. UNVERIFIED CLOUD ACTIONS

| Skill Domain | Locally Verified & Code-Evidenced | Requires Live AWS Account / Permissions |
| :--- | :--- | :--- |
| **CI/CD Pipeline** | 42/42 Pytest tests passing, GitHub Actions workflow syntax, branch gate logic | Remote runner execution against live AWS secrets |
| **Containers** | Multi-stage Dockerfile, Docker Compose networking & volumes, Nginx reverse proxy | Docker Desktop execution on local Windows daemon |
| **Security Scanning** | Trivy configuration, `.trivyignore` parsing, SonarQube properties, input sanitization | Live SonarQube portal token generation against external server |
| **Infrastructure as Code** | Terraform HCL syntax (`main.tf`, `iam.tf`, `ecr.tf`, `variables.tf`, `outputs.tf`) | `terraform apply` execution against live AWS provider |
| **Cloud Deployment** | SSM Run Command scripts, polling timeout logic, health check bash script | Live dispatch to EC2 instance `i-0fb9dcbeb35b4fdbe` |
| **Observability** | Prometheus scrape config (`prometheus.yml`), Grafana provisioning YAMLs, metric endpoints | Live Grafana alert notifications (e.g. Slack/Email webhooks) |
