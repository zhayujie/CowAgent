"""
Edit tool - Precise file editing
Edit files through exact text replacement
"""

import os
from typing import Dict, Any

from agent.tools.base_tool import BaseTool, ToolResult
from common.utils import expand_path
from agent.tools.utils.credentials import DENIED_MESSAGE, is_credential_path
from agent.tools.utils.diff import (
    strip_bom,
    detect_line_ending,
    normalize_to_lf,
    restore_line_endings,
    find_match_spans,
    generate_diff_string,
    looks_like_line_numbered_block,
    reindent_replacement,
    strip_line_number_prefixes,
)
from agent.tools.utils.file_state import note_write, staleness_warning
from agent.tools.utils.syntax_check import review as syntax_review


class Edit(BaseTool):
    """Tool for precise file editing"""
    
    name: str = "edit"
    description: str = "Edit a file by replacing exact text, or append to end if oldText is empty. For append: use empty oldText. For replace: oldText must match exactly (including whitespace) and must be unique unless replaceAll is true. IMPORTANT: the read tool prefixes each line with `12|` for display only - never include those prefixes in oldText or newText."
    requires_approval = True
    risk_level = "high"
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit (relative or absolute)"
            },
            "oldText": {
                "type": "string",
                "description": "Text to find and replace, copied from the file itself WITHOUT the `12|` line-number prefixes shown by the read tool. Use empty string to append to end of file. For replacement: must match exactly including whitespace."
            },
            "newText": {
                "type": "string",
                "description": "New text to replace the old text with (no line-number prefixes)"
            },
            "replaceAll": {
                "type": "boolean",
                "description": "Replace every occurrence of oldText instead of requiring it to be unique. Default false."
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
        replace_all = bool(args.get("replaceAll", False))
        replacements_made = 1
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")
        
        # Resolve path
        absolute_path = self._resolve_path(path)

        # Same guard the read tool applies. Editing is also a read: the success
        # result carries a diff whose context lines would expose the secrets.
        if is_credential_path(absolute_path):
            return ToolResult.fail(DENIED_MESSAGE)

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
                # Normal edit mode: find and replace.
                # Exact match is preferred; the fuzzy pattern only kicks in when
                # the exact substring is absent (see find_match_spans).
                spans, exact = find_match_spans(normalized_content, normalized_old_text)

                if not spans:
                    # Fallback: the model may have copied the `12|` gutter out of
                    # read output. Retry once without it. Doing this only after a
                    # normal miss means content that genuinely contains `12|` is
                    # never mangled.
                    retry_old = strip_line_number_prefixes(normalized_old_text)
                    if retry_old:
                        spans, exact = find_match_spans(normalized_content, retry_old)
                        if spans:
                            normalized_old_text = retry_old
                            stripped_new = strip_line_number_prefixes(normalized_new_text)
                            if stripped_new:
                                normalized_new_text = stripped_new

                if not spans:
                    return ToolResult.fail(
                        f"Error: Could not find the exact text in {path}. "
                        "The old text must match exactly including all whitespace and newlines."
                    )

                if len(spans) > 1 and not replace_all:
                    return ToolResult.fail(
                        f"Error: Found {len(spans)} occurrences of the text in {path}. "
                        "The text must be unique. Please provide more context to make it unique, "
                        "or set replaceAll to true to replace all of them."
                    )

                # Rebuild the file around the matched spans, back to front so the
                # earlier offsets stay valid.
                base_content = normalized_content
                new_content = base_content
                for start, end in reversed(spans):
                    replacement = normalized_new_text
                    if not exact:
                        # A fuzzy match swallowed the file's own indentation;
                        # re-anchor the replacement to it instead of silently
                        # reindenting the line to whatever the model sent.
                        replacement = reindent_replacement(
                            base_content[start:end], normalized_old_text, replacement
                        )
                    new_content = new_content[:start] + replacement + new_content[end:]
                replacements_made = len(spans)
            
            # Checked after the fallback above, so a newText whose gutter was
            # already stripped alongside oldText still goes through.
            if looks_like_line_numbered_block(normalized_new_text):
                return ToolResult.fail(
                    f"Error: newText looks like read tool output ('12|content'), not file "
                    f"content. Those line-number prefixes are display only - strip them "
                    f"before editing {path}."
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

            # Check before writing - our own write would reset the mtime.
            warning = staleness_warning(absolute_path)

            blocking, syntax_warning = syntax_review(absolute_path, base_content, new_content)
            if blocking:
                return ToolResult.fail(f"Error: {blocking}")

            # Write file
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            note_write(absolute_path)
            
            # Generate diff
            diff_result = generate_diff_string(base_content, new_content)

            if replacements_made > 1:
                message = f"Successfully replaced {replacements_made} occurrences in {path}"
            else:
                message = f"Successfully replaced text in {path}"

            result = {
                "message": message,
                "path": path,
                "diff": diff_result['diff'],
                "first_changed_line": diff_result['first_changed_line']
            }
            if replacements_made > 1:
                result["replacements"] = replacements_made
            warnings = [w for w in (warning, syntax_warning) if w]
            if warnings:
                result["warning"] = " ".join(warnings)
            
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
