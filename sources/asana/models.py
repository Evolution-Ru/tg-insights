"""
Модели данных для Asana
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class AsanaTask:
    """Модель задачи Asana"""
    gid: str
    name: str
    notes: Optional[str] = None
    completed: bool = False
    assignee: Optional[str] = None
    assignee_name: Optional[str] = None
    due_on: Optional[str] = None
    created_at: Optional[str] = None
    modified_at: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None
    stories: Optional[List[str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь"""
        return {
            "gid": self.gid,
            "name": self.name,
            "notes": self.notes,
            "completed": self.completed,
            "assignee": self.assignee,
            "assignee_name": self.assignee_name,
            "due_on": self.due_on,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "custom_fields": self.custom_fields,
            "stories": self.stories
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AsanaTask':
        """Создает из словаря"""
        assignee_data = data.get('assignee', {})
        if isinstance(assignee_data, dict):
            assignee = assignee_data.get('gid')
            assignee_name = assignee_data.get('name')
        else:
            assignee = assignee_data
            assignee_name = None
        
        return cls(
            gid=data.get('gid', ''),
            name=data.get('name', ''),
            notes=data.get('notes'),
            completed=data.get('completed', False),
            assignee=assignee,
            assignee_name=assignee_name,
            due_on=data.get('due_on'),
            created_at=data.get('created_at'),
            modified_at=data.get('modified_at'),
            custom_fields=data.get('custom_fields'),
            stories=data.get('stories')
        )


@dataclass
class AsanaProject:
    """Модель проекта Asana"""
    gid: str
    name: str
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь"""
        return {
            "gid": self.gid,
            "name": self.name,
            "notes": self.notes
        }

