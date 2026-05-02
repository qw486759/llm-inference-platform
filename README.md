# LLM Inference Platform on Kubernetes

A production-style LLM inference platform built to explore serving, orchestration, and benchmarking as a systems engineering problem. The project covers containerization, Kubernetes deployment with HPA auto-scaling, Prometheus/Grafana observability, and load-tested architecture comparisons across three scaling strategies.

The core question driving the architecture work: **how should a Kubernetes-based LLM inference service be scaled, and what are the measurable trade-offs between deployment strategies?**

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Client / Locust                         │
└─────────────────────────┬────────────────────────────────────┘
                          │ POST /v1/chat/completions
┌─────────────────────────▼────────────────────────────────────┐
│             Kubernetes Service (ClusterIP:8000)               │
│  ┌──────────────────┐  ┌──────────────────┐                  │
│  │  FastAPI Pod 1   │  │  FastAPI Pod 2   │  ← HPA: 2–6 pods │
│  └────────┬─────────┘  └────────┬─────────┘                  │
│           └─────────────────────┘                            │
│                        /metrics                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │      ServiceMonitor → Prometheus → Grafana            │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
                          │
             ┌────────────▼────────────┐
             │   Ollama + Phi-3 Mini   │
             │   (WSL2, GTX 1650 GPU)  │
             └─────────────────────────┘
```

Each FastAPI pod forwards requests to an Ollama backend running on the host machine via `host.docker.internal`. Prometheus scrapes `/metrics` from each pod through a Kubernetes `ServiceMonitor`, and Grafana renders the collected time-series data.

---

## Tech Stack

| Layer | Tool | Notes |
|-------|------|-------|
| Model Serving | Ollama + Phi-3 Mini (2.2 GB) | GPU-accelerated via GTX 1650 Max-Q |
| Inference API | FastAPI + Python 3.11 | OpenAI-compatible `/v1/chat/completions` |
| Containerization | Docker (multi-stage build) | Slim runtime image |
| Orchestration | k3d (local Kubernetes) | k3s cluster running inside Docker |
| Auto-scaling | Kubernetes HPA (autoscaling/v2) | CPU-based scaling, min=2 / max=6 pods |
| Observability | Prometheus + Grafana | Latency histograms, request rate, error rate |
| Load Testing | Locust 2.43.4 | Headless concurrent-user simulation |
| Environment | WSL2 Ubuntu 24.04 + Windows 11 | NVIDIA Driver 596.36, CUDA 13.2 |

---

## Key Features

- OpenAI-compatible REST API with streaming and non-streaming response modes
- `/health` endpoint for Kubernetes readiness and liveness probes
- `/metrics` endpoint exposing Prometheus-format counters and histograms
- Multi-stage Dockerfile producing a minimal runtime image
- Kubernetes Deployment with CPU resource requests and limits
- Horizontal Pod Autoscaler targeting 70% average CPU utilization
- Grafana dashboard with request rate, P50/P95/P99 latency, error rate, and pod count panels
- Benchmark suite comparing three deployment strategies under concurrent load

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/qw486759/llm-inference-platform
cd llm-inference-platform

# 2. Build the Docker image
docker build -f docker/Dockerfile -t llm-inference:v1 .

# 3. Create a local k3d cluster and deploy
k3d cluster create llm-cluster --agents 2
k3d image import llm-inference:v1 -c llm-cluster
kubectl apply -f k8s/

# 4. Deploy the observability stack
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.adminPassword=admin123 \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
kubectl apply -f monitoring/servicemonitor.yaml

# 5. Access the services
kubectl port-forward svc/llm-inference 8000:8000
kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n monitoring
```

Grafana is available at `http://localhost:3000` (credentials: `admin` / `admin123`).  
Import `monitoring/grafana-dashboard.json` to load the pre-built dashboard.

---

## API Usage

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "phi3:mini",
    "messages": [{"role": "user", "content": "Explain Kubernetes HPA in one sentence."}],
    "stream": false
  }'
```

**Response:**
```json
{
  "id": "3b5a94ec",
  "object": "chat.completion",
  "model": "phi3:mini",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "..."},
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 45,
    "total_tokens": 65
  }
}
```

![K8s API Response](docs/images/k8s-api-response.png)

---

## Kubernetes Deployment

The service is deployed as a Kubernetes `Deployment` with two initial replicas, a `ClusterIP` Service, and a `HorizontalPodAutoscaler`. Resource limits (`500m` CPU, `512Mi` memory) are set per pod to prevent resource contention in the local cluster.

```bash
kubectl apply -f k8s/
kubectl get pods
kubectl get hpa
```

![K8s Deployment and HPA](docs/images/k8s-deploy-hpa.png)

---

## Observability

Prometheus scrapes `/metrics` from each pod every 15 seconds via a `ServiceMonitor` resource. The Grafana dashboard tracks four panels:

| Panel | Metric |
|-------|--------|
| Request Rate | `rate(llm_requests_total[1m])` |
| Latency Histogram | P50, P95, P99 via `histogram_quantile` |
| Error Rate | Error requests as a fraction of total |
| Pod Count | HPA current and maximum replica counts |

![Grafana Dashboard](docs/images/grafana-benchmark.png)

---

## Benchmark

### Methodology

Three deployment strategies were benchmarked under identical workload conditions to measure the trade-offs between reliability, latency, throughput, and resource usage.

| Parameter | Value |
|-----------|-------|
| Tool | Locust 2.43.4 |
| Concurrent users | 10 |
| Ramp rate | 2 users/sec |
| Duration | 60 seconds |
| Prompt | Fixed ~50-token prompt (HPA explanation) |
| Max tokens | 50 |

**Scenarios:**
- **A — Single pod:** 1 replica, HPA disabled
- **B — HPA dynamic:** min=2, max=6 pods, CPU target=70%
- **C — Pre-scaled:** 4 static replicas, HPA disabled

### Results

| Strategy | Pods | Failure Rate | P50 | P95 | Throughput |
|----------|:----:|:---:|:---:|:---:|:---:|
| A: Single pod | 1 | **45.5%** ❌ | 15s | 35s | 0.37 req/s |
| B: HPA dynamic | 2→6 | **0%** ✅ | 26s | 28s | 0.34 req/s |
| C: Pre-scaled | 4 | **0%** ✅ | 22s | **24s** | **0.40 req/s** |

**Scenario A — Single pod**

![Locust Scenario A Setup](docs/images/locust-scenario-a-start.png)
![Locust Scenario A Result](docs/images/locust-scenario-a.png)

**Scenario B — HPA dynamic scaling**

![Locust Scenario B Setup](docs/images/locust-scenario-b-start.png)
![Locust Scenario B Result](docs/images/locust-scenario-b.png)

**Scenario C — Pre-scaled static fleet**

![Locust Scenario C Setup](docs/images/locust-scenario-c-start.png)
![Locust Scenario C Result](docs/images/locust-scenario-c.png)

### Interpretation

Single-pod deployment fails under modest load due to Ollama's serial request queue overflowing (HTTP 502). Both multi-pod configurations eliminate failures. Pre-scaling achieves the lowest P95 latency (24s) because pods are already warm when requests arrive. HPA dynamic scaling introduces a 30–60 second scale-up lag, temporarily increasing latency during the ramp-up window.

### Limitations

These results should be interpreted within the constraints of the test environment:

- **Local k3d cluster** running inside Docker on a single Windows host — not representative of a multi-node cloud deployment
- **GTX 1650 Max-Q (4GB VRAM)** — a consumer-grade GPU; inference throughput and latency would differ significantly on production hardware (e.g., NVIDIA A10G)
- **10 concurrent users** — a small-scale workload; behavior at 50–500 users is not captured
- **CPU-based HPA** — LLM inference load is not well-reflected by CPU utilization, which may delay or suppress appropriate scaling responses

---

## Architecture Decision Record

A full ADR is available at [`docs/adr-inference-strategy.md`](docs/adr-inference-strategy.md). Key decisions are summarized below.

| Decision | Rationale |
|----------|-----------|
| FastAPI as inference layer | Async support for concurrent requests; straightforward OpenAI-schema compatibility; built-in Prometheus integration via `prometheus-client` |
| Docker multi-stage build | Separates dependency installation from the runtime image, reducing final image size and attack surface |
| Kubernetes + HPA | Enables declarative replica management and reactive scaling; separates infrastructure concerns from application code |
| CPU-based HPA at 70% | A practical threshold given the local resource constraints; KEDA with request queue depth would be more accurate for LLM workloads |
| Prometheus + Grafana | Standard observability stack for Kubernetes; ServiceMonitor enables automatic scrape target discovery without modifying application configuration |
| Benchmark: three strategies | Isolates the effect of pod count and scaling behavior on reliability and latency; provides data to justify a deployment recommendation |

**Recommendation:** HPA dynamic scaling (Scenario B) for variable-traffic workloads. Pre-scaling (Scenario C) is preferred when latency is the primary constraint and traffic is predictable.

---

## Repo Structure

```
llm-inference-platform/
├── app/
│   ├── main.py                    # FastAPI inference wrapper
│   └── requirements.txt
├── docker/
│   └── Dockerfile                 # Multi-stage build
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── hpa.yaml
├── monitoring/
│   ├── servicemonitor.yaml
│   └── grafana-dashboard.json
├── benchmark/
│   ├── locustfile.py
│   └── results/                   # Locust CSV outputs (A / B / C)
├── docs/
│   ├── adr-inference-strategy.md
│   ├── phase1-setup-log.md
│   ├── phase2-setup-log.md
│   ├── phase3-setup-log.md
│   ├── phase4-setup-log.md
│   ├── phase5-benchmark-log.md
│   └── images/
└── README.md
```

---

## Environment

| Component | Version |
|-----------|---------|
| OS | Windows 10 + WSL2 Ubuntu 24.04 |
| GPU | NVIDIA GTX 1650 Max-Q (4GB VRAM) |
| NVIDIA Driver | 596.36 |
| CUDA | 13.2 |
| Docker | 29.4.1 |
| k3d | v5.8.3 |
| kubectl | v1.36.0 |
| Helm | v3.20.2 |
| Ollama | 0.22.1 |
| Python | 3.11 (container) / 3.12 (WSL2) |
