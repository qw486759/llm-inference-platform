# Phase 4 — Prometheus + Grafana Observability

This phase deploys a full observability stack using the `kube-prometheus-stack` Helm chart, configures Prometheus to scrape the inference service's `/metrics` endpoint, and builds a Grafana dashboard to visualize request rate, latency distribution, error rate, and pod scaling behavior.

---

## Checklist

| Step | Status |
|------|--------|
| Helm v3.20.2 installed | ✅ |
| kube-prometheus-stack deployed | ✅ |
| Prometheus scraping LLM metrics | ✅ |
| ServiceMonitor configured | ✅ |
| Grafana accessible (port 3000) | ✅ |
| Dashboard imported with 4 panels | ✅ |

---

## Installation

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.adminPassword=admin123 \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
kubectl apply -f monitoring/servicemonitor.yaml
```

---

## ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: llm-inference
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  namespaceSelector:
    matchNames:
    - default
  selector:
    matchLabels:
      app: llm-inference
  endpoints:
  - port: http
    path: /metrics
    interval: 15s
```

The `release: kube-prometheus-stack` label is required — the Prometheus Operator uses this label to determine which ServiceMonitors to include in its scrape configuration. Without it, the monitor is silently ignored.

---

## Prometheus Metrics Confirmed

```bash
$ curl -s http://localhost:9090/api/v1/label/__name__/values | python3 -m json.tool | grep llm
"llm_request_latency_seconds_bucket",
"llm_request_latency_seconds_count",
"llm_request_latency_seconds_sum",
"llm_requests_total",
"llm_tokens_generated_total",
```

---

## Dashboard Panels

| Panel | PromQL |
|-------|--------|
| Request Rate | `rate(llm_requests_total[1m])` |
| Latency P50/P95/P99 | `histogram_quantile(0.95, rate(llm_request_latency_seconds_bucket[5m]))` |
| Error Rate | Error requests / total requests |
| Pod Count | `kube_deployment_status_replicas_ready` + HPA current/max |

Import `monitoring/grafana-dashboard.json` into Grafana to restore all panels.

---

## Initial Results (10 test requests)

| Metric | Value |
|--------|-------|
| Request Rate (peak) | 0.185 req/s |
| Latency P50 | 1.56s |
| Latency P95 | 23.1s |
| Latency P99 | 28.6s |
| Error Rate | 0% |
| Ready Pods | 2 |

---

## Data Flow

```
FastAPI pod (/metrics)
  → ServiceMonitor (scrape every 15s)
  → Prometheus (time-series storage)
  → Grafana (PromQL queries)
  → Dashboard panels
```