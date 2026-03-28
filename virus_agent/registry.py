"""
Attack Plugin Registry
Dynamically discovers and registers all attack plugins
"""

import importlib
import logging
import os
from typing import Dict, Optional, List
from base import AttackPlugin


logger = logging.getLogger("virus-agent.registry")


class AttackPluginRegistry:
    """Registry for discovering and loading attack plugins"""

    def __init__(self):
        self.plugins: Dict[str, AttackPlugin] = {}
        self.logger = logger

    def register_plugin(self, plugin: AttackPlugin) -> None:
        """Register a plugin in the registry"""
        attack_id = plugin.get_attack_id()
        self.plugins[attack_id] = plugin
        self.logger.info(
            f"Registered attack plugin: {attack_id} ({plugin.get_description()})"
        )

    def get_plugin(self, attack_id: str) -> Optional[AttackPlugin]:
        """Get plugin by attack ID"""
        return self.plugins.get(attack_id)

    def list_all_attacks(self) -> List[str]:
        """List all registered attack IDs"""
        return sorted(list(self.plugins.keys()))

    def list_attacks_by_generation(self, generation: int) -> List[str]:
        """List attacks for a specific generation (1, 2, or 3)"""
        return [
            attack_id
            for attack_id, plugin in self.plugins.items()
            if plugin.get_generation() == generation
        ]

    def get_attack_descriptions(self) -> Dict[str, str]:
        """Get all attack IDs with their descriptions"""
        return {
            attack_id: plugin.get_description()
            for attack_id, plugin in self.plugins.items()
        }

    def load_plugins_from_directory(
        self, plugin_dir: str = "plugins"
    ) -> int:
        """
        Automatically discover and load plugins from a directory

        Args:
            plugin_dir: Directory containing plugin modules

        Returns:
            Number of plugins loaded
        """
        loaded_count = 0

        if not os.path.isdir(plugin_dir):
            self.logger.warning(f"Plugin directory not found: {plugin_dir}")
            return 0

        for filename in os.listdir(plugin_dir):
            # Skip special files
            if filename.startswith("_") or not filename.endswith(".py"):
                continue

            module_name = filename[:-3]  # Remove .py extension

            try:
                # Load module
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    os.path.join(plugin_dir, filename)
                )
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find all AttackPlugin subclasses in module
                for item_name in dir(module):
                    item = getattr(module, item_name)

                    # Check if it's a class and subclass of AttackPlugin
                    if (
                        isinstance(item, type)
                        and issubclass(item, AttackPlugin)
                        and item != AttackPlugin
                    ):
                        # Instantiate and register
                        plugin_instance = item()
                        self.register_plugin(plugin_instance)
                        loaded_count += 1

                self.logger.info(f"Loaded plugins from: {module_name}")

            except Exception as e:
                self.logger.error(f"Error loading plugin {module_name}: {e}")

        return loaded_count

    def validate_plugins(self) -> bool:
        """Validate all loaded plugins"""
        if not self.plugins:
            self.logger.warning("No plugins registered!")
            return False

        self.logger.info(f"Loaded {len(self.plugins)} attack plugins:")
        for attack_id, plugin in sorted(self.plugins.items()):
            gen = plugin.get_generation()
            desc = plugin.get_description()
            self.logger.info(f"  - {attack_id} (Gen {gen}): {desc}")

        return True
