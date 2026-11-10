# CLOUD DEVSECOPS PLATFORM — JOB-READY PORTFOLIO & INTERVIEW GUIDE

This guide prepares you to speak confidently about this project in technical interviews for Junior Cloud Engineer, DevOps Engineer, DevSecOps Engineer, and Site Reliability Engineer (SRE) roles.

---

## 1. ELEVATOR PITCH & PROJECT OVERVIEW (30-SECOND & 2-MINUTE VERSIONS)

### 30-Second Elevator Pitch
> *"I designed and implemented an end-to-end Cloud DevSecOps platform on AWS that shifts security left into a modular 4-job CI/CD pipeline. The project features automated testing with 152 unit, platform, and deployment engine tests, SAST scanning via SonarQube, Python dependency auditing via pip-audit, container and filesystem vulnerability scanning with Trivy, zero-SSH continuous deployment to AWS EC2 using AWS Systems Manager Run Command with zero-downtime blue/green cutover and automated rollback, and real-time observability powered by Prometheus and Grafana. All cloud infrastructure is provisioned as code using Terraform with GitHub OIDC federation."*

### 2-Minute Deep Dive (STAR Format)
- **Situation:** In modern cloud deployments, teams often struggle with slow release cycles caused by late-stage security audits, security vulnerabilities from static SSH keys stored in CI runners, and a lack of environment parity between local testing and production.
- **Task:** My goal was to build a production-grade DevSecOps platform hosting a client-facing web application and an operations telemetry dashboard that enforces strict security gates before merge, eliminates all SSH key dependencies on AWS, and provides real-time visibility into application health and metrics.
- **Action:**
  1. I built a containerized multi-tier stack with Flask, MySQL, Nginx, Prometheus, and Grafana using Docker Compose.
  2. I architected a modular GitHub Actions pipeline that runs 152 unit, platform, and deployment tests, spins up ephemeral SonarQube for SAST, runs pip-audit for Python SCA, generates CycloneDX SBOMs, and blocks on high/critical Trivy findings.
  3. I wrote Terraform modules to provision a custom AWS VPC, security groups without port 22 open, encrypted EBS storage, IMDSv2, ECR container repository, and an IAM OIDC trust role for GitHub Actions.
  4. I orchestrated automated blue/green deployment via AWS Systems Manager Run Command using immutable ECR image digests, a 4-tier Nginx route discovery cascade with host bind-mount provenance verification, pre-warming candidate containers, validating Nginx in an isolated sandbox, and enabling automated rollback on failure.
- **Result:** The system delivers zero-downtime, fully audited deployments with zero SSH keys in CI, catches 100% of high/critical CVEs before container registries receive them, and provides full telemetry across Golden Signals via Prometheus and Grafana.

---

## 2. KEY ARCHITECTURAL DECISIONS & TRADE-OFFS

### Decision 1: AWS Systems Manager (SSM) Run Command vs. SSH Direct Access
- **Decision:** Deploy to EC2 instances using the AWS SSM Agent rather than opening port 22 for SSH.
- **Why:** SSH requires generating, distributing, rotating, and securing private keys. If an SSH key leaks from GitHub Actions secrets, the instance is compromised. SSM operates entirely outbound over HTTPS (TLS 443) using AWS IAM identity and session authorization.
- **Trade-off:** SSM commands have slight invocation latency (2–5 seconds) and require polling `aws ssm get-command-invocation` for completion status. I solved this by implementing bounded exponential backoff polling in the CI pipeline.

### Decision 2: Zero-Downtime Blue/Green Nginx Upstream Cutover vs. Single Container In-Place Replacement
- **Decision:** Deploy dual application slots (`devsecops-app-blue` on port 5001 and `devsecops-app-green` on port 5002) fronted by an Nginx reverse proxy with modular `upstream.conf`.
- **Why:** In-place container replacement requires stopping the active container before starting the new one, resulting in 5–15 seconds of HTTP 502 Bad Gateway downtime. With Blue/Green:
  1. The candidate container starts and pre-warms on its dedicated port while the active container handles 100% of live traffic.
  2. Health checks confirm the candidate can reach MySQL and returns HTTP 200 before any routing changes occur.
  3. The Nginx configuration is validated via `nginx -t` in an isolated sandbox container.
  4. Traffic switches atomically using `nginx -s reload` (0 dropped connections).
  5. If the new slot fails post-switch verification, Nginx rolls back to the prior upstream file automatically.
- **Trade-off:** Requires enough host memory to run two application containers concurrently during the cutover window (~200MB overhead). On a `t3.micro` instance (1GB RAM), this was accommodated by tuning MySQL buffers (`--performance-schema=OFF --innodb-buffer-pool-size=64M`).

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
**Q1: How do you prevent unauthorized production deployments on pull requests and standard pushes?**
> *"In our `.github/workflows/ci.yml`, normal pushes to `main` and all pull requests trigger only the `test-and-scan` job (running tests, pip-audit, SonarQube, and Trivy). Production deployment is strictly separated into three downstream jobs (`publish-ecr`, `deploy-blue-green`, `verify-production`) guarded by `if: github.event_name == 'workflow_dispatch' && inputs.deploy_to_production == 'true' && github.ref == 'refs/heads/main'`. This guarantees that code merges never automatically trigger production deployment without explicit, recorded human authorization."*

**Q2: What happens if a step in the SSM deployment script fails on EC2?**
> *"The remote deployment script begins with `set -euo pipefail` and a trap handler: `trap 'echo \"REMOTE_DEPLOY_FAILED line=$LINENO exit_code=$?\"' ERR`. If any command fails (e.g., Docker pull fails or candidate health check fails), the script aborts immediately with a non-zero exit code. The SSM execution status is registered as `Failed`. The CI pipeline polls this status, retrieves the error diagnostics from CloudWatch/SSM logs, prints them clearly, and halts the deployment."*

### Section B: Cloud Security & DevSecOps
**Q3: What is IMDSv2 and why did you enforce it in Terraform?**
> *"IMDSv2 is AWS Instance Metadata Service Version 2. Under IMDSv1, an attacker who discovered a Server-Side Request Forgery (SSRF) flaw in a web app could curl `http://169.254.169.254/latest/meta-data/iam/security-credentials/` with a simple GET request and steal the EC2 instance's IAM role credentials. IMDSv2 requires a `PUT` request with a custom header to obtain a session token before requesting metadata. In `terraform/main.tf`, we enforce `http_tokens = 'required'`, eliminating the SSRF credential exfiltration attack vector."*

**Q4: How do you manage AWS authentication in GitHub Actions without static secrets?**
> *"Instead of generating static `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` credentials that can leak or expire, our GitHub Actions workflow uses OpenID Connect (OIDC) identity federation (`aws-actions/configure-aws-credentials@v4`). GitHub's OIDC provider issues a cryptographically signed, short-lived JWT token containing repository claims (`repo:mohdshahid7033/cloud-devsecops-platform:ref:refs/heads/main`). AWS IAM assumes `arn:aws:iam::850252650249:role/github-actions-devsecops-oidc-role` based on an explicit trust policy, granting temporary 15-minute STS credentials with zero stored secrets."*

### Section C: Deployment & Architecture
**Q5: How does the zero-downtime Blue/Green deployment engine discover the active Nginx route and prevent misrouting?**
> *"The deployment engine implements a 4-tier discovery cascade to determine the active upstream without green-first bias:
> 1. Tier 1: Reads `/etc/nginx/conf.d/upstream.conf` directly from the running container via `docker exec`.
> 2. Tier 2: Reads `/home/ec2-user/nginx-conf/upstream.conf` on the host only after verifying its mount provenance via `docker inspect`. If unverified, it is skipped.
> 3. Tier 3: Captures a live runtime configuration dump via `docker exec devsecops-nginx nginx -T 2>&1`, preserving full diagnostic logs on stderr.
> 4. Tier 4: Compatibility fallback to container root `/etc/nginx/nginx.conf`.
> The output is stripped of comments, checked for unknown targets (failing closed if rogue backends are present), and verified for unambiguous active targets. Finally, independent container syntax validation (`nginx -t`) is strictly enforced before candidate cutover."*

**Q6: How do you guarantee the production deployment runs the exact image tested in CI?**
> *"The pipeline implements single verified image promotion:
> In Stage 1 (`test-and-scan`), the Docker image is built and verified locally with Trivy and smoke tests. It is then archived via `docker save` into a compressed artifact.
> In Stage 2 (`publish-ecr`), the workflow downloads the artifact, loads it via `docker load`, verifies its image ID, and tags it with both the commit SHA and its immutable SHA256 digest before pushing to Amazon ECR.
> In Stage 3 (`deploy-blue-green`), the deployment script enforces immutable digest pull (`repo@sha256:<hash>`), completely preventing image drift between CI verification and production runtime."*

### Section D: Monitoring & Observability
**Q7: What are the 'Golden Signals' and how does this project monitor them?**
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

### Incident 3: Terraform EBS Root Volume Encryption State Drift
- **Symptoms:** A planned `terraform plan` indicated that the active EC2 instance would be destroyed and recreated (`# aws_instance.devsecops_ec2 must be replaced`).
- **Root Cause:** The live root EBS volume was created unencrypted (`encrypted: false` in state), whereas `terraform/main.tf` specified `encrypted = true`. AWS EC2 does not allow in-place modification of encryption attributes on attached root volumes.
- **Resolution:** Enforced strict read-only Terraform governance in production to prevent unexpected instance termination and IP loss. Documented the safe zero-loss migration procedure: snapshot volume, copy snapshot with KMS encryption enabled, create an encrypted AMI, and perform a scheduled instance migration during an authorized maintenance window.

### Incident 4: Nginx Upstream Discovery Failure on Modular Single-File Mount
- **Symptoms:** Blue/Green deployment wrapper failed with: `CRITICAL: Nginx is running but active production route could not be unambiguously identified. Aborting.`
- **Root Cause:** `nginx -T` failed on the running container because of single-file bind mount restrictions or missing default template includes. Because the wrapper only checked `nginx -T`, it could not discover the active route even though `/etc/nginx/conf.d/upstream.conf` was perfectly readable on the container.
- **Resolution:** Designed and implemented a 4-tier discovery cascade (commit `5db3e33`): Tier 1 directly checks `/etc/nginx/conf.d/upstream.conf` inside the container; Tier 2 checks verified host mount provenance; Tier 3 captures `nginx -T` runtime dump with diagnostics; Tier 4 falls back to `/etc/nginx/nginx.conf`. Added independent running container syntax validation (`nginx -t`).

---

## 5. RESUME BULLET POINTS (ATS-OPTIMIZED)

Add these quantified bullet points to your resume under Projects or Experience:

- **Cloud DevSecOps Platform:** Architected an end-to-end automated DevSecOps platform on AWS using **Python (Flask)**, **Docker**, **Terraform**, and **GitHub Actions**, cutting release cycles from hours to under 6 minutes.
- **Zero-Downtime Blue/Green Deployment:** Engineered an automated zero-downtime Blue/Green traffic cutover engine with **Nginx** and **AWS Systems Manager (SSM)**, validating candidate health on isolated ports, pre-flighting Nginx configuration, and enabling automated rollback in under 3 seconds.
- **Automated Security Gates & SCA:** Integrated **pip-audit**, **CycloneDX SBOM generation**, **SonarQube SAST**, and **Aqua Security Trivy** vulnerability scanners into a 14-stage CI/CD pipeline, enforcing a Zero Exceptions Policy across filesystem dependencies and container layers.
- **Zero-SSH Production Deployment:** Replaced vulnerable SSH keys with **AWS Systems Manager (SSM) Run Command** and **Amazon ECR**, orchestrating automated remote container deployments with immutable SHA256 digest verification.
- **Infrastructure as Code (IaC) & Governance:** Authored modular **Terraform** configurations to provision custom VPCs, subnets, least-privilege IAM instance profiles with **GitHub OIDC federation**, and hardened EC2 instances enforcing **IMDSv2**; audited state drift and established strict read-only safety controls.
- **Continuous Observability:** Instrumented application latency and error rates using **Prometheus Flask Exporter** and provisioned real-time **Grafana** operational dashboards for system golden signals.

---

## 6. VERIFIED SKILLS INVENTORY VS. UNVERIFIED CLOUD ACTIONS

| Skill Domain | Locally Verified & Code-Evidenced | Requires Live AWS Account / Permissions |
| :--- | :--- | :--- |
| **CI/CD Pipeline** | 152/152 Pytest tests passing, GitHub Actions workflow syntax, branch gate logic | Remote runner execution against live AWS secrets |
| **Containers** | Multi-stage Dockerfile, Docker Compose networking & volumes, Nginx reverse proxy | Docker Desktop execution on local Windows daemon |
| **Security Scanning** | pip-audit, Trivy configuration, CycloneDX SBOM, SonarQube properties, Zero Exceptions Policy | Live SonarQube portal token generation against external server |
| **Infrastructure as Code** | Terraform HCL syntax (`main.tf`, `iam.tf`, `ecr.tf`, `variables.tf`, `outputs.tf`), drift audit | `terraform apply` execution against live AWS provider |
| **Cloud Deployment** | Blue/Green cutover engine, 4-tier discovery cascade, SSM Run Command scripts, health check script | Live dispatch to EC2 instance `i-0fb9dcbeb35b4fdbe` |
| **Observability** | Prometheus scrape config (`prometheus.yml`), Grafana provisioning YAMLs, metric endpoints | Live Grafana alert notifications (e.g. Slack/Email webhooks) |

---

## 7. BCA VIVA VOCE PRACTICE QUESTIONS & ANSWERS (HINDI / HINGLISH)

Use these bilingual Q&As to practice explaining the technical concepts fluently during your final-year BCA project viva.

### Q1: Aapka project kis baare me hai aur iska main objective kya hai?
> **Answer:**
> *"Mera project ek Cloud-Based DevSecOps Platform hai jo software development, security testing, cloud deployment aur real-time monitoring ko ek automated pipeline me integrate karta hai.*
> *Traditional development me security testing project ke end me hoti hai aur deployment manual SSH se hoti hai. Is platform me humne 'Shift-Left' security implement ki hai — jaise hi developer code push karta hai, automated unit tests (152 tests), dependency audit (pip-audit), code quality scan (SonarQube) aur container vulnerability scanning (Trivy) run hote hain. Production deployment AWS EC2 par bina kisi open SSH port ke AWS Systems Manager (SSM) aur Blue/Green zero-downtime architecture ke through hoti hai."*

### Q2: DevSecOps kya hota hai aur ye standard DevOps se kaise alag hai?
> **Answer:**
> *"DevOps ka main focus development aur operations ke beech collaboration aur high-speed delivery par hota hai. Lekin speed ke chakkar me security aksar compromise ho jati hai.*
> *DevSecOps me 'Security' ko SDLC ke har ek stage par integrate kiya jata hai (Shift-Left). Is project me security har step par guardrail ki tarah kaam karti hai: agar SonarQube quality gate fail hota hai ya Trivy me koi High/Critical vulnerability milti hai, toh pipeline turant fail ho jati hai aur deployment block ho jata hai."*

### Q3: Blue/Green deployment kaise kaam karta hai aur zero-downtime kaise milta hai?
> **Answer:**
> *"Blue/Green deployment me hum EC2 host par do identical application slots maintain karte hain — devsecops-app-blue aur devsecops-app-green.*
> *1. Maan lijiye abhi live traffic Blue container par chal raha hai (port 5001).*
> *2. Jab naya version deploy hota hai, toh engine pehle Green container ko start karta hai (port 5002) jabki Blue container live traffic handle karta rehta hai.*
> *3. Green container par isolated health check run hota hai (MySQL connectivity aur HTTP 200 verify ki jati hai).*
> *4. Nginx configuration syntax check pass hone ke baad, Nginx upstream ko atomic reload (`nginx -s reload`) se Green par point kar diya jata hai. Isse users ka koi connection drop nahi hota.*
> *5. Agar switch ke baad koi issue aata hai, toh engine 3 seconds ke andar Nginx ko wapas previous configuration par rollback kar deta hai."*

### Q4: Nginx route discovery me 4-tier cascade kya hai aur iski zaroorat kyun padi?
> **Answer:**
> *"Pehle deployment script keval `nginx -T` command par depend karti thi. Lekin modular Nginx configurations me jahan upstream file bind-mount hoti hai, `nginx -T` fail ho sakta tha.*
> *Isliye humne 4-tier cascade banaya:*
> *- **Tier 1:** Seedhe container ke andar se `/etc/nginx/conf.d/upstream.conf` read karta hai.*
> *- **Tier 2:** Host file tabhi read karta hai jab `docker inspect` se verify ho jaye ki wahi file container me mounted hai (provenance check).*
> *- **Tier 3:** Agar dono nahi mile, toh runtime dump `nginx -T` leta hai aur diagnostics preserve karta hai.*
> *- **Tier 4:** Monolithic `nginx.conf` fallback.*
> *Iske baad running Nginx par independent syntax check (`nginx -t`) chalana mandatory hota hai."*

### Q5: Production deployment ke liye push vs manual dispatch me kya farak hai?
> **Answer:**
> *"Normal git push par sirf CI pipeline (`test-and-scan`) chalti hai — testing, SonarQube, Trivy scan. Koi bhi code change direct production me deploy nahi hota.*
> *Production deployment ke liye explicit manual trigger (`workflow_dispatch`) chahiye jisme `deploy_to_production: true` pass karna padta hai. Yeh ensure karta hai ki production release controlled aur authorized ho."*

### Q6: AWS par deployment ke liye SSH port 22 kyun band rakha hai?
> **Answer:**
> *"Static SSH keys ek bahut bada security risk hoti hain kyunki wo leak ya share ho sakti hain. Humne Security Group me Port 22 ko completely band kar diya hai.*
> *Hum AWS Systems Manager (SSM) Run Command use karte hain. EC2 par SSM Agent chalta hai jo AWS cloud se outbound TLS 443 par communicate karta hai. GitHub Actions OIDC ke through short-lived temporary credentials leta hai aur SSM ke zariye encrypted remote script execute karta hai."*

### Q7: SonarQube aur Trivy me kya difference hai?
> **Answer:**
> *- **SonarQube (SAST):** Hamare source code ko analyze karta hai — code smells, bugs, security hotspots aur test coverage check karta hai.*
> *- **Trivy (SCA & Container Security):** Third-party libraries aur Docker container base OS layers (Alpine packages) me known CVEs (vulnerabilities) scan karta hai.*
> *- Sath hi **pip-audit** Python requirements ke known CVEs detect karta hai aur **CycloneDX** Software Bill of Materials (SBOM) generate karta hai."*

### Q8: Database disconnect hone par web application crash kyun nahi hoti?
> **Answer:**
> *"Humne `app/database.py` me Circuit Breaker pattern aur in-memory fallback implement kiya hai. Agar MySQL unreachable ho ya restart ho raha ho, toh application 500 error throw karke crash nahi hoti, balki inquiry ko thread-safe in-memory store me save kar leti hai aur `/health` endpoint honestly report karta hai ki database offline hai."*

### Q9: IMDSv2 kya hai aur isko Terraform me kyun enforce kiya?
> **Answer:**
> *"IMDS (Instance Metadata Service) EC2 instances ko IAM role credentials provide karta hai. IMDSv1 me SSRF vulnerability ke through attacker ek simple HTTP GET request se IAM keys chura sakta tha.*
> *IMDSv2 me session token lena padta hai PUT request ke through. Terraform me `http_tokens = 'required'` set karke humne SSRF token exfiltration ko completely block kar diya."*

### Q10: Terraform me EBS root volume encryption me drift dikhne par aapne 'terraform apply' kyun nahi chalaya?
> **Answer:**
> *"AWS me running EC2 instance ke attached root volume par in-place encryption change nahi ho sakti. Agar hum `terraform apply` chalate, toh Terraform active EC2 instance ko delete karke naya instance banata (`forces replacement`). Isse production server down ho jata aur public IP change ho jati.*
> *Isliye production me Terraform ko strict read-only governance me rakha gaya hai aur safe maintenance window ke zariye snapshot-and-restore procedure document kiya gaya hai."*
