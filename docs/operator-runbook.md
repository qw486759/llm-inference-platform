# Operator Runbook — LLM Inference Platform

This runbook is intended for infrastructure engineers and solutions architects inheriting
or operating this platform. It covers day-2 operations: reading the Grafana dashboard,
interpreting benchmark results, evaluating model and runtime changes, GPU bottleneck
diagnosis, HPA tuning, and the migration path from Ollama to production-grade runtimes.

---

## Table of Contents

1. [Reading the Grafana Dashboard](#1-reading-the-grafana-dashboard)
2. [Interpreting Benchmark CSVs](#2-interpreting-benchmark-csvs)
3. [Model and Runtime Evaluation](#3-model-and-runtime-evaluation)
4. [Migration Path: Ollama → vLLM → Triton](#4-migration-path-ollama--vllm--triton)
5. [GPU Bottleneck Checklist](#5-gpu-bottleneck-checklist)
6. [HPA Tuning Reference](#6-hpa-tuning-reference)
7. [Deploying Alert Rules](#7-deploying-alert-rules)

---

## 1. Reading the Grafana Dashboard

Import `monitoring/grafana-dashboard.json` into Grafana to load the pre-built dashboard.
The dashboard exposes five panels covering gateway health and GPU inference throughput.

### Panel Reference

| Panel | Metric Query | What It Tells You |
|-------|-------------|-------------------|
| Request Rate | `rate(llm_requests_total[1m])` | Incoming request volume per second across all gateway pods |
| Latency Histogram | `histogram_quantile(0.95, ...)` | P50/P95/P99 end-to-end latency including gateway + GPU queue time |
| Error Rate | `sum(rate(llm_requests_total{status="error"}[1m])) / sum(rate(llm_requests_total[1m]))` | Fraction of requests returning errors; spike indicates backend or gateway failure |
| Pod Count | HPA current / max replicas via kube-state-metrics | Gateway replica count; plateauing at max signals scaling ceiling |
| Tokens/sec | `rate(llm_tokens_per_second_sum[1m]) / rate(llm_tokens_per_second_count[1m])` | Average GPU inference throughput derived from Ollama `eval_duration`; isolates accelerator speed from network overhead |

### Operational Signals

**Latency rising, error rate stable, tokens/sec flat:**
Gateway pods are queuing behind the GPU backend. Adding more pods will not reduce
latency — the bottleneck is the shared GPU runtime, not the API layer.

**Error rate spiking (HTTP 502):**
Ollama's serial request queue is overflowing. Immediate actions:
```bash
# Check gateway pod logs
kubectl logs -l app=llm-inference --tail=50

# Check Ollama is reachable from a gateway pod
kubectl exec -it <pod-name> -- curl -s http://host.docker.internal:11434/api/tags
```

**Tokens/sec dropping without load increase:**
GPU thermal throttling or VRAM pressure. Check with:
```bash
nvidia-smi dmon -s u
```

**Pod Count plateauing at HPA max with latency still high:**
Gateway scaling ceiling reached. See [GPU Bottleneck Checklist](#5-gpu-bottleneck-checklist)
and [Migration Path](#4-migration-path-ollama--vllm--triton).

---

## 2. Interpreting Benchmark CSVs

Locust exports results to `benchmark/results/`. The primary file is `*_stats.csv`.

### Key Columns

| Column | Meaning |
|--------|---------|
| `Name` | Endpoint path (e.g. `/v1/chat/completions`) |
| `Request Count` | Total requests sent during the run |
| `Failure Count` | Requests that returned non-2xx or timed out |
| `Median Response Time` | P50 latency in milliseconds |
| `95%ile Response Time` | P95 latency in milliseconds — primary SLO signal |
| `Average Response Time` | Mean latency; skewed by outliers, use P95 instead |
| `Requests/s` | Throughput at steady state |

### Reading Degradation

Compare P95 across scenarios. The documented baselines on GTX 1650 Max-Q under
10 concurrent users are:

| Scenario | P95 | Failure Rate | Throughput |
|----------|-----|-------------|-----------|
| A: Single pod | 35s | 45.5% | 0.37 req/s |
| B: HPA dynamic | 28s | 0% | 0.34 req/s |
| C: Pre-scaled 4 pods | 24s | 0% | 0.40 req/s |

A near-flat throughput curve between Scenario B and C (0.34 → 0.40 req/s despite
doubling pod count) is the primary signal that the bottleneck is the shared GPU
backend, not the gateway layer.

### What Degradation Looks Like

- P95 exceeds 30s → outside normal operating envelope; check GPU utilization
- Failure rate > 0% under 10 users → gateway or backend instability; check pod logs
- Throughput drops between runs with identical load → resource contention or thermal throttling

---

## 3. Model and Runtime Evaluation

Before swapping models or runtimes, evaluate the impact across four dimensions:
VRAM budget, throughput, concurrency behavior, and operational complexity.

### VRAM Budget Analysis

| Model | Approx. VRAM | Fits GTX 1650 Max-Q (4GB) |
|-------|-------------|--------------------------|
| Phi-3 Mini (2.2 GB) | ~2.5 GB with runtime overhead | Yes |
| Llama 3 8B (Q4) | ~5 GB | No — exceeds 4GB VRAM |
| Llama 3 8B (Q2) | ~3.5 GB | Marginal — risk of OOM under load |
| Mistral 7B (Q4) | ~5 GB | No |

Exceeding VRAM causes Ollama to fall back to CPU offload, which significantly
increases latency. Always verify with `nvidia-smi` after model load.

### Throughput Impact

Larger models generate fewer tokens/sec on fixed hardware. Use the Tokens/sec Grafana panel,
calculated from `llm_tokens_per_second_sum` and `llm_tokens_per_second_count`, to measure
the impact after any model change. A drop in tokens/sec without a change in load indicates
the new model is more GPU-constrained.

### Concurrency Behavior

Ollama serializes requests — only one inference runs on the GPU at a time regardless
of how many gateway pods are running. This means:

- Switching models does not change concurrency behavior under Ollama
- Throughput ceiling is set by single-request GPU execution time
- True concurrent inference requires a batching-capable runtime (vLLM, Triton)

### When Ollama Ceiling Is Reached

Indicators that Ollama is the limiting factor:

- Tokens/sec is stable but P95 latency grows linearly with concurrent users
- Adding gateway pods does not improve throughput (as seen in Scenario B vs C)
- `nvidia-smi` shows GPU utilization near 100% with requests queuing in gateway logs

At this point, evaluate the migration path in the next section.

---

## 4. Migration Path: Ollama → vLLM → Triton

### Decision Criteria

| Current State | Recommended Next Step |
|--------------|----------------------|
| Ollama, < 5 concurrent users, latency acceptable | Stay on Ollama |
| Ollama, > 5 concurrent users, P95 growing linearly | Evaluate vLLM |
| vLLM, need multi-model serving or ensemble pipelines | Evaluate Triton |
| Need NVIDIA-optimized serving, TensorRT-LLM backend, or multi-model production serving | Evaluate Triton + TensorRT-LLM |

### Ollama → vLLM

vLLM introduces continuous batching, which processes multiple requests concurrently
on the GPU rather than serializing them. This is the primary capability gap between
Ollama and a production inference runtime.

Key changes required:
- Replace `http://localhost:11434/api/chat` backend URL in `app/main.py` with vLLM endpoint
- vLLM exposes an OpenAI-compatible API at `/v1/chat/completions` — FastAPI gateway
  requires minimal changes
- GPU node with NVIDIA Device Plugin required for Kubernetes deployment;
  see `k8s/gpu-deployment.example.yaml` for the reference manifest
- VRAM requirement may increase depending on model size, dtype, and quantization settings; validate with `nvidia-smi` before comparing throughput

### vLLM → Triton

Triton Inference Server adds multi-model serving, ensemble pipelines, and
TensorRT-LLM backend support for NVIDIA-optimized throughput on supported hardware.

Appropriate when:
- Serving multiple models from the same GPU node
- Requiring dynamic batching with configurable batch size and timeout
- Targeting A100/H100 class hardware with TensorRT optimization

Reference: [NVIDIA Triton Inference Server](https://developer.nvidia.com/triton-inference-server)

---

## 5. GPU Bottleneck Checklist

Use this checklist when latency is high or throughput is not improving with additional pods.

### Step 1: Confirm GPU is being used

```bash
nvidia-smi
```

Look for Ollama process in the `Processes` section consuming GPU memory.
If absent, Ollama is running in CPU mode — check CUDA installation and driver version.

### Step 2: Check VRAM utilization

```bash
nvidia-smi --query-gpu=memory.used,memory.free,memory.total --format=csv
```

If `memory.free` is near zero during inference, VRAM is saturated. The model may
be partially offloaded to CPU, increasing latency significantly.

### Step 3: Check GPU compute utilization

```bash
nvidia-smi dmon -s u -d 1
```

Sustained GPU utilization near 100% during inference confirms the accelerator is
the throughput ceiling. Adding gateway pods will not help — this is a hardware constraint.

### Step 4: Distinguish gateway bottleneck from GPU bottleneck

| Symptom | Gateway bottleneck | GPU bottleneck |
|---------|-------------------|----------------|
| Error rate high (502s) | ✅ | ❌ |
| Tokens/sec flat as pods increase | ❌ | ✅ |
| GPU utilization < 50% under load | ✅ | ❌ |
| P95 grows linearly with users | ❌ | ✅ |

Gateway bottleneck → scale pods or increase resource limits.
GPU bottleneck → evaluate vLLM/Triton or upgrade hardware.

### Step 5: Check for thermal throttling

```bash
nvidia-smi --query-gpu=temperature.gpu,clocks_throttle_reasons.sw_thermal_slowdown --format=csv
```

On laptop GPUs (GTX 1650 Max-Q), sustained inference workloads can trigger thermal
throttling, reducing clock speed and tokens/sec over time.

---

## 6. HPA Tuning Reference

The current HPA targets 70% average CPU utilization across gateway pods. This is a
practical threshold for the local environment but has known limitations for LLM workloads.

### Adjusting the CPU Threshold

```bash
kubectl edit hpa llm-inference-hpa
```

Or update `k8s/hpa.yaml` and reapply:

```yaml
metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 60  # Lower = more aggressive scaling
```

Lower threshold → pods scale up earlier, reducing queue pressure at the cost of
higher idle resource usage.

### Limitations of CPU-Based HPA for LLM Workloads

LLM inference is GPU-bound, not CPU-bound. Gateway pods may show low CPU utilization
even when the inference queue is deep, because pods spend most of their time waiting
for the GPU backend to respond. This means HPA may not scale up in time to prevent
latency spikes.

### More Accurate Scaling Signal: KEDA

[KEDA](https://keda.sh) (Kubernetes Event-Driven Autoscaler) can scale on custom
Prometheus metrics — for example, request queue depth or `llm_tokens_per_second`.
This would allow HPA-equivalent scaling behavior driven by inference-specific signals
rather than CPU utilization.

Example KEDA ScaledObject targeting request rate:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: llm-inference-scaledobject
spec:
  scaleTargetRef:
    name: llm-inference
  minReplicaCount: 2
  maxReplicaCount: 6
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://kube-prometheus-stack-prometheus.monitoring:9090
        metricName: llm_request_rate
        threshold: "5"
        query: sum(rate(llm_requests_total[1m]))
```

Note: KEDA is not deployed in this project. This is provided as a reference for
production scaling improvement.

---

## 7. Deploying Alert Rules

`monitoring/inference-alerts.yml` defines Prometheus alerting rules in native
rule-group format. It is not directly applicable with `kubectl apply` — it must
be wrapped in a `PrometheusRule` custom resource to be recognized by kube-prometheus-stack.

### Wrapping in a PrometheusRule CRD

Create `monitoring/prometheusrule.yaml`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: llm-inference-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack  # Must match Helm release name
spec:
  groups:
    - name: llm_inference_alerts
      rules:
        # Paste the contents of the `rules:` block from inference-alerts.yml here
```

Apply to the monitoring namespace:

```bash
kubectl apply -f monitoring/prometheusrule.yaml
```

Verify the rule is loaded:

```bash
kubectl get prometheusrule -n monitoring
```

Open `http://localhost:9090/alerts` to confirm alert rules appear in the Prometheus UI.

### Label Requirement

The `release: kube-prometheus-stack` label must match your Helm release name.
If you installed with a different release name, update the label accordingly:

```bash
helm list -n monitoring  # Check release name
```
