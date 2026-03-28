.PHONY: help install test test-unit test-integration test-cov clean lint docker docker-build docker-push deploy destroy

help:
	@echo "Antibody Agent - Development commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install          Install dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test             Run all tests"
	@echo "  make test-unit        Run unit tests only"
	@echo "  make test-integration Run integration tests only"
	@echo "  make test-cov         Run tests with coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint             Run linting checks"
	@echo "  make format           Format code with black"
	@echo ""
	@echo "Docker & Deployment:"
	@echo "  make docker           Build Docker image"
	@echo "  make docker-push      Push to registry"
	@echo "  make deploy           Deploy to Kubernetes"
	@echo "  make destroy          Destroy Kubernetes deployment"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean            Remove __pycache__, .pytest_cache, etc"

# Setup
install:
	pip install -r requirements.txt

# Testing
test:
	pytest tests/ -v

test-unit:
	pytest tests/ -v -m "not integration"

test-integration:
	pytest tests/test_integration.py -v

test-cov:
	pytest tests/ -v --cov=antibody --cov-report=html --cov-report=term-missing

# Code Quality
lint:
	flake8 antibody/ tests/ --max-line-length=100

format:
	black antibody/ tests/

# Docker
docker: docker-build

docker-build:
	docker build -t darwin/antibody-agent:v1.0 .

docker-push:
	docker push darwin/antibody-agent:v1.0

# Kubernetes
deploy:
	kubectl apply -f ../k8s/darwin/antibody-agent-deployment.yaml
	kubectl rollout status deployment/antibody-agent -n darwin

destroy:
	kubectl delete -f ../k8s/darwin/antibody-agent-deployment.yaml

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +

.PHONY: help install test test-unit test-integration test-cov lint format docker docker-build docker-push deploy destroy clean
