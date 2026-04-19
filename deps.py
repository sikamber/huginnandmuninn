from dataclasses import dataclass

from inbox import InboxStore
from quests import QuestLineStore, QuestStore
from subjects import SubjectStore
from tasks import TaskStore


@dataclass
class AppDeps:
    tasks: TaskStore
    subjects: SubjectStore
    quests: QuestStore
    quest_lines: QuestLineStore
    inbox: InboxStore
