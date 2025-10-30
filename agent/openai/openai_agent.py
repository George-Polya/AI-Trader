"""
OpenAIAgent - Agent using ChatOpenAI for OpenAI API with Web Search
"""

import os
from typing import Dict, Any, List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

import sys
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from agent.base_agent.base_agent import BaseAgent


class OpenAIAgent(BaseAgent):
    """
    Trading agent using ChatOpenAI client for OpenAI API

    Supports:
    - OpenAI API (gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.)
    - Native Web Search (optional)

    Additional config parameters:
    - openai_api_key: OpenAI API key
    - openai_base_url: Optional base URL
    - use_web_search: Enable OpenAI Web Search (default: False)
    - temperature: Model temperature (default: 0)
    """

    def __init__(
        self,
        signature: str,
        basemodel: str,
        stock_symbols: Optional[List[str]] = None,
        mcp_config: Optional[Dict[str, Dict[str, Any]]] = None,
        log_path: Optional[str] = None,
        max_steps: int = 10,
        max_retries: int = 3,
        base_delay: float = 0.5,
        initial_cash: float = 10000.0,
        init_date: str = "2025-10-13",
        use_web_search: bool = False,  # OpenAI-specific parameter
        **kwargs
    ):
        """
        Initialize OpenAIAgent

        Args:
            signature: Agent signature/name
            basemodel: Base model name (e.g., "openai/gpt-4o")
            stock_symbols: List of stock symbols
            mcp_config: MCP tool configuration
            log_path: Log path
            max_steps: Maximum reasoning steps
            max_retries: Maximum retry attempts
            base_delay: Base delay time for retries
            initial_cash: Initial cash amount
            init_date: Initialization date
            use_web_search: Enable OpenAI Web Search (default: False)
            **kwargs: Additional parameters
        """
        # Set use_web_search BEFORE calling super().__init__()
        # because _get_default_mcp_config() is called during parent init
        self.use_web_search = use_web_search

        super().__init__(
            signature=signature,
            basemodel=basemodel,
            stock_symbols=stock_symbols,
            mcp_config=mcp_config,
            log_path=log_path,
            max_steps=max_steps,
            max_retries=max_retries,
            base_delay=base_delay,
            initial_cash=initial_cash,
            init_date=init_date,
            **kwargs  # use_web_search는 kwargs에 포함됨
        )


    def _get_model_config(self) -> Dict[str, Any]:
        """
        Get OpenAI model configuration

        Priority:
        1. Constructor kwargs (from config file)
        2. Environment variables
        3. Default values
        """
        config = self.additional_config

        # Remove "openai/" prefix if exists (e.g., "openai/gpt-4o" -> "gpt-4o")
        model_name = self.basemodel.replace("openai/", "")

        model_config = {
            "model": model_name,
            "api_key": config.get("openai_api_key") or os.getenv("OPENAI_API_KEY"),
            "max_retries": config.get("max_retries", 3),
            "timeout": config.get("timeout", 30),
            "temperature": config.get("temperature", 0)
        }


        # Enable Responses API if web search is used
        if self.use_web_search:
            model_config["use_responses_api"] = True

        return model_config

    def _create_model(self) -> BaseChatModel:
        """
        Create ChatOpenAI model instance with optional Web Search

        Returns:
            ChatOpenAI instance with optional web search binding
        """
        model_config = self._get_model_config()

        print(f"🤖 Creating OpenAI model:")
        print(f"   Model: {model_config['model']}")
        if 'base_url' in model_config:
            print(f"   Base URL: {model_config['base_url']}")
        print(f"   Web Search: {'Enabled' if self.use_web_search else 'Disabled'}")
        if self.use_web_search:
            print(f"   Responses API: True")

        model = ChatOpenAI(**model_config)

        # Bind Web Search if enabled
        if self.use_web_search:
            print(f"🔍 Binding OpenAI Web Search")
            model = model.bind(
                extra_body={
                    "tools": [{"type": "web_search"}],
                    "tool_choice": "auto",  # Model decides when to use it
                }
            )

        return model

    def _post_initialize(self) -> None:
        """
        Post-initialization: Log OpenAI-specific setup
        """
        if self.use_web_search:
            print(f"✅ OpenAI Web Search enabled")
            print(f"   Agent will use real-time web search for market information")
