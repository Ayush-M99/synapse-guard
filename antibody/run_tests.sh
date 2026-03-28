#!/bin/bash
# Test runner script for Antibody Agent

set -e

echo "🧬 ANTIBODY AGENT - TEST SUITE"
echo "======================================================"
echo ""

# Check if we're in the antibody directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: Run this script from the antibody directory"
    exit 1
fi

# Install dependencies if needed
if [ "$1" == "--install" ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
    echo ""
fi

# Run tests based on argument
case "$1" in
    "unit")
        echo "🧪 Running UNIT tests..."
        pytest tests/ -v -m "not integration"
        ;;
    "integration")
        echo "🔄 Running INTEGRATION tests..."
        pytest tests/test_integration.py -v
        ;;
    "cov")
        echo "📊 Running tests with COVERAGE..."
        pytest tests/ -v --cov=antibody --cov-report=html --cov-report=term-missing
        echo ""
        echo "✅ Coverage report generated in htmlcov/index.html"
        ;;
    "all"|"")
        echo "🧪 Running ALL tests..."
        pytest tests/ -v
        ;;
    "quick")
        echo "⚡ Running quick tests..."
        pytest tests/ -v -x  # Stop on first failure
        ;;
    *)
        echo "Usage: $0 [unit|integration|cov|all|quick|--install]"
        exit 1
        ;;
esac

echo ""
echo "======================================================"
echo "✅ Test run complete!"
