import os
import json
import urllib.request

def load_env():
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                if line.strip() and not line.startswith("#") and "=" in line:
                    key, val = line.strip().split("=", 1)
                    os.environ[key.strip()] = val.strip().strip("'").strip('"')

def test_github():
    load_env()
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    print("Token length:", len(token))
    
    repo = "mohdshahid7033/cloud-devsecops-platform"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "DevSecOps-Platform"
    }

    try:
        url_runs = f"https://api.github.com/repos/{repo}/actions/runs?per_page=1"
        req_runs = urllib.request.Request(url_runs, headers=headers)
        with urllib.request.urlopen(req_runs, timeout=10) as resp:
            runs_data = json.loads(resp.read().decode())
        
        runs = runs_data.get("workflow_runs", [])
        if not runs:
            print("No runs found")
            return
        
        latest_run = runs[0]
        run_id = latest_run.get("id")
        print("Run ID:", run_id)
        print("Run Status:", latest_run.get("status"))
        print("Run Conclusion:", latest_run.get("conclusion"))

        url_jobs = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
        req_jobs = urllib.request.Request(url_jobs, headers=headers)
        with urllib.request.urlopen(req_jobs, timeout=10) as resp:
            jobs_data = json.loads(resp.read().decode())
        
        jobs = jobs_data.get("jobs", [])
        if not jobs:
            print("No jobs found")
            return
        
        test_job = jobs[0]
        for step in test_job.get("steps", []):
            print(f"- {step.get('name')}: {step.get('status')} / {step.get('conclusion')} ({step.get('started_at')} to {step.get('completed_at')})")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_github()
