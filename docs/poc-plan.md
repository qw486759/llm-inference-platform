# POC Validation Runbook — LLM Inference Platform

This runbook provides a structured validation procedure for deploying and verifying
the LLM inference platform in a new environment. It covers environment prerequisites,
deployment phases, observability validation, and load testing — with explicit success
criteria at each stage.

> **Scope:** Local k3d cluster on a single host with a consumer-grade NVIDIA GPU.
> Results are not representative of a production multi-node deployment.
> See [Limitations](#limitations) before interpreting results.

---

## Prerequisites

### Hardware Minimums

| Component | Minimum | Notes |
|-----------|---------|-------|
| GPU VRAM | 4 GB | Phi-3 Mini requires ~2.2 GB; headroom needed for CUDA runtime |
| System RAM | 16 GB | k3d + Docker + Ollama running concurrently |
| Disk | 10 GB free | Model weights (~2.2 GB) + Docker images + k3d volumes |

### Software Stack

| Component | Version Used | Notes |
|-----------|-------------|-------|
| OS | WSL2 Ubuntu 24.04 / Windows 11 | Linux host also supported |
| NVIDIA Driver | 596.36+ | Must support CUDA 12.x or later |
| CUDA | 12.x / 13.x | Verify with `nvidia-smi` inside WSL2 |
| Docker Desktop | 29.x | WSL2 integration must be enabled |
| k3d | v5.8+ | Runs k3s inside Docker |
| kubectl | v1.30+ | Must match k3s server version |
| Helm | v3.10+ | Required for kube-prometheus-stack |
| Ollama | 0.22+ | GPU offload enabled by default on NVIDIA hardware |
| jq | 1.6+ | Optional; used to inspect JSON responses in Phase 1 |
| Python | 3.11+ | For Locust load testing |

### Pre-flight Checks

Run these before starting. All must pass before proceeding.

```bash
# GPU accessible in WSL2
nvidia-smi

# Docker running
docker info

# kubectl available
kubectl version --client

# Helm available
helm version
```

---

## Phase 1: Environment Validation

**Goal:** Confirm GPU, Docker, and Ollama are working correctly before any Kubernetes work.

```bash
# Start Ollama if it is not already running
# If Ollama is already running as a background service, skip ollama serve &
ollama serve &
ollama pull phi3:mini

# Verify model responds
curl -s http://localhost:11434/api/generate \
  -d '{"model": "phi3:mini", "prompt": "ping", "stream": false}' \
  | jq .response
```

**Expected:** Non-empty response string. During inference, `nvidia-smi` should show Ollama consuming GPU memory.

```bash
# Confirm GPU memory is being used by Ollama during inference
nvidia-smi
```

**Pass criteria:** Response received, and `nvidia-smi` shows Ollama consuming GPU memory during inference.

---

## Phase 2: Service Deployment

**Goal:** Deploy the inference gateway on k3d and confirm pods are healthy.

```bash
# Create cluster
k3d cluster create llm-cluster --agents 2

# Build and load image
docker build -f docker/Dockerfile -t llm-inference:v2 .
k3d image import llm-inference:v2 -c llm-cluster

# Apply Kubernetes manifests
kubectl apply -f k8s/

# Verify pods and HPA
kubectl get pods -w
# Press Ctrl+C after pods show Running status
kubectl get hpa
```

**Expected pod state:** Two `llm-inference` pods reach `Running` status within 60 seconds.

**Expected HPA state:**
```
NAME               REFERENCE             TARGETS   MINPODS   MAXPODS   REPLICAS
llm-inference-hpa  Deployment/llm-inference  <30%/70%  2         6         2
```

```bash
# Confirm API is reachable
kubectl port-forward svc/llm-inference 8000:8000 &

curl -s http://localhost:8000/health
curl -s http://localhost:8000/metrics | grep llm_requests_total
```

**Pass criteria:** `/health` returns `200`, `/metrics` exposes `llm_requests_total` counter.

---

## Phase 3: Observability Validation

**Goal:** Confirm Prometheus is scraping the inference service and Grafana dashboard is populated.

```bash
# Deploy kube-prometheus-stack
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.adminPassword=admin123 \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false

# Apply ServiceMonitor
kubectl apply -f monitoring/servicemonitor.yaml

# Verify scrape target is active (allow 60s for Prometheus to discover)
kubectl port-forward svc/kube-prometheus-stack-prometheus 9090:9090 -n monitoring &
```

Open `http://localhost:9090/targets` and confirm `llm-inference` appears as `UP`.

```bash
# Access Grafana
kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n monitoring &
```

Open `http://localhost:3000` (admin / admin123), import `monitoring/grafana-dashboard.json`.

**Pass criteria:** All five dashboard panels populated — Request Rate, Latency Histogram,
Error Rate, Pod Count, Tokens/sec.

> **Alerting rules note:** `monitoring/inference-alerts.yml` is provided as a Prometheus
> rule template. In kube-prometheus-stack, it can be wrapped in a `PrometheusRule`
> custom resource or loaded through Prometheus rule configuration.
> See [`docs/operator-runbook.md`](operator-runbook.md) for the wrapping procedure.

---

## Phase 4: Load Validation

**Goal:** Run the Locust benchmark and confirm results fall within expected ranges.

```bash
# Install Locust
pip install locust

# Run benchmark (Scenario B — HPA dynamic, default configuration)
locust -f benchmark/locustfile.py \
  --headless \
  --host http://localhost:8000 \
  -u 10 -r 2 -t 60s \
  --csv benchmark/results/poc-validation
```

**Expected output files:**
- `benchmark/results/poc-validation_stats.csv`
- `benchmark/results/poc-validation_failures.csv`

---

## Cleanup

Stop background port-forward processes when validation is complete:

```bash
pkill -f "kubectl port-forward"
```

To tear down the cluster entirely:

```bash
k3d cluster delete llm-cluster
```

---

## Success Criteria

> These thresholds are calibrated for the local k3d + GTX 1650 Max-Q test environment
> and should not be interpreted as production SLOs.

| Check | Pass Condition | Notes |
|-------|---------------|-------|
| GPU offload | `nvidia-smi` shows Ollama consuming GPU memory during inference | CPU-only inference will be significantly slower |
| Pod readiness | 2 pods Running within 60s | Check image pull and resource limits if delayed |
| HPA visible | `kubectl get hpa` shows target CPU % | Requires Kubernetes Metrics API / metrics-server |
| Prometheus scrape | llm-inference target shows `UP` | Allow 60s after ServiceMonitor apply |
| Grafana panels | All 5 panels populated with data | Send at least 5 requests before checking |
| P95 latency | < 30s under 10 concurrent users | Local baseline: Scenario B 28s, Scenario C 24s on GTX 1650 Max-Q |
| Failure rate | 0% under 10 concurrent users | Scenario A single-pod failure rate was 45.5% — confirms multi-pod value |
| HPA scale-up | Pods increase under sustained load | Scale-up lag is 30–60s; pre-scaling eliminates this |

---

## Limitations

| Constraint | Impact |
|-----------|--------|
| Single-node k3d cluster | No real pod scheduling distribution; all pods share one host |
| GTX 1650 Max-Q (4GB VRAM) | ~20 tokens/sec; A10G/A100 would yield substantially lower latency |
| Ollama single-request serialization | All gateway pods queue behind one GPU runtime; true concurrency requires vLLM or Triton |
| CPU-based HPA | LLM inference load is not well-reflected by CPU; KEDA with queue depth would be more accurate |
| 10 concurrent users | Small-scale workload; 50–500 user behavior is not validated here |
| Local Docker networking | Port-forwarding latency adds overhead not present in cluster-internal deployments |
