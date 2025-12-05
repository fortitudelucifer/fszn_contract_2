# -*- coding: utf-8 -*-
"""
财务相关的业务服务函数。

设计目的：
- 把统计某个合同的财务汇总”集中到一个地方；
- 视图层只依赖这个接口，后续如果你要暂时“关掉所有资金相关逻辑”
  可以只改这个文件（例如返回空或脱敏数据），而不用到处改视图。
  以后如果要“临时不展示真实资金数据”，只要在这个函数里改成返回空/0/脱敏数据；
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import date

from ..models import Contract, SalesInfo


ZERO = Decimal('0.00')


def get_contract_finance_summary(contract: Contract,
                                 sales: Optional[SalesInfo] = None) -> Dict[str, Any]:
    """
    计算单个合同的财务汇总信息。

    返回的字典字段：
        - quote_amount: 报价金额（合同金额），可能为 None
        - paid_total: 已收款总额
        - refund_total: 退款总额
        - net_received: 实收净额 = 已收款 - 退款
        - invoiced_total: 已开票总额
        - receivable_remaining: 剩余应收（可能为 None）
        - invoice_remaining: 剩余待开票（可能为 None）

    说明：
    - 调用方如果已经查过 SalesInfo，可以通过 sales 参数传进来，避免重复查询；
    - 如果 sales 为 None，这里会自行根据 contract_id 查询。
    """
    # 如果没传销售信息，这里自己查一遍
    if sales is None:
        sales = SalesInfo.query.filter_by(contract_id=contract.id).first()

    # 报价金额（作为合同金额使用）
    quote_amount = None
    if sales and getattr(sales, 'quote_amount', None) is not None:
        quote_amount = sales.quote_amount

    # 已收款总额 / 退款总额 / 实收净额
    paid_total = sum((p.amount or ZERO) for p in contract.payments)
    refund_total = sum((r.amount or ZERO) for r in contract.refunds)
    net_received = paid_total - refund_total

    # 已开票总额
    invoiced_total = sum((inv.amount or ZERO) for inv in contract.invoices)

    # 剩余应收 / 剩余待开票（报价为空时，这两个也保持 None）
    receivable_remaining = None
    invoice_remaining = None
    if quote_amount is not None:
        receivable_remaining = quote_amount - net_received
        invoice_remaining = quote_amount - invoiced_total

    return dict(
        quote_amount=quote_amount,
        paid_total=paid_total,
        refund_total=refund_total,
        net_received=net_received,
        invoiced_total=invoiced_total,
        receivable_remaining=receivable_remaining,
        invoice_remaining=invoice_remaining,
    )


# ---------------------- 付款（Payment） ----------------------


def create_payment(
    contract: Contract,
    amount: float,
    pay_date: date,
    method: str | None,
    remarks: str | None,
) -> Payment:
    """
    为给定合同创建一条付款记录（不提交事务，调用方负责 commit）。

    返回新建的 Payment 对象（已 flush，有 id）。
    """
    p = Payment(
        contract_id=contract.id,
        amount=amount,
        date=pay_date,
        method=(method or None),
        remarks=(remarks or None),
    )
    db.session.add(p)
    db.session.flush()  # 需要 p.id 用于后续写日志
    return p


def delete_payment(contract: Contract, pay_id: int) -> Payment:
    """
    删除指定合同下的一条付款记录（不提交事务，调用方负责 commit）。

    返回被删除的 Payment 对象（对象仍可读取字段，直到事务提交）。
    """
    p = Payment.query.filter_by(id=pay_id, contract_id=contract.id).first_or_404()
    db.session.delete(p)
    return p


# ---------------------- 开票（Invoice） ----------------------


def create_invoice(
    contract: Contract,
    invoice_number: str | None,
    amount: float,
    inv_date: date,
    remarks: str | None,
) -> Invoice:
    """
    为给定合同创建一条开票记录（不提交事务，调用方负责 commit）。
    """
    inv = Invoice(
        contract_id=contract.id,
        invoice_number=(invoice_number or None),
        amount=amount,
        date=inv_date,
        remarks=(remarks or None),
    )
    db.session.add(inv)
    db.session.flush()
    return inv


def delete_invoice(contract: Contract, inv_id: int) -> Invoice:
    """
    删除指定合同下的一条开票记录（不提交事务，调用方负责 commit）。
    """
    inv = Invoice.query.filter_by(id=inv_id, contract_id=contract.id).first_or_404()
    db.session.delete(inv)
    return inv


# ---------------------- 退款（Refund） ----------------------


def create_refund(
    contract: Contract,
    amount: float,
    refund_date: date,
    reason: str | None,
    remarks: str | None,
) -> Refund:
    """
    为给定合同创建一条退款记录（不提交事务，调用方负责 commit）。
    """
    refund = Refund(
        contract_id=contract.id,
        amount=amount,
        date=refund_date,
        reason=(reason or None),
        remarks=(remarks or None),
    )
    db.session.add(refund)
    db.session.flush()
    return refund


def delete_refund(contract: Contract, refund_id: int) -> Refund:
    """
    删除指定合同下的一条退款记录（不提交事务，调用方负责 commit）。
    """
    refund = Refund.query.filter_by(id=refund_id, contract_id=contract.id).first_or_404()
    db.session.delete(refund)
    return refund