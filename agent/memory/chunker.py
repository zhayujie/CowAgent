"""
Text chunking utilities for memory

Splits text into chunks with token limits and overlap
"""

from __future__ import annotations
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class TextChunk:
    """Represents a text chunk with line numbers"""
    text: str
    start_line: int
    end_line: int


class TextChunker:
    """Chunks text by line count with token estimation"""
    
    def __init__(self, max_tokens: int = 500, overlap_tokens: int = 50):
        """
        Initialize chunker
        
        Args:
            max_tokens: Maximum tokens per chunk
            overlap_tokens: Overlap tokens between chunks
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        # Rough estimation: ~4 chars per token for English/Chinese mixed
        self.chars_per_token = 4
    
    def chunk_text(self, text: str) -> List[TextChunk]:
        """
        Chunk text into overlapping segments
        
        Args:
            text: Input text to chunk
            
        Returns:
            List of TextChunk objects
        """
        if not text.strip():
            return []
        
        lines = text.split('\n')
        chunks = []
        
        max_chars = self.max_tokens * self.chars_per_token
        overlap_chars = self.overlap_tokens * self.chars_per_token
        
        current_chunk = []
        current_chars = 0
        start_line = 1
        
        for i, line in enumerate(lines, start=1):
            line_chars = len(line)
            
            # If single line exceeds max, split it
            if line_chars > max_chars:
                # Save current chunk if exists
                if current_chunk:
                    chunks.append(TextChunk(
                        text='\n'.join(current_chunk),
                        start_line=start_line,
                        end_line=i - 1
                    ))
                    current_chunk = []
                    current_chars = 0
                
                # Split long line into multiple chunks
                for sub_chunk in self._split_long_line(line, max_chars):
                    chunks.append(TextChunk(
                        text=sub_chunk,
                        start_line=i,
                        end_line=i
                    ))
                
                start_line = i + 1
                continue
            
            # Check if adding this line would exceed limit
            if current_chars + line_chars > max_chars and current_chunk:
                # Save current chunk
                chunks.append(TextChunk(
                    text='\n'.join(current_chunk),
                    start_line=start_line,
                    end_line=i - 1
                ))
                
                # Start new chunk with overlap
                overlap_lines = self._get_overlap_lines(current_chunk, overlap_chars)
                current_chunk = overlap_lines + [line]
                current_chars = sum(len(l) for l in current_chunk)
                start_line = i - len(overlap_lines)
            else:
                # Add line to current chunk
                current_chunk.append(line)
                current_chars += line_chars
        
        # Save last chunk
        if current_chunk:
            chunks.append(TextChunk(
                text='\n'.join(current_chunk),
                start_line=start_line,
                end_line=len(lines)
            ))
        
        return chunks
    
    def _split_long_line(self, line: str, max_chars: int) -> List[str]:
        """Split a single long line into multiple chunks"""
        chunks = []
        for i in range(0, len(line), max_chars):
            chunks.append(line[i:i + max_chars])
        return chunks
    
    def _get_overlap_lines(self, lines: List[str], target_chars: int) -> List[str]:
        """Get last few lines that fit within target_chars for overlap"""
        overlap = []
        chars = 0
        
        for line in reversed(lines):
            line_chars = len(line)
            if chars + line_chars > target_chars:
                break
            overlap.insert(0, line)
            chars += line_chars
        
        return overlap
    
    def chunk_markdown(self, text: str) -> List[TextChunk]:
        """
        Chunk markdown text while respecting structure
        (For future enhancement: respect markdown sections)
        """
        return self.chunk_text(text)
