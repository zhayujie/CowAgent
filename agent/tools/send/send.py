"""
Send tool - Send files to the user
"""

import os
from typing import Dict, Any
from pathlib import Path

from agent.tools.base_tool import BaseTool, ToolResult
from common.utils import expand_path


class Send(BaseTool):
    """Tool for sending files to the user"""
    
    name: str = "send"
    description: str = "Send a LOCAL file (image, video, audio, document) to the user. Only for local file paths. Do NOT use this for URLs — URLs should be included directly in your text reply, the system will handle them automatically."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Local file path to send. Must be an absolute path or relative to workspace. Do NOT pass URLs here."
            },
            "message": {
                "type": "string",
                "description": "Optional message to accompany the file"
            }
        },
        "required": ["path"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        
        # Supported file types
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'}
        self.video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v'}
        self.audio_extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma'}
        self.document_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.md'}
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute file send operation
        
        :param args: Contains file path and optional message
        :return: File metadata for channel to send
        """
        path = args.get("path", "").strip()
        message = args.get("message", "")
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")
        
        # Resolve path
        absolute_path = self._resolve_path(path)
        
        # Check if file exists
        if not os.path.exists(absolute_path):
            return ToolResult.fail(f"Error: File not found: {path}")
        
        # Check if readable
        if not os.access(absolute_path, os.R_OK):
            return ToolResult.fail(f"Error: File is not readable: {path}")
        
        # Get file info
        file_ext = Path(absolute_path).suffix.lower()
        file_size = os.path.getsize(absolute_path)
        file_name = Path(absolute_path).name
        
        # Determine file type
        if file_ext in self.image_extensions:
            file_type = "image"
            mime_type = self._get_image_mime_type(file_ext)
        elif file_ext in self.video_extensions:
            file_type = "video"
            mime_type = self._get_video_mime_type(file_ext)
        elif file_ext in self.audio_extensions:
            file_type = "audio"
            mime_type = self._get_audio_mime_type(file_ext)
        elif file_ext in self.document_extensions:
            file_type = "document"
            mime_type = self._get_document_mime_type(file_ext)
        else:
            file_type = "file"
            mime_type = "application/octet-stream"
        
        # Return file_to_send metadata
        result = {
            "type": "file_to_send",
            "file_type": file_type,
            "path": absolute_path,
            "file_name": file_name,
            "mime_type": mime_type,
            "size": file_size,
            "size_formatted": self._format_size(file_size),
            "message": message or f"正在发送 {file_name}"
        }

        try:
            from common.cloud_client import get_website_base_url, copy_send_file

            # Do nothing when in local env
            if get_website_base_url():
                url = copy_send_file(absolute_path, self.cwd)
                if url:
                    result["url"] = url
        except Exception:
            pass

        return ToolResult.success(result)
    
    def _resolve_path(self, path: str) -> str:
        """Resolve path to absolute path"""
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))
    
    def _get_image_mime_type(self, ext: str) -> str:
        """Get MIME type for image"""
        mime_map = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png', '.gif': 'image/gif',
            '.webp': 'image/webp', '.bmp': 'image/bmp',
            '.svg': 'image/svg+xml', '.ico': 'image/x-icon'
        }
        return mime_map.get(ext, 'image/jpeg')
    
    def _get_video_mime_type(self, ext: str) -> str:
        """Get MIME type for video"""
        mime_map = {
            '.mp4': 'video/mp4', '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime', '.mkv': 'video/x-matroska',
            '.webm': 'video/webm', '.flv': 'video/x-flv'
        }
        return mime_map.get(ext, 'video/mp4')
    
    def _get_audio_mime_type(self, ext: str) -> str:
        """Get MIME type for audio"""
        mime_map = {
            '.mp3': 'audio/mpeg', '.wav': 'audio/wav',
            '.ogg': 'audio/ogg', '.m4a': 'audio/mp4',
            '.flac': 'audio/flac', '.aac': 'audio/aac'
        }
        return mime_map.get(ext, 'audio/mpeg')
    
    def _get_document_mime_type(self, ext: str) -> str:
        """Get MIME type for document"""
        mime_map = {
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.txt': 'text/plain',
            '.md': 'text/markdown'
        }
        return mime_map.get(ext, 'application/octet-stream')
    
    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f}TB"
