# Phase 3 — Kubernetes Deployment + HPA

This phase deploys the inference service to a local k3d Kubernetes cluster and configures a Horizontal Pod Autoscaler. The aim is to validate that the containerized service runs correctly under Kubernetes and that the HPA can observe CPU utilization and report scaling targets.

---

## Checklist

| Step | Status |
|------|--------|
| kubectl v1.36.0 installed | ✅ |
| k3d v5.8.3 installed | ✅ |
| k3d cluster created (1 server, 2 agents) | ✅ |
| Docker image imported into k3d | ✅ |
| `deployment.yaml` applied (2 replicas) | ✅ |
| `service.yaml` applied (ClusterIP:8000) | ✅ |
| `hpa.yaml` applied (min=2, max=6, CPU=70%) | ✅ |
| Pods Running | ✅ |
| HPA CPU metrics reading (3%/70%) | ✅ |
| Inference API responding via port-forward | ✅ |

---

## Cluster Setup

```bash
k3d cluster create llm-cluster --agents 2
k3d image import llm-inference:v1 -c llm-cluster
kubectl apply -f k8s/
```

```
$ kubectl get nodes
NAME                       STATUS   ROLES                  VERSION
k3d-llm-cluster-agent-0    Ready    <none>                 v1.31.5+k3s1
k3d-llm-cluster-agent-1    Ready    <none>                 v1.31.5+k3s1
k3d-llm-cluster-server-0   Ready    control-plane,master   v1.31.5+k3s1
```

---

## Kubernetes Manifests

**deployment.yaml**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-inference
spec:
  replicas: 2
  selector:
    matchLabels:
      app: llm-inference
  template:
    metadata:
      labels:
        app: llm-inference
    spec:
      containers:
      - name: llm-inference
        image: llm-inference:v1
        imagePullPolicy: Never
        ports:
        - containerPort: 8000
        resources:
          requests:
            cpu: "250m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 15
          periodSeconds: 20
```

**hpa.yaml**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: llm-inference-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: llm-inference
  minReplicas: 2
  maxReplicas: 6
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

---

## Verification

```
$ kubectl get pods
NAME                             READY   STATUS    RESTARTS   AGE
llm-inference-65dcb95487-2wplc   1/1     Running   0          3m11s
llm-inference-65dcb95487-sdjlz   1/1     Running   0          3m11s

$ kubectl get hpa
NAME                REFERENCE                  TARGETS       MINPODS   MAXPODS   REPLICAS
llm-inference-hpa   Deployment/llm-inference   cpu: 3%/70%   2         6         2
```

---

## Design Notes

- **`imagePullPolicy: Never`** — Required for k3d; tells Kubernetes to use the locally imported image rather than attempting a remote pull
- **Resource requests vs limits** — `requests` influence scheduling decisions; `limits` cap per-pod consumption and prevent one pod from crowding out others
- **readinessProbe + livenessProbe** — Kubernetes withholds traffic from pods that have not yet passed the readiness check, and restarts pods that fail the liveness check
- **HPA autoscaling/v2** — The v2 API supports multiple metric sources and more expressive scaling behavior than the deprecated v1 API