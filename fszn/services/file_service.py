# -*- coding: utf-8 -*-
"""
文件相关业务逻辑的 Service：

- 文件下载权限判断 + 日志信息准备
- 文件删除权限判断 + 日志信息准备

视图层只需：
- 调用 evaluate_file_download / evaluate_file_delete
- 根据返回结果决定：是否放行、flash 提示、写 OperationLog、提交事务
"""

from __future__ import annotations

from typing import Optional, Dict, Any, Tuple
from datetime import date
from ..models import User, Contract, ProjectFile


def _get_role(user: Optional[User]) -> str:
    """统一获取用户角色的小工具：全部转为小写字符串。"""
    return (user.role or "").strip().lower() if user and user.role else ""


def evaluate_file_download(
    user: Optional[User],
    contract: Contract,
    pf: ProjectFile,
) -> Dict[str, Any]:
    """
    评估当前用户对指定文件的下载权限，并返回：

    {
        "allowed": bool,              # 是否允许下载
        "flash_message": str | None,  # 若不允许，提示文案；允许时为 None
        "log_action": str,            # file.download 或 file.download_denied
        "log_message": str,           # 日志说明文本
        "log_extra": dict,            # 日志 extra_data
    }
    """
    role = _get_role(user)

    # 默认：允许下载
    allowed = True
    flash_message: Optional[str] = None
    log_action = "file.download"
    log_message = f"下载文件：{pf.original_filename}"
    log_extra = {
        "contract_id": contract.id,
        "file_type": pf.file_type,
        "version": pf.version,
        "is_public": pf.is_public,
    }

    # ------ 权限规则 ------

    if role in ("admin", "boss", "software_engineer"):
        # 完全放行
        return dict(
            allowed=True,
            flash_message=None,
            log_action=log_action,
            log_message=log_message,
            log_extra=log_extra,
        )

    if role == "customer":
        # 客户：只能下载公开的合同/技术文档
        if not (pf.is_public and pf.file_type in ("contract", "tech")):
            allowed = False
            flash_message = "你没有权限下载此文件"
            log_action = "file.download_denied"
            log_message = "客户尝试下载未公开文件"
            log_extra = {
                "contract_id": contract.id,
                "file_type": pf.file_type,
                "is_public": pf.is_public,
            }
    else:
        # 内部普通员工：只能下载 owner_role == 自己 role 的文件
        if pf.owner_role and user and pf.owner_role != user.role:
            allowed = False
            flash_message = "你只能下载自己部门上传的文件"
            log_action = "file.download_denied"
            log_message = "员工尝试下载非本部门文件"
            log_extra = {
                "contract_id": contract.id,
                "file_type": pf.file_type,
                "owner_role": pf.owner_role,
                "user_role": user.role if user and user.role else None,
            }

    return dict(
        allowed=allowed,
        flash_message=flash_message,
        log_action=log_action,
        log_message=log_message,
        log_extra=log_extra,
    )


def evaluate_file_delete(
    user: Optional[User],
    contract: Contract,
    pf: ProjectFile,
) -> Dict[str, Any]:
    """
    评估当前用户对文件“软删除”的权限，并返回：

    {
        "allowed": bool,              # 是否允许删除
        "flash_message": str | None,  # 若不允许，提示文案
        "log_action": str,            # file.delete_soft 或 file.delete_denied
        "log_message": str,
        "log_extra": dict,
    }

    规则：
    - 上传者 / admin / boss 可以删除
    - 其它用户删除 -> 记 file.delete_denied
    """
    role = _get_role(user)

    allowed = True
    flash_message: Optional[str] = None
    log_action = "file.delete_soft"
    log_message = f"软删除文件：{pf.original_filename}"
    log_extra = {
        "contract_id": contract.id,
        "stored_filename": pf.stored_filename,
        "file_type": pf.file_type,
    }

    if (not user) or (user.id != pf.uploader_id and role not in ("admin", "boss")):
        allowed = False
        flash_message = "你没有权限删除此文件"
        log_action = "file.delete_denied"
        log_message = "无权限删除文件"
        log_extra = {
            "contract_id": contract.id,
            "stored_filename": pf.stored_filename,
            "file_type": pf.file_type,
            "uploader_id": pf.uploader_id,
            "user_id": user.id if user else None,
            "user_role": user.role if user and user.role else None,
        }

    return dict(
        allowed=allowed,
        flash_message=flash_message,
        log_action=log_action,
        log_message=log_message,
        log_extra=log_extra,
    )
