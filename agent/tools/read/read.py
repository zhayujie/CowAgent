"""
Read tool - Read file contents
Supports text files, images (jpg, png, gif, webp), and PDF files
"""

import os
from typing import Dict, Any
from pathlib import Path

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.truncate import truncate_head, format_size, DEFAULT_MAX_LINES, DEFAULT_MAX_BYTES
from common.utils import expand_path


class Read(BaseTool):
    """Tool for reading file contents"""
    
    name: str = "read"
    description: str = f"Read or inspect file contents. For text/PDF files, returns content (truncated to {DEFAULT_MAX_LINES} lines or {DEFAULT_MAX_BYTES // 1024}KB). For images/videos/audio, returns metadata only (file info, size, type). Use offset/limit for large text files."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read. IMPORTANT: Relative paths are based on workspace directory. To access files outside workspace, use absolute paths starting with ~ or /."
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed, optional). Use negative values to read from end (e.g. -20 for last 20 lines)"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read (optional)"
            }
        },
        "required": ["path"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        
        # File type categories
        self.image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico'}
        self.video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v'}
        self.audio_extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma'}
        self.binary_extensions = {'.exe', '.dll', '.so', '.dylib', '.bin', '.dat', '.db', '.sqlite'}
        self.archive_extensions = {'.zip', '.tar', '.gz', '.rar', '.7z', '.bz2', '.xz'}
        self.pdf_extensions = {'.pdf'}
        self.office_extensions = {'.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}

        # Readable text formats (will be read with truncation)
        self.text_extensions = {
            '.txt', '.md', '.markdown', '.rst', '.log', '.csv', '.tsv', '.json', '.xml', '.yaml', '.yml',
            '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.hpp', '.go', '.rs', '.rb', '.php',
            '.html', '.css', '.scss', '.sass', '.less', '.vue', '.jsx', '.tsx',
            '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
            '.sql', '.r', '.m', '.swift', '.kt', '.scala', '.clj', '.erl', '.ex',
            '.dockerfile', '.makefile', '.cmake', '.gradle', '.properties', '.ini', '.conf', '.cfg',
        }
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute file read operation
        
        :param args: Contains file path and optional offset/limit parameters
        :return: File content or error message
        """
        # Support 'location' as alias for 'path' (LLM may use it from skill listing)
        path = args.get("path", "") or args.get("location", "")
        path = path.strip() if isinstance(path, str) else ""
        offset = args.get("offset")
        limit = args.get("limit")

        if not path:
            return ToolResult.fail("Error: path parameter is required")
        
        # Resolve path
        absolute_path = self._resolve_path(path)
        
        # Security check: Prevent reading sensitive config files
        env_config_path = expand_path("~/.cow/.env")
        if os.path.abspath(absolute_path) == os.path.abspath(env_config_path):
            return ToolResult.fail(
                "Error: Access denied. API keys and credentials must be accessed through the env_config tool only."
            )
        
        # Check if file exists
        if not os.path.exists(absolute_path):
            # Provide helpful hint if using relative path
            if not os.path.isabs(path) and not path.startswith('~'):
                return ToolResult.fail(
                    f"Error: File not found: {path}\n"
                    f"Resolved to: {absolute_path}\n"
                    f"Hint: Relative paths are based on workspace ({self.cwd}). For files outside workspace, use absolute paths."
                )
            return ToolResult.fail(f"Error: File not found: {path}")
        
        # Check if readable
        if not os.access(absolute_path, os.R_OK):
            return ToolResult.fail(f"Error: File is not readable: {path}")
        
        # Check file type
        file_ext = Path(absolute_path).suffix.lower()
        file_size = os.path.getsize(absolute_path)
        
        # Check if image - return metadata for sending
        if file_ext in self.image_extensions:
            return self._read_image(absolute_path, file_ext)
        
        # Check if video/audio/binary/archive - return metadata only
        if file_ext in self.video_extensions:
            return self._return_file_metadata(absolute_path, "video", file_size)
        if file_ext in self.audio_extensions:
            return self._return_file_metadata(absolute_path, "audio", file_size)
        if file_ext in self.binary_extensions or file_ext in self.archive_extensions:
            return self._return_file_metadata(absolute_path, "binary", file_size)
        
        # Check if PDF
        if file_ext in self.pdf_extensions:
            return self._read_pdf(absolute_path, path, offset, limit)

        # Check if Office document (.docx, .xlsx, .pptx, etc.)
        if file_ext in self.office_extensions:
            return self._read_office(absolute_path, path, file_ext, offset, limit)

        # Read text file (with truncation for large files)
        return self._read_text(absolute_path, path, offset, limit)
    
    def _resolve_path(self, path: str) -> str:
        """
        Resolve path to absolute path
        
        :param path: Relative or absolute path
        :return: Absolute path
        """
        # Expand ~ to user home directory
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))
    
    def _return_file_metadata(self, absolute_path: str, file_type: str, file_size: int) -> ToolResult:
        """
        Return file metadata for non-readable files (video, audio, binary, etc.)
        
        :param absolute_path: Absolute path to the file
        :param file_type: Type of file (video, audio, binary, etc.)
        :param file_size: File size in bytes
        :return: File metadata
        """
        file_name = Path(absolute_path).name
        file_ext = Path(absolute_path).suffix.lower()
        
        # Determine MIME type
        mime_types = {
            # Video
            '.mp4': 'video/mp4', '.avi': 'video/x-msvideo', '.mov': 'video/quicktime',
            '.mkv': 'video/x-matroska', '.webm': 'video/webm',
            # Audio
            '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
            '.m4a': 'audio/mp4', '.flac': 'audio/flac',
            # Binary
            '.zip': 'application/zip', '.tar': 'application/x-tar',
            '.gz': 'application/gzip', '.rar': 'application/x-rar-compressed',
        }
        mime_type = mime_types.get(file_ext, 'application/octet-stream')
        
        result = {
            "type": f"{file_type}_metadata",
            "file_type": file_type,
            "path": absolute_path,
            "file_name": file_name,
            "mime_type": mime_type,
            "size": file_size,
            "size_formatted": format_size(file_size),
            "message": f"{file_type.capitalize()} 文件: {file_name} ({format_size(file_size)})\n提示: 如果需要发送此文件，请使用 send 工具。"
        }
        
        return ToolResult.success(result)
    
    def _read_image(self, absolute_path: str, file_ext: str) -> ToolResult:
        """
        Read image file - always return metadata only (images should be sent, not read into context)
        
        :param absolute_path: Absolute path to the image file
        :param file_ext: File extension
        :return: Result containing image metadata for sending
        """
        try:
            # Get file size
            file_size = os.path.getsize(absolute_path)
            
            # Determine MIME type
            mime_type_map = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }
            mime_type = mime_type_map.get(file_ext, 'image/jpeg')
            
            # Return metadata for images (NOT file_to_send - use send tool to actually send)
            result = {
                "type": "image_metadata",
                "file_type": "image",
                "path": absolute_path,
                "mime_type": mime_type,
                "size": file_size,
                "size_formatted": format_size(file_size),
                "message": f"图片文件: {Path(absolute_path).name} ({format_size(file_size)})\n提示: 如果需要发送此图片，请使用 send 工具。"
            }
            
            return ToolResult.success(result)
            
        except Exception as e:
            return ToolResult.fail(f"Error reading image file: {str(e)}")
    
    def _read_text(self, absolute_path: str, display_path: str, offset: int = None, limit: int = None) -> ToolResult:
        """
        Read text file
        
        :param absolute_path: Absolute path to the file
        :param display_path: Path to display
        :param offset: Starting line number (1-indexed)
        :param limit: Maximum number of lines to read
        :return: File content or error message
        """
        try:
            # Check file size first
            file_size = os.path.getsize(absolute_path)
            MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
            
            if file_size > MAX_FILE_SIZE:
                # File too large, return metadata only
                return ToolResult.success({
                    "type": "file_to_send",
                    "file_type": "document",
                    "path": absolute_path,
                    "size": file_size,
                    "size_formatted": format_size(file_size),
                    "message": f"文件过大 ({format_size(file_size)} > 50MB)，无法读取内容。文件路径: {absolute_path}"
                })
            
            # Read file (utf-8-sig strips BOM automatically on Windows)
            # Note: Truncation is unified via truncate_head (DEFAULT_MAX_LINES / DEFAULT_MAX_BYTES)
            # so that offset/limit can paginate the entire file correctly.
            with open(absolute_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()

            all_lines = content.split('\n')
            total_file_lines = len(all_lines)
            
            # Apply offset (if specified)
            start_line = 0
            if offset is not None:
                if offset < 0:
                    # Negative offset: read from end
                    # -20 means "last 20 lines" → start from (total - 20)
                    start_line = max(0, total_file_lines + offset)
                else:
                    # Positive offset: read from start (1-indexed)
                    start_line = max(0, offset - 1)  # Convert to 0-indexed
                    if start_line >= total_file_lines:
                        return ToolResult.fail(
                            f"Error: Offset {offset} is beyond end of file ({total_file_lines} lines total)"
                        )
            
            start_line_display = start_line + 1  # For display (1-indexed)
            
            # If user specified limit, use it
            selected_content = content
            user_limited_lines = None
            if limit is not None:
                end_line = min(start_line + limit, total_file_lines)
                selected_content = '\n'.join(all_lines[start_line:end_line])
                user_limited_lines = end_line - start_line
            elif offset is not None:
                selected_content = '\n'.join(all_lines[start_line:])
            
            # Apply truncation (considering line count and byte limits)
            truncation = truncate_head(selected_content)
            
            output_text = ""
            details = {}

            if truncation.first_line_exceeds_limit:
                # First line exceeds 30KB limit
                first_line_size = format_size(len(all_lines[start_line].encode('utf-8')))
                output_text = f"[Line {start_line_display} is {first_line_size}, exceeds {format_size(DEFAULT_MAX_BYTES)} limit. Use bash tool to read: head -c {DEFAULT_MAX_BYTES} {display_path} | tail -n +{start_line_display}]"
                details["truncation"] = truncation.to_dict()
            elif truncation.truncated:
                # Truncation occurred
                end_line_display = start_line_display + truncation.output_lines - 1
                next_offset = end_line_display + 1
                
                output_text = truncation.content
                
                if truncation.truncated_by == "lines":
                    output_text += f"\n\n[Showing lines {start_line_display}-{end_line_display} of {total_file_lines}. Use offset={next_offset} to continue.]"
                else:
                    output_text += f"\n\n[Showing lines {start_line_display}-{end_line_display} of {total_file_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). Use offset={next_offset} to continue.]"
                
                details["truncation"] = truncation.to_dict()
            elif user_limited_lines is not None and start_line + user_limited_lines < total_file_lines:
                # User specified limit, more content available, but no truncation
                remaining = total_file_lines - (start_line + user_limited_lines)
                next_offset = start_line + user_limited_lines + 1
                
                output_text = truncation.content
                output_text += f"\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"
            else:
                # No truncation, no exceeding user limit
                output_text = truncation.content
            
            result = {
                "content": output_text,
                "total_lines": total_file_lines,
                "start_line": start_line_display,
                "output_lines": truncation.output_lines
            }
            
            if details:
                result["details"] = details
            
            return ToolResult.success(result)
            
        except UnicodeDecodeError:
            return ToolResult.fail(f"Error: File is not a valid text file (encoding error): {display_path}")
        except Exception as e:
            return ToolResult.fail(f"Error reading file: {str(e)}")
    
    def _read_office(self, absolute_path: str, display_path: str, file_ext: str,
                     offset: int = None, limit: int = None) -> ToolResult:
        """Read Office documents (.docx, .xlsx, .pptx) using python-docx / openpyxl / python-pptx."""
        try:
            text = self._extract_office_text(absolute_path, file_ext)
        except ImportError as e:
            return ToolResult.fail(str(e))
        except Exception as e:
            return ToolResult.fail(f"Error reading Office document: {e}")

        if not text or not text.strip():
            return ToolResult.success({
                "content": f"[Office file {Path(absolute_path).name}: no text content could be extracted]",
            })

        all_lines = text.split('\n')
        total_lines = len(all_lines)

        start_line = 0
        if offset is not None:
            if offset < 0:
                start_line = max(0, total_lines + offset)
            else:
                start_line = max(0, offset - 1)
                if start_line >= total_lines:
                    return ToolResult.fail(
                        f"Error: Offset {offset} is beyond end of content ({total_lines} lines total)"
                    )

        selected_content = text
        user_limited_lines = None
        if limit is not None:
            end_line = min(start_line + limit, total_lines)
            selected_content = '\n'.join(all_lines[start_line:end_line])
            user_limited_lines = end_line - start_line
        elif offset is not None:
            selected_content = '\n'.join(all_lines[start_line:])

        truncation = truncate_head(selected_content)
        start_line_display = start_line + 1
        output_text = ""

        if truncation.truncated:
            end_line_display = start_line_display + truncation.output_lines - 1
            next_offset = end_line_display + 1
            output_text = truncation.content
            output_text += f"\n\n[Showing lines {start_line_display}-{end_line_display} of {total_lines}. Use offset={next_offset} to continue.]"
        elif user_limited_lines is not None and start_line + user_limited_lines < total_lines:
            remaining = total_lines - (start_line + user_limited_lines)
            next_offset = start_line + user_limited_lines + 1
            output_text = truncation.content
            output_text += f"\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"
        else:
            output_text = truncation.content

        return ToolResult.success({
            "content": output_text,
            "total_lines": total_lines,
            "start_line": start_line_display,
            "output_lines": truncation.output_lines,
        })

    @staticmethod
    def _extract_office_text(absolute_path: str, file_ext: str) -> str:
        """Extract plain text from an Office document."""
        if file_ext in ('.docx', '.doc'):
            try:
                from docx import Document
            except ImportError:
                raise ImportError("Error: python-docx library not installed. Install with: pip install python-docx")
            doc = Document(absolute_path)
            paragraphs = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    paragraphs.append('\t'.join(cell.text for cell in row.cells))
            return '\n'.join(paragraphs)

        if file_ext in ('.xlsx', '.xls'):
            try:
                from openpyxl import load_workbook
            except ImportError:
                raise ImportError("Error: openpyxl library not installed. Install with: pip install openpyxl")
            wb = load_workbook(absolute_path, read_only=True, data_only=True)
            parts = []
            for ws in wb.worksheets:
                parts.append(f"--- Sheet: {ws.title} ---")
                for row in ws.iter_rows(values_only=True):
                    parts.append('\t'.join(str(c) if c is not None else '' for c in row))
            wb.close()
            return '\n'.join(parts)

        if file_ext in ('.pptx', '.ppt'):
            try:
                from pptx import Presentation
            except ImportError:
                raise ImportError("Error: python-pptx library not installed. Install with: pip install python-pptx")
            prs = Presentation(absolute_path)
            parts = []
            for i, slide in enumerate(prs.slides, 1):
                parts.append(f"--- Slide {i} ---")
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            text = para.text.strip()
                            if text:
                                parts.append(text)
            return '\n'.join(parts)

        return ""

    def _read_pdf(self, absolute_path: str, display_path: str, offset: int = None, limit: int = None) -> ToolResult:
        """
        Read PDF file content
        
        :param absolute_path: Absolute path to the file
        :param display_path: Path to display
        :param offset: Starting line number (1-indexed)
        :param limit: Maximum number of lines to read
        :return: PDF text content or error message
        """
        try:
            # Try to import pypdf
            try:
                from pypdf import PdfReader
            except ImportError:
                return ToolResult.fail(
                    "Error: pypdf library not installed. Install with: pip install pypdf"
                )
            
            # Read PDF
            reader = PdfReader(absolute_path)
            total_pages = len(reader.pages)
            
            # Extract text from all pages
            text_parts = []
            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text()
                if page_text.strip():
                    text_parts.append(f"--- Page {page_num} ---\n{page_text}")
            
            if not text_parts:
                return ToolResult.success({
                    "content": f"[PDF file with {total_pages} pages, but no text content could be extracted]",
                    "total_pages": total_pages,
                    "message": "PDF may contain only images or be encrypted"
                })
            
            # Merge all text
            full_content = "\n\n".join(text_parts)
            all_lines = full_content.split('\n')
            total_lines = len(all_lines)
            
            # Apply offset and limit (same logic as text files)
            start_line = 0
            if offset is not None:
                start_line = max(0, offset - 1)
                if start_line >= total_lines:
                    return ToolResult.fail(
                        f"Error: Offset {offset} is beyond end of content ({total_lines} lines total)"
                    )
            
            start_line_display = start_line + 1
            
            selected_content = full_content
            user_limited_lines = None
            if limit is not None:
                end_line = min(start_line + limit, total_lines)
                selected_content = '\n'.join(all_lines[start_line:end_line])
                user_limited_lines = end_line - start_line
            elif offset is not None:
                selected_content = '\n'.join(all_lines[start_line:])
            
            # Apply truncation
            truncation = truncate_head(selected_content)
            
            output_text = ""
            details = {}
            
            if truncation.truncated:
                end_line_display = start_line_display + truncation.output_lines - 1
                next_offset = end_line_display + 1
                
                output_text = truncation.content
                
                if truncation.truncated_by == "lines":
                    output_text += f"\n\n[Showing lines {start_line_display}-{end_line_display} of {total_lines}. Use offset={next_offset} to continue.]"
                else:
                    output_text += f"\n\n[Showing lines {start_line_display}-{end_line_display} of {total_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). Use offset={next_offset} to continue.]"
                
                details["truncation"] = truncation.to_dict()
            elif user_limited_lines is not None and start_line + user_limited_lines < total_lines:
                remaining = total_lines - (start_line + user_limited_lines)
                next_offset = start_line + user_limited_lines + 1
                
                output_text = truncation.content
                output_text += f"\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"
            else:
                output_text = truncation.content
            
            result = {
                "content": output_text,
                "total_pages": total_pages,
                "total_lines": total_lines,
                "start_line": start_line_display,
                "output_lines": truncation.output_lines
            }
            
            if details:
                result["details"] = details
            
            return ToolResult.success(result)
            
        except Exception as e:
            return ToolResult.fail(f"Error reading PDF file: {str(e)}")
