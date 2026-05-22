"""
Edit tool - Precise file editing
Edit files through exact text replacement
"""

import os
from typing import Dict, Any

from agent.tools.base_tool import BaseTool, ToolResult
from common.utils import expand_path
from agent.tools.utils.diff import (
    strip_bom,
    detect_line_ending,
    normalize_to_lf,
    restore_line_endings,
    normalize_for_fuzzy_match,
    fuzzy_find_text,
    generate_diff_string
)


class Edit(BaseTool):
    """Tool for precise file editing"""
    
    name: str = "edit"
    description: str = "Edit a file by replacing exact text, or append to end if oldText is empty. For append: use empty oldText. For replace: oldText must match exactly (including whitespace)."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit (relative or absolute)"
            },
            "oldText": {
                "type": "string",
                "description": "Text to find and replace. Use empty string to append to end of file. For replacement: must match exactly including whitespace."
            },
            "newText": {
                "type": "string",
                "description": "New text to replace the old text with"
            }
        },
        "required": ["path", "oldText", "newText"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.memory_manager = self.config.get("memory_manager", None)
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute file edit operation
        
        :param args: Contains file path, old text and new text
        :return: Operation result
        """
        path = args.get("path", "").strip()
        old_text = args.get("oldText", "")
        new_text = args.get("newText", "")
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")
        
        # Resolve path
        absolute_path = self._resolve_path(path)
        
        # Check if file exists
        if not os.path.exists(absolute_path):
            return ToolResult.fail(f"Error: File not found: {path}")
        
        # Check if readable/writable
        if not os.access(absolute_path, os.R_OK | os.W_OK):
            return ToolResult.fail(f"Error: File is not readable/writable: {path}")
        
        try:
            # Read file
            with open(absolute_path, 'r', encoding='utf-8') as f:
                raw_content = f.read()
            
            # Remove BOM (LLM won't include invisible BOM in oldText)
            bom, content = strip_bom(raw_content)
            
            # Detect original line ending
            original_ending = detect_line_ending(content)
            
            # Normalize to LF
            normalized_content = normalize_to_lf(content)
            normalized_old_text = normalize_to_lf(old_text)
            normalized_new_text = normalize_to_lf(new_text)
            
            # Special case: empty oldText means append to end of file
            if not old_text or not old_text.strip():
                # Append mode: add newText to the end
                # Add newline before newText if file doesn't end with one
                if normalized_content and not normalized_content.endswith('\n'):
                    new_content = normalized_content + '\n' + normalized_new_text
                else:
                    new_content = normalized_content + normalized_new_text
                base_content = normalized_content  # For verification
            else:
                # Normal edit mode: find and replace
                # Use fuzzy matching to find old text (try exact match first, then fuzzy match)
                match_result = fuzzy_find_text(normalized_content, normalized_old_text)
                
                if not match_result.found:
                    return ToolResult.fail(
                        f"Error: Could not find the exact text in {path}. "
                        "The old text must match exactly including all whitespace and newlines."
                    )
                
                # Calculate occurrence count (use fuzzy normalized content for consistency)
                fuzzy_content = normalize_for_fuzzy_match(normalized_content)
                fuzzy_old_text = normalize_for_fuzzy_match(normalized_old_text)
                occurrences = fuzzy_content.count(fuzzy_old_text)
                
                if occurrences > 1:
                    return ToolResult.fail(
                        f"Error: Found {occurrences} occurrences of the text in {path}. "
                        "The text must be unique. Please provide more context to make it unique."
                    )
                
                # Execute replacement (use matched text position)
                base_content = match_result.content_for_replacement
                new_content = (
                    base_content[:match_result.index] +
                    normalized_new_text +
                    base_content[match_result.index + match_result.match_length:]
                )
            
            # Verify replacement actually changed content
            if base_content == new_content:
                return ToolResult.fail(
                    f"Error: No changes made to {path}. "
                    "The replacement produced identical content. "
                    "This might indicate an issue with special characters or the text not existing as expected."
                )
            
            # Restore original line endings
            final_content = bom + restore_line_endings(new_content, original_ending)
            
            # Write file
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            
            # Generate diff
            diff_result = generate_diff_string(base_content, new_content)
            
            result = {
                "message": f"Successfully replaced text in {path}",
                "path": path,
                "diff": diff_result['diff'],
                "first_changed_line": diff_result['first_changed_line']
            }
            
            # Notify memory manager if file is in memory directory
            if self.memory_manager and "memory/" in path:
                try:
                    self.memory_manager.mark_dirty()
                except Exception as e:
                    # Don't fail the edit if memory notification fails
                    pass
            
            return ToolResult.success(result)
            
        except UnicodeDecodeError:
            return ToolResult.fail(f"Error: File is not a valid text file (encoding error): {path}")
        except PermissionError:
            return ToolResult.fail(f"Error: Permission denied accessing {path}")
        except Exception as e:
            return ToolResult.fail(f"Error editing file: {str(e)}")
    
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
