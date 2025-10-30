"""
OpenRouterAgent - Agent using ChatOpenAI for OpenRouter API
"""

import os
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

import sys
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from agent.base_agent.base_agent import BaseAgent


class OpenRouterAgent(BaseAgent):
    """
    Trading agent using ChatOpenAI client for OpenRouter API

    Supports:
    - Claude (anthropic/claude-*)
    - Deepseek (deepseek/*)
    - Qwen (qwen/*)
    - GLM (z-ai/*)
    - Any OpenRouter-supported models

    OpenRouter provides unified access to multiple LLM providers
    through an OpenAI-compatible API.
    """

    def _get_model_config(self) -> Dict[str, Any]:
        """
        Get OpenRouter model configuration

        Priority:
        1. Constructor kwargs (from config file)
        2. Environment variables
        3. Default values (OpenRouter URL)
        """
        config = self.additional_config

        # Default to OpenRouter if not specified
        base_url = config.get("openai_base_url") or os.getenv("OPENAI_API_BASE") or "https://openrouter.ai/api/v1"

        return {
            "model": self.basemodel,
            "base_url": base_url,
            "api_key": config.get("openai_api_key") or os.getenv("OPENAI_API_KEY"),
            "max_retries": config.get("max_retries", 3),
            "timeout": config.get("timeout", 30),
            "temperature": config.get("temperature", 0)
        }

    def _create_model(self) -> BaseChatModel:
        """
        Create ChatOpenAI model instance for OpenRouter

        Returns:
            ChatOpenAI instance configured for OpenRouter
        """
        model_config = self._get_model_config()

        print(f"🤖 Creating OpenRouter model:")
        print(f"   Model: {model_config['model']}")
        print(f"   Base URL: {model_config['base_url']}")

        return ChatOpenAI(**model_config)
