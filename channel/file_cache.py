"""
文件缓存管理器
用于缓存单独发送的文件消息（图片、视频、文档等），在用户提问时自动附加
"""
import time
import logging

logger = logging.getLogger(__name__)


class FileCache:
    """文件缓存管理器，按 session_id 缓存文件，TTL=2分钟"""
    
    def __init__(self, ttl=120):
        """
        Args:
            ttl: 缓存过期时间（秒），默认2分钟
        """
        self.cache = {}
        self.ttl = ttl
    
    def add(self, session_id: str, file_path: str, file_type: str = "image"):
        """
        添加文件到缓存
        
        Args:
            session_id: 会话ID
            file_path: 文件本地路径
            file_type: 文件类型（image, video, file 等）
        """
        if session_id not in self.cache:
            self.cache[session_id] = {
                'files': [],
                'timestamp': time.time()
            }
        
        # 添加文件（去重）
        file_info = {'path': file_path, 'type': file_type}
        if file_info not in self.cache[session_id]['files']:
            self.cache[session_id]['files'].append(file_info)
            logger.info(f"[FileCache] Added {file_type} to cache for session {session_id}: {file_path}")
    
    def get(self, session_id: str) -> list:
        """
        获取缓存的文件列表
        
        Args:
            session_id: 会话ID
        
        Returns:
            文件信息列表 [{'path': '...', 'type': 'image'}, ...]，如果没有或已过期返回空列表
        """
        if session_id not in self.cache:
            return []
        
        item = self.cache[session_id]
        
        # 检查是否过期
        if time.time() - item['timestamp'] > self.ttl:
            logger.info(f"[FileCache] Cache expired for session {session_id}, clearing...")
            del self.cache[session_id]
            return []
        
        return item['files']
    
    def clear(self, session_id: str):
        """
        清除指定会话的缓存
        
        Args:
            session_id: 会话ID
        """
        if session_id in self.cache:
            logger.info(f"[FileCache] Cleared cache for session {session_id}")
            del self.cache[session_id]
    
    def cleanup_expired(self):
        """清理所有过期的缓存"""
        current_time = time.time()
        expired_sessions = []
        
        for session_id, item in self.cache.items():
            if current_time - item['timestamp'] > self.ttl:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self.cache[session_id]
            logger.debug(f"[FileCache] Cleaned up expired cache for session {session_id}")
        
        if expired_sessions:
            logger.info(f"[FileCache] Cleaned up {len(expired_sessions)} expired cache(s)")


# 全局单例
_file_cache = FileCache()


def get_file_cache() -> FileCache:
    """获取全局文件缓存实例"""
    return _file_cache
