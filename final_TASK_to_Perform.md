You are a senior systems architect and full-stack platform engineer. Design DARWIN as a real, modular, local-first autonomous chaos-engineering and self-healing platform for Kubernetes microservices.

IMPORTANT CONSTRAINT:
Do NOT create Python-based replacements for external infrastructure services. Use the real external services as external dependencies and integrate with them. Do not mock or reimplement:
- Redis
- PostgreSQL
- Neo4j
- NATS
- Prometheus
- Loki
- Jaeger
- Kubernetes
- Istio (if used for network fault injection)

DARWIN is the control plane and orchestration layer. The patient application is the user’s microservice workload running on Kubernetes. The platform must host, observe, attack, detect, classify, predict, recover, and learn from the workload.

========================
1) GOAL OF THE SYSTEM
========================
Build a complete DARWIN platform with two sides:

A. PATIENT SIDE
The application the user provides and DARWIN hosts.
This should be a real microservice application deployed on Kubernetes.

B. DARWIN SIDE
The tool/platform layer that:
- deploys the patient app
- attaches telemetry collectors
- injects faults
- detects anomalies using ML
- retrieves recovery knowledge using RAG
- executes healing actions
- updates the knowledge graph in real time
- shows the live system state in a dashboard

The core closed loop is:
inject → detect → classify → predict → decide → recover → learn

========================
2) WHAT THE PATIENT SIDE MUST CONTAIN
========================
The patient side is the test application, not the intelligence core.

Design the patient app as a realistic microservice workload with:
- 5 or more microservices
- Kubernetes deployment manifests
- health endpoints
- metrics endpoints
- real traffic between services
- stateful dependencies where appropriate
- observable behavior under load

Each service should have:
- /health endpoint
- /metrics endpoint
- service-specific business endpoints
- logs
- realistic CPU/memory/network behavior
- optional PostgreSQL or Redis backing where needed

Suggested services:
- auth-service
- api-gateway
- order-service
- payment-service
- inventory-service
- notification-service

For each patient service, define:
- purpose
- dependencies
- exposed ports
- environment variables
- health check route
- metrics route
- deployment type
- resource requests/limits
- whether it uses PostgreSQL or Redis

The patient side should be containerized and deployable with Kubernetes manifests or Helm.

========================
3) WHAT THE DARWIN SIDE MUST CONTAIN
========================
DARWIN is the platform/control plane. It must be modular.

Core modules:
1. Virus Agent
   - injects controlled chaos
   - creates faults such as pod crashes, latency, packet loss, resource pressure, timing attacks, camouflage attacks
   - runs attacks in isolated subprocesses or isolated jobs so one failure does not crash the controller

2. Nerve Endings / Telemetry Collectors
   - collect raw metrics from each patient pod
   - do not make decisions
   - publish telemetry to NATS
   - collect CPU, memory, error rate, latency, restart count delta, network RX/TX delta

3. ML Brain
   - CUSUM for slow drift
   - Isolation Forest for fast anomaly detection
   - Random Forest for attack/failure classification
   - LSTM for next-attack prediction
   - all model code should be orchestration/inference only; do not replace external services

4. Antibody / Recovery Engine
   - subscribes to anomaly events
   - checks Redis immunity cache first
   - on cache miss, queries Neo4j knowledge graph
   - composes recovery plan
   - executes recovery actions on the patient app

5. Knowledge Graph
   - Neo4j stores attack families, attack strands, signatures, services, playbooks, dependencies, generations

6. DNA Store
   - PostgreSQL stores full incident history, generation history, recovery times, classifier confidence, cache hits, and outcomes

7. Event Bus
   - NATS carries telemetry and anomaly events between modules

8. Observability
   - Prometheus scrapes metrics
   - Loki stores logs
   - Jaeger stores traces

9. Dashboard
   - real-time UI showing attack status, anomaly scores, recovery timeline, knowledge graph updates, and replay

========================
4) EXTERNAL SERVICES: USE REAL ONES
========================
Use the real infrastructure services and integrate with them properly.

Required integrations:
- Redis: fast cache / immunity memory
- PostgreSQL: DNA/history store
- Neo4j: knowledge graph / brain memory
- NATS: event bus
- Prometheus: metrics scraping and time series
- Loki: logs aggregation
- Jaeger: distributed tracing
- Kubernetes: deployment and orchestration
- Istio: optional but preferred for traffic shaping and network fault injection

Do not create Python substitutes for these services.

If any service is optional, clearly state why, but prefer using the real tool.

========================
5) WHAT TO ASK THE USER FOR BEFORE DESIGNING
========================
Before finalizing the architecture or generating files, ask me for all required inputs.

Ask for:
- patient app type or domain
- number of microservices
- whether I already have source code or need templates
- Docker image names or Git repo URLs
- ports for each service
- health endpoint paths
- metrics endpoint paths
- environment variables
- database choice per service
- Kubernetes namespace name
- whether I want Helm or plain manifests
- whether I want Istio fault injection
- which external services are available already
- Redis connection details
- PostgreSQL connection details
- Neo4j connection details
- NATS connection details
- Prometheus setup details
- Loki setup details
- Jaeger setup details
- whether the demo should be fully local or hybrid
- whether I want a simple dry-run mode or full live mode

If any of these are missing, stop and ask me before proceeding.

========================
6) REQUIRED OUTPUT FORMAT
========================
When responding, produce the following sections:

A. System overview
B. Patient-side architecture
C. DARWIN-side architecture
D. Data flow / runtime flow
E. External service integration map
F. Folder structure / repository structure
G. Deployment plan
H. Real-time observability plan
I. Fault injection plan
J. Recovery plan
K. Knowledge graph update plan
L. Dry-run execution flow
M. What inputs are still needed from the user

========================
7) PATIENT-SIDE RULES
========================
The patient side should be treated as a normal app that the user wants to host.

It should:
- be deployable independently
- not know about ML internals
- not contain recovery logic
- not contain chaos logic
- only expose useful health, metrics, and business routes
- simulate realistic load and failure signals

The patient side should be described as the workload that DARWIN tests and heals.

========================
8) DARWIN-SIDE RULES
========================
The DARWIN side should:
- remain modular
- communicate over events
- keep detection separate from recovery
- keep storage separate from computation
- keep observability separate from business logic
- be easy to debug and modify
- tolerate failure of one module without breaking the whole platform

Use these principles:
- clear interfaces
- event-driven design
- isolated services
- retry/timeouts
- structured logs
- correlation IDs
- health endpoints for every module

========================
9) KNOWLEDGE GRAPH REQUIREMENTS
========================
Neo4j should track:
- attack family
- attack strand
- signature
- service
- playbook
- generation
- recovery outcome
- dependency edges
- mutation edges
- countermeasure edges

When a new anomaly is found:
- create/update nodes
- create/refresh relationships
- store the recovery outcome
- update Redis cache if the incident is recognized in the future

The knowledge graph should be visible in real time on the dashboard.

========================
10) RAG REQUIREMENTS
========================
Use RAG only for recovery knowledge retrieval and plan composition.

RAG flow:
- input: RF label + anomaly signature + service context
- retrieve from Redis first
- retrieve from Neo4j if cache miss
- augment with service dependency context
- generate/compose recovery plan
- execute healing actions

Do not use RAG as a general chatbot. Use it as the recovery decision knowledge layer.

========================
11) RESPONSE STYLE
========================
Be precise, modular, and implementation-oriented.
Prefer concrete files, modules, responsibilities, and interfaces.
Avoid hand-wavy descriptions.
If anything is missing, ask me for it before generating code or architecture.

Start by asking me for the missing inputs needed to build the patient side and the external services setup.