import importlib
import inspect
from pathlib import Path

from packages.plugin_sdk import BasePlugin, PluginContext
from packages.shared.logging.logger import get_logger

logger = get_logger("plugin_loader")


class PluginLoader:
    """Dynamic Plugin Loader & Lifecycle Manager."""

    def __init__(self):
        self.plugins: dict[str, BasePlugin] = {}

    def register_plugin(self, plugin: BasePlugin) -> None:
        """Register a plugin instance."""
        if plugin.name in self.plugins:
            logger.warning(f"Plugin {plugin.name} is already registered. Overwriting.")
        self.plugins[plugin.name] = plugin
        logger.info(f"Registered plugin: {plugin.name} (v{plugin.version})")

    def discover_and_load_plugins(self, plugins_dir: str = "plugins") -> list[BasePlugin]:
        """Scans plugins directory to dynamically load plugin classes."""
        dir_path = Path(plugins_dir)
        if not dir_path.exists():
            logger.warning(f"Plugins directory '{plugins_dir}' does not exist.")
            return list(self.plugins.values())

        for path in dir_path.glob("*/plugin.py"):
            module_name = f"{plugins_dir}.{path.parent.name}.plugin".replace("/", ".")
            try:
                module = importlib.import_module(module_name)
                for _name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, BasePlugin) and obj is not BasePlugin:
                        plugin_instance = obj()
                        self.register_plugin(plugin_instance)
            except Exception as e:
                logger.error(f"Failed to load plugin from {path}: {str(e)}")

        return list(self.plugins.values())

    async def initialize_plugins(self, context: PluginContext = PluginContext()) -> None:
        """Invoke on_load hook for all loaded plugins."""
        for plugin in self.plugins.values():
            try:
                await plugin.on_load(context)
            except Exception as e:
                logger.error(f"Error during on_load for plugin {plugin.name}: {str(e)}")

    async def execute_on_request(self, context: PluginContext) -> None:
        """Invoke on_request hook across active plugins."""
        for plugin in self.plugins.values():
            try:
                await plugin.on_request(context)
            except Exception as e:
                logger.error(f"Error during on_request for plugin {plugin.name}: {str(e)}")

    async def execute_on_response(self, context: PluginContext) -> None:
        """Invoke on_response hook across active plugins."""
        for plugin in self.plugins.values():
            try:
                await plugin.on_response(context)
            except Exception as e:
                logger.error(f"Error during on_response for plugin {plugin.name}: {str(e)}")

    async def unload_plugins(self) -> None:
        """Invoke on_unload hook across active plugins."""
        for plugin in self.plugins.values():
            try:
                await plugin.on_unload()
            except Exception as e:
                logger.error(f"Error during on_unload for plugin {plugin.name}: {str(e)}")
        self.plugins.clear()
