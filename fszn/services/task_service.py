# -*- coding: utf-8 -*-
"""
任务（Task）相关业务逻辑的 Service。

目标：
- 把“创建 / 更新 / 删除任务”的核心逻辑放到这里；
- 视图只做表单解析 + 权限校验 + 调用 service + 日志 + commit；
- 以后生产流程改动（比如任务字段、状态流转规则）可以集中改这里。
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Dict, Any

from .. import db
from ..models import Contract, Task


def create_task(
    contract: Contract,
    name: str,
    department_id: Optional[int] = None,
    person_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Task:
    """
    为指定合同创建一条任务记录（不提交事务，调用方负责 commit）。

    说明：
    - contract: 必填，任务必然挂在某个合同下；
    - 其他字段根据你 models.Task 中已有字段对齐；
    - 若将来 Task 增加字段（优先级、类型等），可以在这里统一扩展。
    """
    t = Task(
        contract_id=contract.id,
        name=name,
        department_id=department_id,
        person_id=person_id,
        start_date=start_date,
        end_date=end_date,
        status=status,
        remarks=remarks,
    )
    db.session.add(t)
    db.session.flush()  # 需要 t.id 用于后续写操作日志
    return t


def update_task(
    task: Task,
    *,
    name: Optional[str] = None,
    department_id: Optional[int] = None,
    person_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Task:
    """
    更新任务的若干字段（不提交事务，调用方负责 commit）。

    - 哪些字段不为 None，就更新哪些字段；
    - 哪些字段传 None，保持原值不动；
    - 这样视图层可以非常简洁地做“部分更新”。
    """
    if name is not None:
        task.name = name
    if department_id is not None:
        task.department_id = department_id
    if person_id is not None:
        task.person_id = person_id
    if start_date is not None:
        task.start_date = start_date
    if end_date is not None:
        task.end_date = end_date
    if status is not None:
        task.status = status
    if remarks is not None:
        task.remarks = remarks

    db.session.flush()
    return task


def delete_task(contract: Contract, task_id: int) -> Task:
    """
    删除指定合同下的一条任务记录（不提交事务，调用方负责 commit）。

    返回被删除的 Task 对象（在事务提交前依然可以访问字段，用于写日志）。
    """
    task = Task.query.filter_by(id=task_id, contract_id=contract.id).first_or_404()
    db.session.delete(task)
    return task
