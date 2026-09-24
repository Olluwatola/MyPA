from fastcrud import FastCRUD

from ..models.task import Task
from ..schemas.task import TaskCreateInternal, TaskDelete, TaskRead, TaskUpdate, TaskUpdateInternal

# `delete()` is a soft delete (Task has is_deleted/deleted_at); `db_delete()` would hard
# delete and is never called. FastCRUD does not filter soft-deleted rows on reads — pass
# `is_deleted=False` explicitly.
CRUDTask = FastCRUD[Task, TaskCreateInternal, TaskUpdate, TaskUpdateInternal, TaskDelete, TaskRead]
crud_tasks = CRUDTask(Task)
