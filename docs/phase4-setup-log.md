# Phase 4 — Prometheus + Grafana Observability

**Date:** 2026-05-01  
**Author:** Po-Fang Yang (Megan)  
**Goal:** Deploy full observability stack on k3d cluster, configure Prometheus scraping, build LLM monitoring dashboard

---

## ✅ Checklist

| Step | Status |
|------|--------|
| Helm v3.20.2 installed | ✅ |
| kube-prometheus-stack deployed | ✅ |
| Prometheus scraping llm metrics | ✅ |
| ServiceMonitor configured | ✅ |
| Grafana accessible (port 3000) | ✅ |
| Dashboard imported with 4 panels | ✅ |
| Request Rate panel | ✅ |
| Latency P50/P95/P99 panel | ✅ |
| Error Rate panel | ✅ |
| Pod Count / HPA panel | ✅ |

---

## Installation

```bash
# Install Helm
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version --short
# v3.20.2

# Add Prometheus community repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Create monitoring namespace
kubectl create namespace monitoring

# Install kube-prometheus-stack
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.adminPassword=admin123 \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
```

---

## All Pods Running

```
$ kubectl --namespace monitoring get pods
NAME                                                        READY   STATUS    RESTARTS   AGE
alertmanager-kube-prometheus-stack-alertmanager-0           2/2     Running   0          83s
kube-prometheus-stack-grafana-6d9f95c484-54hkt              3/3     Running   0          95s
kube-prometheus-stack-kube-state-metrics-864fbc65cf-sqldt   1/1     Running   0          95s
kube-prometheus-stack-operator-787d757cb-hxlt2              1/1     Running   0          95s
kube-prometheus-stack-prometheus-node-exporter-9s2r6        1/1     Running   0          95s
kube-prometheus-stack-prometheus-node-exporter-pf8gk        1/1     Running   0          95s
kube-prometheus-stack-prometheus-node-exporter-zcksf        1/1     Running   0          95s
prometheus-kube-prometheus-stack-prometheus-0               2/2     Running   0          83s
```

---

## monitoring/servicemonitor.yaml

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

---

## Prometheus Metrics Verified

```bash
$ curl -s http://localhost:9090/api/v1/label/__name__/values | python3 -m json.tool | grep llm
"llm_request_latency_seconds_bucket",
"llm_request_latency_seconds_count",
"llm_request_latency_seconds_sum",
"llm_requests_total",
"llm_tokens_generated_total",
```

---

## Access Commands

```bash
# Grafana (admin / admin123)
kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n monitoring

# Prometheus
kubectl port-forward svc/kube-prometheus-stack-prometheus 9090:9090 -n monitoring

# LLM Inference API
kubectl port-forward svc/llm-inference 8000:8000
```

---

## Dashboard Results (10 test requests)

| Metric | Value |
|--------|-------|
| Request Rate (peak) | 0.185 req/s |
| Latency P50 | 1.56s |
| Latency P95 | 23.1s |
| Latency P99 | 28.6s |
| Error Rate | 0% |
| Ready Pods | 2 |
| HPA Current | 2 |
| HPA Max | 6 |

---

## Key Design Decisions

- **serviceMonitorSelectorNilUsesHelmValues=false** — Allows Prometheus to discover ServiceMonitors outside the Helm release namespace
- **ServiceMonitor label `release: kube-prometheus-stack`** — Must match the Helm release name for Prometheus operator to pick it up
- **15s scrape interval** — Balances metric freshness vs Prometheus storage overhead
- **Dashboard JSON stored in repo** — Enables one-click dashboard restore; no manual panel recreation needed

---

## Data Flow

```
llm-inference Pod (/metrics)
    → ServiceMonitor (every 15s)
    → Prometheus (stores time-series)
    → Grafana (queries via PromQL)
    → Dashboard panels
```


