"""
Embedding providers for memory

Supports OpenAI and local embedding models
"""

import hashlib
from abc import ABC, abstractmethod
from typing import List, Optional


class EmbeddingProvider(ABC):
    """Base class for embedding providers"""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Generate embedding for text"""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        pass
    
    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Get embedding dimensions"""
        pass


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider using REST API"""
    
    def __init__(self, model: str = "text-embedding-3-small", api_key: Optional[str] = None,
                 api_base: Optional[str] = None, extra_headers: Optional[dict] = None):
        """
        Initialize OpenAI embedding provider

        Args:
            model: Model name (text-embedding-3-small or text-embedding-3-large)
            api_key: OpenAI API key
            api_base: Optional API base URL
            extra_headers: Optional extra headers to include in API requests
        """
        self.model = model
        # Name-mangled to prevent repr/attribute access from leaking the key to callers
        self.__api_key = api_key
        self.api_base = api_base or "https://api.openai.com/v1"
        self.extra_headers = extra_headers or {}

        # Validate API key
        if not self.__api_key or self.__api_key in ["", "YOUR API KEY", "YOUR_API_KEY"]:
            raise ValueError("OpenAI API key is not configured. Please set 'open_ai_api_key' in config.json")

        # Set dimensions based on model
        self._dimensions = 1536 if "small" in model else 3072

    def _call_api(self, input_data):
        """Call OpenAI embedding API using requests"""
        import requests

        url = f"{self.api_base}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.__api_key}",
            **self.extra_headers,
        }
        data = {
            "input": input_data,
            "model": self.model
        }

        try:
            response = requests.post(url, headers=headers, json=data, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Failed to connect to OpenAI API at {url}. Please check your network connection and api_base configuration. Error: {str(e)}")
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"OpenAI API request timed out after 10s. Please check your network connection. Error: {str(e)}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise ValueError(f"Invalid OpenAI API key. Please check your 'open_ai_api_key' in config.json")
            elif e.response.status_code == 429:
                raise ValueError(f"OpenAI API rate limit exceeded. Please try again later.")
            else:
                raise ValueError(f"OpenAI API request failed with status {e.response.status_code}. Check API provider logs for details.")

    def embed(self, text: str) -> List[float]:
        """Generate embedding for text"""
        result = self._call_api(text)
        return result["data"][0]["embedding"]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        if not texts:
            return []

        result = self._call_api(texts)
        return [item["embedding"] for item in result["data"]]

    @property
    def dimensions(self) -> int:
        return self._dimensions


# LocalEmbeddingProvider removed - only use OpenAI embedding or keyword search


class EmbeddingCache:
    """Cache for embeddings to avoid recomputation"""

    def __init__(self):
        self.cache = {}

    def get(self, text: str, provider: str, model: str) -> Optional[List[float]]:
        """Get cached embedding"""
        key = self._compute_key(text, provider, model)
        return self.cache.get(key)
    
    def put(self, text: str, provider: str, model: str, embedding: List[float]):
        """Cache embedding"""
        key = self._compute_key(text, provider, model)
        self.cache[key] = embedding
    
    @staticmethod
    def _compute_key(text: str, provider: str, model: str) -> str:
        """Compute cache key"""
        content = f"{provider}:{model}:{text}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def clear(self):
        """Clear cache"""
        self.cache.clear()


def create_embedding_provider(
    provider: str = "openai",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    extra_headers: Optional[dict] = None
) -> EmbeddingProvider:
    """
    Factory function to create embedding provider

    Supports "openai" and "linkai" providers (both use OpenAI-compatible REST API).
    If initialization fails, caller should fall back to keyword-only search.

    Args:
        provider: Provider name ("openai" or "linkai")
        model: Model name (default: text-embedding-3-small)
        api_key: API key (required)
        api_base: API base URL
        extra_headers: Optional extra headers to include in API requests

    Returns:
        EmbeddingProvider instance

    Raises:
        ValueError: If provider is unsupported or api_key is missing
    """
    if provider not in ("openai", "linkai"):
        raise ValueError(f"Unsupported embedding provider: {provider}. Use 'openai' or 'linkai'.")

    model = model or "text-embedding-3-small"
    return OpenAIEmbeddingProvider(model=model, api_key=api_key, api_base=api_base, extra_headers=extra_headers)
