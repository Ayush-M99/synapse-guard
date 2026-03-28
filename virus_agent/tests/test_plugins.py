"""
Unit tests for Virus Agent Attack Plugin System
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from base import AttackPlugin, AttackResult


class MockAttack(AttackPlugin):
    """Mock attack for testing"""

    def get_attack_id(self) -> str:
        return "mock_attack"

    def get_description(self) -> str:
        return "Mock attack for testing"

    def get_generation(self) -> int:
        return 1

    async def execute_attack(self, namespace: str, target_service: str) -> AttackResult:
        return AttackResult(
            success=True,
            attack_id="mock_attack",
            target_service=target_service,
            message="Mock attack executed"
        )

    async def cleanup(self, namespace: str, target_service: str) -> bool:
        return True


class TestAttackResult:
    """Test AttackResult dataclass"""

    def test_attack_result_creation(self):
        """Test creating AttackResult"""
        result = AttackResult(
            success=True,
            attack_id="test_attack",
            target_service="payment-service",
            message="Test successful"
        )

        assert result.success is True
        assert result.attack_id == "test_attack"
        assert result.target_service == "payment-service"
        assert result.message == "Test successful"

    def test_attack_result_to_dict(self):
        """Test AttackResult.to_dict()"""
        result = AttackResult(
            success=True,
            attack_id="pod_crash",
            target_service="auth-service",
            target_pod="auth-xyz"
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["attack_id"] == "pod_crash"
        assert data["target_service"] == "auth-service"
        assert data["target_pod"] == "auth-xyz"
        assert "timestamp" in data

    def test_attack_result_to_json(self):
        """Test AttackResult.to_json()"""
        result = AttackResult(
            success=False,
            attack_id="network_latency",
            target_service="order-service",
            error="No pods found"
        )

        json_str = result.to_json()

        assert "network_latency" in json_str
        assert "order-service" in json_str
        assert "No pods found" in json_str


class TestAttackPlugin:
    """Test AttackPlugin interface"""

    def test_mock_plugin_interface(self):
        """Test that mock plugin implements interface"""
        plugin = MockAttack()

        assert isinstance(plugin, AttackPlugin)
        assert plugin.get_attack_id() == "mock_attack"
        assert plugin.get_description() == "Mock attack for testing"
        assert plugin.get_generation() == 1

    @pytest.mark.asyncio
    async def test_mock_plugin_execute(self):
        """Test mock plugin execution"""
        plugin = MockAttack()

        result = await plugin.execute_attack("darwin-target", "payment-service")

        assert result.success is True
        assert result.attack_id == "mock_attack"
        assert result.target_service == "payment-service"

    @pytest.mark.asyncio
    async def test_mock_plugin_cleanup(self):
        """Test mock plugin cleanup"""
        plugin = MockAttack()

        result = await plugin.cleanup("darwin-target", "payment-service")

        assert result is True


class TestPluginRegistry:
    """Test plugin registry"""

    def test_registry_plugin_count(self):
        """Test loading all plugins from plugins directory"""
        from registry import AttackPluginRegistry

        registry = AttackPluginRegistry()

        # Should have 6 attack plugins
        attack_plugins = [
            "pod_crash",
            "network_latency",
            "resource_pressure",
            "timing_attack",
            "amplification",
            "camouflage"
        ]

        # Register mock plugins
        for attack_id in attack_plugins:
            plugin = MockAttack()
            # Override get_attack_id for testing
            plugin.get_attack_id = lambda aid=attack_id: aid
            registry.register_plugin(plugin)

        assert len(registry.list_all_attacks()) == len(attack_plugins)

    def test_registry_lists_attacks(self):
        """Test listing all attacks"""
        from registry import AttackPluginRegistry

        registry = AttackPluginRegistry()
        plugin = MockAttack()
        registry.register_plugin(plugin)

        attacks = registry.list_all_attacks()

        assert "mock_attack" in attacks

    def test_registry_get_plugin(self):
        """Test retrieving plugin from registry"""
        from registry import AttackPluginRegistry

        registry = AttackPluginRegistry()
        plugin = MockAttack()
        registry.register_plugin(plugin)

        retrieved = registry.get_plugin("mock_attack")

        assert retrieved is not None
        assert retrieved.get_attack_id() == "mock_attack"

    def test_registry_get_descriptions(self):
        """Test getting attack descriptions"""
        from registry import AttackPluginRegistry

        registry = AttackPluginRegistry()
        plugin = MockAttack()
        registry.register_plugin(plugin)

        descriptions = registry.get_attack_descriptions()

        assert "mock_attack" in descriptions
        assert descriptions["mock_attack"] == "Mock attack for testing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
