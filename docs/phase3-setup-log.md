# Phase 3 — Kubernetes Deployment + HPA

**Date:** 2026-05-01  
**Author:** Po-Fang Yang (Megan)  
**Goal:** Deploy llm-inference:v1 on local k3d Kubernetes cluster with Horizontal Pod Autoscaler

---

## ✅ Checklist

| Step | Status |
|------|--------|
| kubectl v1.36.0 installed | ✅ |
| k3d v5.8.3 installed | ✅ |
| k3d cluster created (1 server + 2 agents) | ✅ |
| Docker image imported into k3d | ✅ |
| `deployment.yaml` applied (2 replicas) | ✅ |
| `service.yaml` applied (ClusterIP:8000) | ✅ |
| `hpa.yaml` applied (min=2, max=6, 70% CPU) | ✅ |
| Pods Running | ✅ |
| HPA CPU metrics reading (3%/70%) | ✅ |
| Inference API responding via port-forward | ✅ |

---

## Cluster Info

```
$ kubectl get nodes
NAME                       STATUS   ROLES                  AGE   VERSION
k3d-llm-cluster-agent-0    Ready    <none>                 76s   v1.31.5+k3s1
k3d-llm-cluster-agent-1    Ready    <none>                 76s   v1.31.5+k3s1
k3d-llm-cluster-server-0   Ready    control-plane,master   81s   v1.31.5+k3s1
```

---

## Installation

```bash
# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/

# k3d
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash

# Create cluster
k3d cluster create llm-cluster --agents 2

# Import image
k3d image import llm-inference:v1 -c llm-cluster
```

---

## k8s/deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-inference
  labels:
    app: llm-inference
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

---

## k8s/service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: llm-inference
  labels:
    app: llm-inference
spec:
  type: ClusterIP
  selector:
    app: llm-inference
  ports:
  - name: http
    port: 8000
    targetPort: 8000
    protocol: TCP
```

---

## k8s/hpa.yaml

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
NAME                REFERENCE                  TARGETS       MINPODS   MAXPODS   REPLICAS   AGE
llm-inference-hpa   Deployment/llm-inference   cpu: 3%/70%   2         6         2          3m10s
```

**HPA Explanation:** HPA monitors average CPU utilization across all Pods every 15 seconds. When CPU exceeds 70%, it scales up (max 6 pods). When load drops, it scales back down to minReplicas=2. This prevents both over-provisioning at idle and under-provisioning at peak load.

---

## Inference Test via Port-Forward

```
$ kubectl port-forward svc/llm-inference 8000:8000

$ curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"phi3:mini","messages":[{"role":"user","content":"Say hello in one word."}],"stream":false}'

{
    "id": "3b5a94ec",
    "object": "chat.completion",
    "model": "phi3:mini",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 16, "completion_tokens": 168, "total_tokens": 184}
}
```

---

## Key Design Decisions

- **`imagePullPolicy: Never`** — Forces k3d to use the locally imported image instead of pulling from Docker Hub
- **Resource requests vs limits** — requests=250m CPU ensures Pod gets scheduled; limits=500m prevents one Pod from starving others
- **readinessProbe + livenessProbe** — K8s won't send traffic to a Pod until `/health` returns 200; restarts unhealthy Pods automatically
- **HPA autoscaling/v2** — Supports multiple metric types; v1 only supported CPU percentage


