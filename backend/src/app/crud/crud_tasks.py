from fastcrud import FastCRUD

from ..models.task import Task
from ..schemas.task import TaskCreateInternal, TaskDelete, TaskRead, TaskUpdate, TaskUpdateInternal

CRUDTask = FastCRUD[Task, TaskCreateInternal, TaskUpdate, TaskUpdateInternal, TaskDelete, TaskRead]
crud_tasks = CRUDTask(Task)
