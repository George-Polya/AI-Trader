"""
GoogleAgent - Agent using ChatGoogleGenerativeAI for Gemini models
"""

import os
from typing import Dict, Any, List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models import BaseChatModel

import sys
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from agent.base_agent.base_agent import BaseAgent


class GoogleAgent(BaseAgent):
    """
    Trading agent using ChatGoogleGenerativeAI client

    Supports:
    - Gemini models (gemini-2.5-flash, gemini-pro, etc.)
    - Google Search Grounding (optional)

    Additional config parameters:
    - openai_api_key: API key (reused for Google API)
    - use_web_search: Enable Google Search Grounding (default: False)
    - temperature: Model temperature (default: 0)
    - max_output_tokens: Maximum output tokens (default: 8192)
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
        use_web_search: bool = False,  # Google-specific parameter
        **kwargs
    ):
        """
        Initialize GoogleAgent

        Args:
            signature: Agent signature/name
            basemodel: Base model name (e.g., "google/gemini-2.5-flash")
            stock_symbols: List of stock symbols
            mcp_config: MCP tool configuration
            log_path: Log path
            max_steps: Maximum reasoning steps
            max_retries: Maximum retry attempts
            base_delay: Base delay time for retries
            initial_cash: Initial cash amount
            init_date: Initialization date
            use_web_search: Enable Google Search Grounding (default: False)
            **kwargs: Additional parameters
        """
        # Set use_web_search BEFORE calling super().__init__()
        self.use_web_search = use_web_search
        self.search_tool = {"google_search": {}} if use_web_search else None

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
        Get Google model configuration

        Priority:
        1. Constructor kwargs (from config file)
        2. Environment variables
        3. Default values
        """
        config = self.additional_config

        # Get API key (reuse openai_api_key field)
        api_key = config.get("openai_api_key") or os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "Google API key not found. "
                "Set 'openai_api_key' in config or GOOGLE_API_KEY/OPENAI_API_KEY environment variable."
            )

        # Remove "google/" prefix if exists (e.g., "google/gemini-2.5-flash" -> "gemini-2.5-flash")
        model_name = self.basemodel.replace("google/", "")

        return {
            "model": model_name,
            "google_api_key": api_key,
            "max_retries": config.get("max_retries", 6),
            "temperature": config.get("temperature", 0),
            "timeout": config.get("timeout", 60)
        }

    def _create_model(self) -> BaseChatModel:
        """
        Create ChatGoogleGenerativeAI model instance

        Returns:
            ChatGoogleGenerativeAI instance with optional Google Search binding
        """
        model_config = self._get_model_config()

        print(f"🤖 Creating Google Gemini model:")
        print(f"   Model: {model_config['model']}")
        print(f"   Google Search: {'Enabled' if self.use_web_search else 'Disabled'}")

        model = ChatGoogleGenerativeAI(**model_config)

        # Bind Google Search tool if enabled
        if self.use_web_search:
            print(f"🔍 Binding Google Search Grounding tool")
            model = model.bind(tools=[self.search_tool])

        return model

    def _post_initialize(self) -> None:
        """
        Post-initialization: Log Google-specific setup
        """
        if self.use_web_search:
            print(f"✅ Google Search Grounding enabled")
            print(f"   Agent will use real-time web search for market information")
