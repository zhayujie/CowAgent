"""
Skill loader for discovering and loading skills from directories.
"""

import os
from pathlib import Path
from typing import List, Optional, Dict
from common.log import logger
from agent.skills.types import Skill, SkillEntry, LoadSkillsResult, SkillMetadata
from agent.skills.frontmatter import parse_frontmatter, parse_metadata, parse_boolean_value, get_frontmatter_value


class SkillLoader:
    """Loads skills from various directories."""

    def __init__(self):
        pass
    
    def load_skills_from_dir(self, dir_path: str, source: str) -> LoadSkillsResult:
        """
        Load skills from a directory.

        Discovery rules:
        - Direct .md files in the root directory
        - Recursive SKILL.md files under subdirectories

        :param dir_path: Directory path to scan
        :param source: Source identifier ('builtin' or 'custom')
        :return: LoadSkillsResult with skills and diagnostics
        """
        skills = []
        diagnostics = []
        
        if not os.path.exists(dir_path):
            diagnostics.append(f"Directory does not exist: {dir_path}")
            return LoadSkillsResult(skills=skills, diagnostics=diagnostics)
        
        if not os.path.isdir(dir_path):
            diagnostics.append(f"Path is not a directory: {dir_path}")
            return LoadSkillsResult(skills=skills, diagnostics=diagnostics)
        
        # Load skills from root-level .md files and subdirectories
        result = self._load_skills_recursive(dir_path, source, include_root_files=True)
        
        return result
    
    def _load_skills_recursive(
        self, 
        dir_path: str, 
        source: str, 
        include_root_files: bool = False
    ) -> LoadSkillsResult:
        """
        Recursively load skills from a directory.
        
        If a subdirectory contains its own SKILL.md, it is treated as a
        self-contained skill (or skill-collection) and its children are
        NOT scanned further. This prevents sub-skills inside a collection
        (e.g. style-collection/style-anjing) from being listed as
        independent top-level skills.
        
        :param dir_path: Directory to scan
        :param source: Source identifier
        :param include_root_files: Whether to include root-level .md files
        :return: LoadSkillsResult
        """
        skills = []
        diagnostics = []
        
        try:
            entries = os.listdir(dir_path)
        except Exception as e:
            diagnostics.append(f"Failed to list directory {dir_path}: {e}")
            return LoadSkillsResult(skills=skills, diagnostics=diagnostics)

        # If this directory has its own SKILL.md, load it and stop recursing.
        # The sub-directories are internal resources of this skill.
        if not include_root_files and 'SKILL.md' in entries:
            skill_md_path = os.path.join(dir_path, 'SKILL.md')
            if os.path.isfile(skill_md_path):
                skill_result = self._load_skill_from_file(skill_md_path, source)
                if skill_result.skills:
                    skills.extend(skill_result.skills)
                diagnostics.extend(skill_result.diagnostics)
                return LoadSkillsResult(skills=skills, diagnostics=diagnostics)
        
        for entry in entries:
            if entry.startswith('.'):
                continue
            
            if entry in ('node_modules', '__pycache__', 'venv', '.git'):
                continue
            
            full_path = os.path.join(dir_path, entry)
            
            if os.path.isdir(full_path):
                sub_result = self._load_skills_recursive(full_path, source, include_root_files=False)
                skills.extend(sub_result.skills)
                diagnostics.extend(sub_result.diagnostics)
                continue
            
            if not os.path.isfile(full_path):
                continue
            
            is_root_md = include_root_files and entry.endswith('.md') and entry.upper() != 'README.MD'
            
            if not is_root_md:
                continue
            
            skill_result = self._load_skill_from_file(full_path, source)
            if skill_result.skills:
                skills.extend(skill_result.skills)
            diagnostics.extend(skill_result.diagnostics)
        
        return LoadSkillsResult(skills=skills, diagnostics=diagnostics)
    
    def _load_skill_from_file(self, file_path: str, source: str) -> LoadSkillsResult:
        """
        Load a single skill from a markdown file.
        
        :param file_path: Path to the skill markdown file
        :param source: Source identifier
        :return: LoadSkillsResult
        """
        diagnostics = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            diagnostics.append(f"Failed to read skill file {file_path}: {e}")
            return LoadSkillsResult(skills=[], diagnostics=diagnostics)
        
        # Parse frontmatter
        frontmatter = parse_frontmatter(content)
        
        # Get skill name and description
        skill_dir = os.path.dirname(file_path)
        parent_dir_name = os.path.basename(skill_dir)
        
        name = frontmatter.get('name', parent_dir_name)
        description = frontmatter.get('description', '')
        
        # Normalize name (handle both string and list)
        if isinstance(name, list):
            name = name[0] if name else parent_dir_name
        elif not isinstance(name, str):
            name = str(name) if name else parent_dir_name
        
        # Normalize description (handle both string and list)
        if isinstance(description, list):
            description = ' '.join(str(d) for d in description if d)
        elif not isinstance(description, str):
            description = str(description) if description else ''
        
        # Special handling for linkai-agent: dynamically load apps from config.json
        if name == 'linkai-agent':
            description = self._load_linkai_agent_description(skill_dir, description)
        
        if not description or not description.strip():
            diagnostics.append(f"Skill {name} has no description: {file_path}")
            return LoadSkillsResult(skills=[], diagnostics=diagnostics)
        
        # Parse disable-model-invocation flag
        disable_model_invocation = parse_boolean_value(
            get_frontmatter_value(frontmatter, 'disable-model-invocation'),
            default=False
        )
        
        # Create skill object
        skill = Skill(
            name=name,
            description=description,
            file_path=file_path,
            base_dir=skill_dir,
            source=source,
            content=content,
            disable_model_invocation=disable_model_invocation,
            frontmatter=frontmatter,
        )
        
        return LoadSkillsResult(skills=[skill], diagnostics=diagnostics)
    
    def _load_linkai_agent_description(self, skill_dir: str, default_description: str) -> str:
        """
        Dynamically load LinkAI agent description from config.json
        
        :param skill_dir: Skill directory
        :param default_description: Default description from SKILL.md
        :return: Dynamic description with app list
        """
        import json
        
        config_path = os.path.join(skill_dir, "config.json")
        
        if not os.path.exists(config_path):
            logger.debug(f"[SkillLoader] linkai-agent skipped: no config.json found")
            return ""
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            apps = config.get("apps", [])
            if not apps:
                return default_description
            
            # Build dynamic description with app details
            app_descriptions = "; ".join([
                f"{app['app_name']}({app['app_code']}: {app['app_description']})"
                for app in apps
            ])
            
            return f"Call LinkAI apps/workflows. {app_descriptions}"
        
        except Exception as e:
            logger.warning(f"[SkillLoader] Failed to load linkai-agent config: {e}")
            return default_description
    
    def load_all_skills(
        self,
        builtin_dir: Optional[str] = None,
        custom_dir: Optional[str] = None,
    ) -> Dict[str, SkillEntry]:
        """
        Load skills from builtin and custom directories.

        Precedence (lowest to highest):
        1. builtin  — project root ``skills/``, shipped with the codebase
        2. custom   — workspace ``skills/``, installed via cloud console or skill creator

        Same-name custom skills override builtin ones.

        :param builtin_dir: Built-in skills directory
        :param custom_dir: Custom skills directory
        :return: Dictionary mapping skill name to SkillEntry
        """
        skill_map: Dict[str, SkillEntry] = {}
        all_diagnostics = []

        # Load builtin skills (lower precedence)
        if builtin_dir and os.path.exists(builtin_dir):
            result = self.load_skills_from_dir(builtin_dir, source='builtin')
            all_diagnostics.extend(result.diagnostics)
            for skill in result.skills:
                entry = self._create_skill_entry(skill)
                skill_map[skill.name] = entry

        # Load custom skills (higher precedence, overrides builtin)
        if custom_dir and os.path.exists(custom_dir):
            result = self.load_skills_from_dir(custom_dir, source='custom')
            all_diagnostics.extend(result.diagnostics)
            for skill in result.skills:
                entry = self._create_skill_entry(skill)
                skill_map[skill.name] = entry

        # Log diagnostics
        if all_diagnostics:
            logger.debug(f"Skill loading diagnostics: {len(all_diagnostics)} issues")
            for diag in all_diagnostics[:5]:
                logger.debug(f"  - {diag}")

        logger.debug(f"Loaded {len(skill_map)} skills total")

        return skill_map
    
    def _create_skill_entry(self, skill: Skill) -> SkillEntry:
        """
        Create a SkillEntry from a Skill with parsed metadata.
        
        :param skill: The skill to create an entry for
        :return: SkillEntry with metadata
        """
        metadata = parse_metadata(skill.frontmatter)
        
        # Parse user-invocable flag
        user_invocable = parse_boolean_value(
            get_frontmatter_value(skill.frontmatter, 'user-invocable'),
            default=True
        )
        
        return SkillEntry(
            skill=skill,
            metadata=metadata,
            user_invocable=user_invocable,
        )
