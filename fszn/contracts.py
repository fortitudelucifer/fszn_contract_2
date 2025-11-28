# -*- coding: utf-8 -*-

from functools import wraps
from datetime import datetime, date
import os
from decimal import Decimal

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, session, send_from_directory, current_app
)

from . import db
from .auth import login_required
from .models import (
    Contract, Company, User,
    Department, Person, ProjectDepartmentLeader,
    Task, ProcurementItem, Acceptance, Payment, Invoice, Refund, Feedback,
    SalesInfo, ProjectFile
)



# 根据任务、验收、付款、反馈等情况计算项目状态

def get_contract_status(contract: Contract):
    """根据任务、验收、付款、反馈等情况计算项目状态"""
    cid = contract.id

    has_tasks = Task.query.filter_by(contract_id=cid).count() > 0
    has_acceptance = Acceptance.query.filter_by(contract_id=cid).count() > 0
    has_payments = Payment.query.filter_by(contract_id=cid).count() > 0
    has_invoices = Invoice.query.filter_by(contract_id=cid).count() > 0

    # 有未解决反馈？
    has_unresolved_feedback = Feedback.query.filter_by(
        contract_id=cid,
        is_resolved=False
    ).count() > 0

    # 规则可以慢慢打磨，现在先用一个简化版：
    if (not has_tasks) and (not has_acceptance) and (not has_payments) and (not has_invoices):
        return "未启动", "grey"

    if has_tasks and not has_acceptance:
        return "生产中", "blue"

    if has_acceptance and not has_payments:
        return "已验收，待回款", "orange"

    if has_acceptance and has_payments and has_unresolved_feedback:
        return "已回款，有未解决问题", "red"

    if has_acceptance and has_payments and not has_unresolved_feedback:
        return "已完成", "green"

    # 兜底
    return "进行中", "blue"

# 状态筛选用的映射：URL 参数值 -> 状态文本
STATUS_FILTERS = {
    'not_started': '未启动',
    'in_production': '生产中',
    'accepted_pending_payment': '已验收，待回款',
    'paid_with_issues': '已回款，有未解决问题',
    'finished': '已完成',
}



contracts_bp = Blueprint('contracts', __name__, url_prefix='/contracts')

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx'}


# 不同角色允许上传的文件类型
ROLE_ALLOWED_TYPES = {
    # 你可以根据自己 User.role 的实际值调整这些 key
    'admin': {'contract', 'tech', 'drawing', 'invoice', 'ticket'},
    'boss': {'contract', 'tech', 'drawing', 'invoice', 'ticket'},
    'software_engineer': {'drawing', 'tech'},
    'mechanical_engineer': {'drawing', 'tech'},
    'electrical_engineer': {'drawing', 'tech'},
    'sales': {'contract', 'tech', 'ticket'},
    'finance': {'invoice'},
    'procurement': {'invoice'},
    # 默认角色（找不到时）
    'default': {'contract', 'tech', 'drawing', 'invoice', 'ticket'},
}


def allowed_file(filename: str) -> bool:
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def get_role_allowed_types(user: User):
    role = (user.role or '').strip().lower() if user and user.role else ''
    # 简单处理一下常见中文/英文角色映射可以在这里加
    return ROLE_ALLOWED_TYPES.get(role, ROLE_ALLOWED_TYPES['default'])


def sanitize_part(text: str) -> str:
    """用于文件名中某一段的安全处理：去掉空格和特殊字符"""
    if not text:
        return ''
    # 替换空格为下划线，去掉不适合出现在文件名中的字符
    invalid = '\\/:*?"<>|'
    for ch in invalid:
        text = text.replace(ch, '')
    text = text.replace(' ', '_')
    return text


def generate_file_name(contract: Contract, file_type: str, version: str, author: str, original_filename: str) -> str:
    """按照约定规则生成文件名：
    客户公司_项目编号_合同编号_合同名称_上传日期_文件类型_版本号_作者.扩展名
    """
    if '.' in original_filename:
        ext = '.' + original_filename.rsplit('.', 1)[1].lower()
    else:
        ext = ''

    company_name = sanitize_part(contract.company.name if contract.company else '')
    project_code = sanitize_part(contract.project_code or '')
    contract_number = sanitize_part(contract.contract_number or '')
    contract_name = sanitize_part(contract.name or '')
    today_str = datetime.utcnow().strftime('%Y%m%d')
    file_type_part = sanitize_part(file_type)
    version_part = sanitize_part(version or 'V1')
    author_part = sanitize_part(author or 'unknown')

    parts = [
        company_name or 'NoCompany',
        project_code or 'NoProject',
        contract_number or 'NoContractNo',
        contract_name or 'NoName',
        today_str,
        file_type_part,
        version_part,
        author_part,
    ]
    base = "_".join(parts)
    # 长度太长时可以简单截断
    if len(base) > 180:
        base = base[:180]
    return base + ext



def parse_date(date_str):
    """将 'YYYY-MM-DD' 字符串转成 date 对象，失败返回 None"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return None


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            flash('请先登录')
            return redirect(url_for('auth.login'))
        return view(**kwargs)
    return wrapped_view

# 项目/合同列表

@contracts_bp.route('/')
@login_required
def list_contracts():
    """项目/合同列表"""
    user = None
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)

    # 读取查询参数（全部为可选）
    company_kw = (request.args.get('company') or '').strip()
    project_kw = (request.args.get('project') or '').strip()
    contract_no_kw = (request.args.get('contract_no') or '').strip()
    sales_kw = (request.args.get('sales') or '').strip()
    leader_kw = (request.args.get('leader') or '').strip()
    status_param = (request.args.get('status') or '').strip()

     # 取值约定：
    #   '' 或 None              -> 按创建时间(新→旧)
    #   'created_at_asc'        -> 按创建时间(旧→新)
    #   'deal_date_desc'        -> 按成交日期(新→旧)
    #   'deal_date_asc'         -> 按成交日期(旧→新)
    #   'status_asc' / 'status_desc' -> 按状态文本排序（Python 层）
    order_param = (request.args.get('order') or '').strip()

    # 基础查询
    query = Contract.query

    if company_kw:
        query = query.join(Company).filter(Company.name.ilike(f"%{company_kw}%"))

    if project_kw:
        query = query.filter(Contract.project_code.ilike(f"%{project_kw}%"))

    if contract_no_kw:
        query = query.filter(Contract.contract_number.ilike(f"%{contract_no_kw}%"))

    if sales_kw:
        # 只在需要时关联销售信息和销售负责人
        query = (
            query.join(SalesInfo, SalesInfo.contract_id == Contract.id)
                 .join(Person, Person.id == SalesInfo.sales_person_id)
                 .filter(Person.name.ilike(f"%{sales_kw}%"))
        )

    if leader_kw:
        # 只在需要时关联部门负责人
        query = (
            query.join(ProjectDepartmentLeader, ProjectDepartmentLeader.contract_id == Contract.id)
                 .join(Person, Person.id == ProjectDepartmentLeader.person_id)
                 .filter(Person.name.ilike(f"%{leader_kw}%"))
        )

    # 根据排序参数设置数据库层排序（创建时间 / 成交日期）
    # 说明：
    # - created_at：在 Contract 表上直接排序
    # - deal_date：需要关联 SalesInfo
    if order_param in ('deal_date_asc', 'deal_date_desc'):
        # 如果前面没有按销售人员过滤，这里补一个外连接
        if not sales_kw:
            query = query.outerjoin(SalesInfo, SalesInfo.contract_id == Contract.id)

        if order_param == 'deal_date_asc':
            query = query.order_by(SalesInfo.deal_date.asc(), Contract.created_at.desc())
        else:
            # 默认成交日期(新→旧)
            query = query.order_by(SalesInfo.deal_date.desc(), Contract.created_at.desc())
    else:
        # 默认按创建时间排序
        if order_param == 'created_at_asc':
            query = query.order_by(Contract.created_at.asc())
        else:
            # 创建时间(新→旧)
            query = query.order_by(Contract.created_at.desc())

    contracts = query.all()


    # 去重（避免因 join 产生重复）
    unique_contracts = []
    seen_ids = set()
    for c in contracts:
        if c.id in seen_ids:
            continue
        seen_ids.add(c.id)
        unique_contracts.append(c)
    contracts = unique_contracts

    # 1）构造：每个合同的 “部门 -> [负责人列表]”
    leaders_by_contract = {}
    for c in contracts:
        dept_map = {}
        # 这里用 department_id / person_id 排序，遵守“用 id 控制顺序”的原则
        for l in sorted(
            c.department_leaders,
            key=lambda x: ((x.department_id or 0), (x.person_id or 0))
        ):
            if not l.department or not l.person:
                continue
            dept_name = l.department.name
            dept_map.setdefault(dept_name, []).append(l.person)
        leaders_by_contract[c.id] = dept_map

    # 2）为每个合同计算状态（get_contract_status）
    status_map = {}
    for c in contracts:
        st_text, st_level = get_contract_status(c)
        status_map[c.id] = dict(text=st_text, level=st_level)

    # 3）按状态参数进行二次过滤（在 Python 层处理）
    status_filter_text = STATUS_FILTERS.get(status_param) if status_param else None
    if status_filter_text:
        filtered_contracts = []
        filtered_status_map = {}
        for c in contracts:
            st = status_map.get(c.id)
            if not st:
                continue
            if st['text'] == status_filter_text:
                filtered_contracts.append(c)
                filtered_status_map[c.id] = st
        contracts = filtered_contracts
        status_map = filtered_status_map

    # 4）按状态文本排序（在 Python 层处理）
    if order_param in ('status_asc', 'status_desc'):
        reverse = (order_param == 'status_desc')

        def status_key(c: Contract):
            st = status_map.get(c.id)
            # 没状态的排在最后
            return st['text'] if st and st.get('text') else 'ZZZZZZ'

        contracts = sorted(contracts, key=status_key, reverse=reverse)


    return render_template(
        'contracts/list.html',
        user=user,
        contracts=contracts,
        leaders_by_contract=leaders_by_contract,
        statuses=status_map,
        # 把当前查询参数传过去，方便模板回填
        company_kw=company_kw,
        project_kw=project_kw,
        contract_no_kw=contract_no_kw,
        sales_kw=sales_kw,
        leader_kw=leader_kw,
        status_param=status_param,
        order_param=order_param,
    )
    )



# 新建项目/合同

@contracts_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_contract():
    """新建项目/合同"""
    user = None
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)

    if request.method == 'POST':
        company_name = (request.form.get('company_name') or '').strip()
        project_code = (request.form.get('project_code') or '').strip()
        contract_number = (request.form.get('contract_number') or '').strip()
        name = (request.form.get('name') or '').strip()
        client_manager = (request.form.get('client_manager') or '').strip()
        client_contact = (request.form.get('client_contact') or '').strip()
        our_manager = (request.form.get('our_manager') or '').strip()

        if not company_name or not project_code or not contract_number or not name:
            flash('客户公司名称、项目编号、合同编号、合同名称都是必填项')
            return render_template('contracts/new.html', user=user)

        # 查找或创建公司
        company = Company.query.filter_by(name=company_name).first()
        if not company:
            company = Company(name=company_name)
            db.session.add(company)
            db.session.flush()

        # 检查项目编号全局唯一
        exists = Contract.query.filter_by(project_code=project_code).first()
        if exists:
            flash('该项目编号已存在，请更换一个唯一的项目编号')
            return render_template('contracts/new.html', user=user)

        contract = Contract(
            company_id=company.id,
            project_code=project_code,
            contract_number=contract_number,
            name=name,
            client_manager=client_manager,
            client_contact=client_contact,
            our_manager=our_manager,
            created_by_id=user_id,
        )

        db.session.add(contract)
        db.session.commit()

        flash('项目/合同已创建')
        return redirect(url_for('contracts.list_contracts'))

    return render_template('contracts/new.html', user=user)


@contracts_bp.route('/<int:contract_id>/leaders', methods=['GET', 'POST'])
@login_required
def manage_leaders(contract_id):
    """管理某个项目/合同的部门负责人（可多名）"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    # 处理新增负责人
    if request.method == 'POST':
        department_id_raw = request.form.get('department_id')
        person_id_raw = request.form.get('person_id')

        if not department_id_raw or not person_id_raw:
            flash('请选择部门和负责人')
        else:
            try:
                department_id = int(department_id_raw)
                person_id = int(person_id_raw)
            except ValueError:
                flash('部门或负责人选择无效')
            else:
                # 检查是否已存在同一记录
                exists = ProjectDepartmentLeader.query.filter_by(
                    contract_id=contract.id,
                    department_id=department_id,
                    person_id=person_id
                ).first()
                if exists:
                    flash('该负责人在本项目此部门下已存在')
                else:
                    leader = ProjectDepartmentLeader(
                        contract_id=contract.id,
                        department_id=department_id,
                        person_id=person_id,
                    )
                    db.session.add(leader)
                    db.session.commit()
                    flash('已添加部门负责人')

        return redirect(url_for('contracts.manage_leaders', contract_id=contract.id))

    # GET 请求：展示当前负责人列表 + 添加表单
    # 为了让你可以用 id 控制顺序，我这里按照 Department.id / Person.id 排序
    leaders = (
        ProjectDepartmentLeader.query
        .filter_by(contract_id=contract.id)
        .join(Department, ProjectDepartmentLeader.department_id == Department.id)
        .join(Person, ProjectDepartmentLeader.person_id == Person.id)
        .order_by(Department.id.asc(), Person.id.asc())
        .all()
    )

    departments = Department.query.order_by(Department.id.asc()).all()
    persons = Person.query.order_by(Person.id.asc()).all()

    return render_template(
        'contracts/leaders.html',
        user=user,
        contract=contract,
        leaders=leaders,
        departments=departments,
        persons=persons,
    )


@contracts_bp.route('/<int:contract_id>/leaders/<int:leader_id>/delete', methods=['POST'])
@login_required
def delete_leader(contract_id, leader_id):
    """删除某条部门负责人记录"""
    contract = Contract.query.get_or_404(contract_id)

    leader = ProjectDepartmentLeader.query.filter_by(
        id=leader_id,
        contract_id=contract.id
    ).first_or_404()

    db.session.delete(leader)
    db.session.commit()
    flash('该负责人已移除')

    return redirect(url_for('contracts.manage_leaders', contract_id=contract.id))

@contracts_bp.route('/<int:contract_id>/tasks', methods=['GET', 'POST'])
@login_required
def manage_tasks(contract_id):
    """管理某个项目的任务/生产进度"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    if request.method == 'POST':
        department_id_raw = request.form.get('department_id')
        person_id_raw = request.form.get('person_id')
        title = (request.form.get('title') or '').strip()
        start_date_str = (request.form.get('start_date') or '').strip()
        end_date_str = (request.form.get('end_date') or '').strip()
        status = (request.form.get('status') or '').strip() or '未开始'
        remarks = (request.form.get('remarks') or '').strip()

        if not department_id_raw or not title or not start_date_str:
            flash('部门、任务名称、开始日期为必填')
            return redirect(url_for('contracts.manage_tasks', contract_id=contract.id))

        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)

        try:
            department_id = int(department_id_raw)
        except ValueError:
            flash('部门选择无效')
            return redirect(url_for('contracts.manage_tasks', contract_id=contract.id))

        person_id = None
        if person_id_raw:
            try:
                person_id = int(person_id_raw)
            except ValueError:
                person_id = None

        task = Task(
            contract_id=contract.id,
            department_id=department_id,
            person_id=person_id,
            title=title,
            start_date=start_date,
            end_date=end_date,
            status=status,
            remarks=remarks,
        )
        db.session.add(task)
        db.session.commit()
        flash('任务已创建')
        return redirect(url_for('contracts.manage_tasks', contract_id=contract.id))

    # GET: 展示任务列表和新增表单
    tasks = (
        Task.query
        .filter_by(contract_id=contract.id)
        .join(Department, Task.department_id == Department.id)
        .order_by(Department.id.asc(), Task.start_date.asc(), Task.id.asc())
        .all()
    )
    departments = Department.query.order_by(Department.id.asc()).all()
    persons = Person.query.order_by(Person.id.asc()).all()

    return render_template(
        'contracts/tasks.html',
        user=user,
        contract=contract,
        tasks=tasks,
        departments=departments,
        persons=persons,
    )


@contracts_bp.route('/<int:contract_id>/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(contract_id, task_id):
    contract = Contract.query.get_or_404(contract_id)
    task = Task.query.filter_by(id=task_id, contract_id=contract.id).first_or_404()
    db.session.delete(task)
    db.session.commit()
    flash('任务已删除')
    return redirect(url_for('contracts.manage_tasks', contract_id=contract.id))


# 采购

@contracts_bp.route('/<int:contract_id>/procurements', methods=['GET', 'POST'])
@login_required
def manage_procurements(contract_id):
    """管理某个项目的采购清单"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    if request.method == 'POST':
        item_name = (request.form.get('item_name') or '').strip()
        quantity_raw = (request.form.get('quantity') or '').strip()
        unit = (request.form.get('unit') or '').strip()
        expected_date_str = (request.form.get('expected_date') or '').strip()
        status = (request.form.get('status') or '').strip() or '未采购'
        # 🔹 ：负责人 ID
        person_id_raw = (request.form.get('person_id') or '').strip()
        remarks = (request.form.get('remarks') or '').strip()

        if not item_name:
            flash('物料名称为必填')
            return redirect(url_for('contracts.manage_procurements', contract_id=contract.id))

        try:
            quantity = int(quantity_raw) if quantity_raw else 0
        except ValueError:
            quantity = 0

        expected_date = parse_date(expected_date_str)

        # 🔹 ：解析负责人 ID
        person_id = None
        if person_id_raw:
            try:
                person_id = int(person_id_raw)
            except ValueError:
                person_id = None

        item = ProcurementItem(
            contract_id=contract.id,
            item_name=item_name,
            quantity=quantity,
            unit=unit,
            expected_date=expected_date,
            status=status,
            remarks=remarks,
            person_id=person_id,  # 🔹 新增
        )
        db.session.add(item)
        db.session.commit()
        flash('采购项已添加')
        return redirect(url_for('contracts.manage_procurements', contract_id=contract.id))

    items = ProcurementItem.query.filter_by(contract_id=contract.id).order_by(
        ProcurementItem.id.asc()
    ).all()

    # 🔹 仿照任务/验收：查询所有人员
    persons = Person.query.order_by(Person.id.asc()).all()

    return render_template(
        'contracts/procurements.html',
        user=user,
        contract=contract,
        items=items,
        persons=persons,  # 🔹 关键：把 persons 传给模板
    )


@contracts_bp.route('/<int:contract_id>/procurements/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_procurement(contract_id, item_id):
    contract = Contract.query.get_or_404(contract_id)
    item = ProcurementItem.query.filter_by(id=item_id, contract_id=contract.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash('采购项已删除')
    return redirect(url_for('contracts.manage_procurements', contract_id=contract.id))

# 验收
@contracts_bp.route('/<int:contract_id>/acceptances', methods=['GET', 'POST'])
@login_required
def manage_acceptances(contract_id):
    """管理某个项目的验收记录"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    if request.method == 'POST':
        stage_name = (request.form.get('stage_name') or '').strip()
        person_id_raw = (request.form.get('person_id') or '').strip()
        date_str = (request.form.get('date') or '').strip()
        status = (request.form.get('status') or '').strip() or '进行中'
        remarks = (request.form.get('remarks') or '').strip()

        if not stage_name or not date_str:
            flash('阶段名称和日期为必填')
            return redirect(url_for('contracts.manage_acceptances', contract_id=contract.id))

        d = parse_date(date_str)
        if not d:
            flash('日期格式错误')
            return redirect(url_for('contracts.manage_acceptances', contract_id=contract.id))

        person_id = None
        if person_id_raw:
            try:
                person_id = int(person_id_raw)
            except ValueError:
                person_id = None

        acc = Acceptance(
            contract_id=contract.id,
            stage_name=stage_name,
            person_id=person_id,
            date=d,
            status=status,
            remarks=remarks,
        )
        db.session.add(acc)
        db.session.commit()
        flash('验收记录已添加')
        return redirect(url_for('contracts.manage_acceptances', contract_id=contract.id))

    records = (
        Acceptance.query.filter_by(contract_id=contract.id)
        .order_by(Acceptance.date.asc(), Acceptance.id.asc())
        .all()
    )
    persons = Person.query.order_by(Person.id.asc()).all()

    return render_template(
        'contracts/acceptances.html',
        user=user,
        contract=contract,
        records=records,
        persons=persons,
    )


@contracts_bp.route('/<int:contract_id>/acceptances/<int:acc_id>/delete', methods=['POST'])
@login_required
def delete_acceptance(contract_id, acc_id):
    contract = Contract.query.get_or_404(contract_id)
    acc = Acceptance.query.filter_by(id=acc_id, contract_id=contract.id).first_or_404()
    db.session.delete(acc)
    db.session.commit()
    flash('验收记录已删除')
    return redirect(url_for('contracts.manage_acceptances', contract_id=contract.id))

# 销售管理

@contracts_bp.route('/<int:contract_id>/sales', methods=['GET', 'POST'])
@login_required
def manage_sales(contract_id):
    """管理某个项目的销售信息（报价、成交日期、销售负责人）"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    # 查询当前已有的销售记录（0 或 1 条）
    sales = SalesInfo.query.filter_by(contract_id=contract.id).first()

    if request.method == 'POST':
        quote_amount_raw = (request.form.get('quote_amount') or '').strip()
        quote_date_str = (request.form.get('quote_date') or '').strip()
        deal_date_str = (request.form.get('deal_date') or '').strip()
        sales_person_id_raw = (request.form.get('sales_person_id') or '').strip()
        remarks = (request.form.get('remarks') or '').strip()

        # 金额可以为空，为空代表尚未确定
        quote_amount = None
        if quote_amount_raw:
            try:
                quote_amount = float(quote_amount_raw)
            except ValueError:
                flash('报价金额格式错误')
                return redirect(url_for('contracts.manage_sales', contract_id=contract.id))

        quote_date = parse_date(quote_date_str) if quote_date_str else None
        if quote_date_str and not quote_date:
            flash('报价日期格式错误')
            return redirect(url_for('contracts.manage_sales', contract_id=contract.id))

        deal_date = parse_date(deal_date_str) if deal_date_str else None
        if deal_date_str and not deal_date:
            flash('成交日期格式错误')
            return redirect(url_for('contracts.manage_sales', contract_id=contract.id))

        sales_person_id = None
        if sales_person_id_raw:
            try:
                sales_person_id = int(sales_person_id_raw)
            except ValueError:
                sales_person_id = None

        if sales:
            # 更新
            sales.quote_amount = quote_amount
            sales.quote_date = quote_date
            sales.deal_date = deal_date
            sales.sales_person_id = sales_person_id
            sales.remarks = remarks or None
            flash('销售信息已更新')
        else:
            # 创建
            sales = SalesInfo(
                contract_id=contract.id,
                quote_amount=quote_amount,
                quote_date=quote_date,
                deal_date=deal_date,
                sales_person_id=sales_person_id,
                remarks=remarks or None,
            )
            db.session.add(sales)
            flash('销售信息已创建')

        db.session.commit()
        return redirect(url_for('contracts.manage_sales', contract_id=contract.id))

    # GET：展示现有销售信息 + 编辑表单
    persons = Person.query.order_by(Person.id.asc()).all()

    return render_template(
        'contracts/sales.html',
        user=user,
        contract=contract,
        sales=sales,
        persons=persons,
    )


@contracts_bp.route('/<int:contract_id>/sales/delete', methods=['POST'])
@login_required
def delete_sales(contract_id):
    """删除某项目的销售信息记录"""
    contract = Contract.query.get_or_404(contract_id)
    sales = SalesInfo.query.filter_by(contract_id=contract.id).first()
    if not sales:
        flash('当前项目没有销售信息可删除')
        return redirect(url_for('contracts.manage_sales', contract_id=contract.id))

    db.session.delete(sales)
    db.session.commit()
    flash('销售信息已删除')
    return redirect(url_for('contracts.manage_sales', contract_id=contract.id))

# 项目总览
@contracts_bp.route('/<int:contract_id>/overview')
@login_required
def contract_overview(contract_id):
    """项目 / 合同总览页面"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    # 部门负责人列表
    leaders = (
        ProjectDepartmentLeader.query
        .filter_by(contract_id=contract.id)
        .order_by(ProjectDepartmentLeader.id.asc())
        .all()
    )

    # 销售信息（可能没有）
    sales = SalesInfo.query.filter_by(contract_id=contract.id).first()

    # 各模块计数（不做金额统计，避免字段名对不上）
    tasks_count = Task.query.filter_by(contract_id=contract.id).count()
    proc_count = ProcurementItem.query.filter_by(contract_id=contract.id).count()
    acc_count = Acceptance.query.filter_by(contract_id=contract.id).count()
    pay_count = Payment.query.filter_by(contract_id=contract.id).count()
    inv_count = Invoice.query.filter_by(contract_id=contract.id).count()
    refund_count = Refund.query.filter_by(contract_id=contract.id).count()
    fb_count = Feedback.query.filter_by(contract_id=contract.id).count()
    files_count = ProjectFile.query.filter_by(contract_id=contract.id, is_deleted=False).count()

    # 当前项目状态（文本 + 颜色级别）
    status_text, status_level = get_contract_status(contract)

    #  财务汇总
    zero = Decimal('0.00')

    # 报价金额（作为合同金额使用）
    quote_amount = None
    if sales and getattr(sales, 'quote_amount', None) is not None:
        quote_amount = sales.quote_amount

    # 已收款总额 / 退款总额 / 实收净额
    paid_total = sum((p.amount or zero) for p in contract.payments)
    refund_total = sum((r.amount or zero) for r in contract.refunds)
    net_received = paid_total - refund_total

    # 已开票总额
    invoiced_total = sum((inv.amount or zero) for inv in contract.invoices)

    # 剩余应收 / 剩余待开票
    receivable_remaining = None
    invoice_remaining = None
    if quote_amount is not None:
        receivable_remaining = quote_amount - net_received
        invoice_remaining = quote_amount - invoiced_total

    finance = dict(
        quote_amount=quote_amount,
        paid_total=paid_total,
        refund_total=refund_total,
        net_received=net_received,
        invoiced_total=invoiced_total,
        receivable_remaining=receivable_remaining,
        invoice_remaining=invoice_remaining,
    )

    return render_template(
        'contracts/overview.html',
        user=user,
        contract=contract,
        leaders=leaders,
        sales=sales,
        stats=dict(
            tasks=tasks_count,
            proc=proc_count,
            acc=acc_count,
            pay=pay_count,
            inv=inv_count,
            refund=refund_count,
            fb=fb_count,
            files=files_count,
        ),
        status_text=status_text,
        status_level=status_level,
        finance=finance,  # 传进模板
    )





# 付款管理
@contracts_bp.route('/<int:contract_id>/payments', methods=['GET', 'POST'])
@login_required
def manage_payments(contract_id):
    """管理某个项目的客户付款记录"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    if request.method == 'POST':
        amount_raw = (request.form.get('amount') or '').strip()
        date_str = (request.form.get('date') or '').strip()
        method = (request.form.get('method') or '').strip()
        remarks = (request.form.get('remarks') or '').strip()

        if not amount_raw or not date_str:
            flash('金额和日期为必填')
            return redirect(url_for('contracts.manage_payments', contract_id=contract.id))

        try:
            amount = float(amount_raw)
        except ValueError:
            flash('金额格式错误')
            return redirect(url_for('contracts.manage_payments', contract_id=contract.id))

        d = parse_date(date_str)
        if not d:
            flash('日期格式错误')
            return redirect(url_for('contracts.manage_payments', contract_id=contract.id))

        p = Payment(
            contract_id=contract.id,
            amount=amount,
            date=d,
            method=method,
            remarks=remarks,
        )
        db.session.add(p)
        db.session.commit()
        flash('付款记录已添加')
        return redirect(url_for('contracts.manage_payments', contract_id=contract.id))

    records = Payment.query.filter_by(contract_id=contract.id).order_by(
        Payment.date.asc(), Payment.id.asc()
    ).all()

    return render_template(
        'contracts/payments.html',
        user=user,
        contract=contract,
        records=records,
    )


@contracts_bp.route('/<int:contract_id>/payments/<int:pay_id>/delete', methods=['POST'])
@login_required
def delete_payment(contract_id, pay_id):
    contract = Contract.query.get_or_404(contract_id)
    p = Payment.query.filter_by(id=pay_id, contract_id=contract.id).first_or_404()
    db.session.delete(p)
    db.session.commit()
    flash('付款记录已删除')
    return redirect(url_for('contracts.manage_payments', contract_id=contract.id))

# 发票管理
@contracts_bp.route('/<int:contract_id>/invoices', methods=['GET', 'POST'])
@login_required
def manage_invoices(contract_id):
    """管理某个项目的开票记录"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    if request.method == 'POST':
        invoice_number = (request.form.get('invoice_number') or '').strip()
        amount_raw = (request.form.get('amount') or '').strip()
        date_str = (request.form.get('date') or '').strip()
        remarks = (request.form.get('remarks') or '').strip()

        if not amount_raw or not date_str:
            flash('金额和日期为必填')
            return redirect(url_for('contracts.manage_invoices', contract_id=contract.id))

        try:
            amount = float(amount_raw)
        except ValueError:
            flash('金额格式错误')
            return redirect(url_for('contracts.manage_invoices', contract_id=contract.id))

        d = parse_date(date_str)
        if not d:
            flash('日期格式错误')
            return redirect(url_for('contracts.manage_invoices', contract_id=contract.id))

        inv = Invoice(
            contract_id=contract.id,
            invoice_number=invoice_number or None,
            amount=amount,
            date=d,
            remarks=remarks,
        )
        db.session.add(inv)
        db.session.commit()
        flash('开票记录已添加')
        return redirect(url_for('contracts.manage_invoices', contract_id=contract.id))

    records = Invoice.query.filter_by(contract_id=contract.id).order_by(
        Invoice.date.asc(), Invoice.id.asc()
    ).all()

    return render_template(
        'contracts/invoices.html',
        user=user,
        contract=contract,
        records=records,
    )


@contracts_bp.route('/<int:contract_id>/invoices/<int:inv_id>/delete', methods=['POST'])
@login_required
def delete_invoice(contract_id, inv_id):
    contract = Contract.query.get_or_404(contract_id)
    inv = Invoice.query.filter_by(id=inv_id, contract_id=contract.id).first_or_404()
    db.session.delete(inv)
    db.session.commit()
    flash('开票记录已删除')
    return redirect(url_for('contracts.manage_invoices', contract_id=contract.id))

# 退款管理
@contracts_bp.route('/<int:contract_id>/refunds', methods=['GET', 'POST'])
@login_required
def manage_refunds(contract_id):
    """管理某个项目的退款记录"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    if request.method == 'POST':
        amount_raw = (request.form.get('amount') or '').strip()
        date_str = (request.form.get('date') or '').strip()
        reason = (request.form.get('reason') or '').strip()
        remarks = (request.form.get('remarks') or '').strip()

        if not amount_raw or not date_str:
            flash('金额和日期为必填')
            return redirect(url_for('contracts.manage_refunds', contract_id=contract.id))

        try:
            amount = float(amount_raw)
        except ValueError:
            flash('金额格式错误')
            return redirect(url_for('contracts.manage_refunds', contract_id=contract.id))

        d = parse_date(date_str)
        if not d:
            flash('日期格式错误')
            return redirect(url_for('contracts.manage_refunds', contract_id=contract.id))

        r = Refund(
            contract_id=contract.id,
            amount=amount,
            date=d,
            reason=reason,
            remarks=remarks,
        )
        db.session.add(r)
        db.session.commit()
        flash('退款记录已添加')
        return redirect(url_for('contracts.manage_refunds', contract_id=contract.id))

    records = Refund.query.filter_by(contract_id=contract.id).order_by(
        Refund.date.asc(), Refund.id.asc()
    ).all()

    return render_template(
        'contracts/refunds.html',
        user=user,
        contract=contract,
        records=records,
    )


@contracts_bp.route('/<int:contract_id>/refunds/<int:ref_id>/delete', methods=['POST'])
@login_required
def delete_refund(contract_id, ref_id):
    contract = Contract.query.get_or_404(contract_id)
    r = Refund.query.filter_by(id=ref_id, contract_id=contract.id).first_or_404()
    db.session.delete(r)
    db.session.commit()
    flash('退款记录已删除')
    return redirect(url_for('contracts.manage_refunds', contract_id=contract.id))

# 客户反馈
@contracts_bp.route('/<int:contract_id>/feedbacks', methods=['GET', 'POST'])
@login_required
def manage_feedbacks(contract_id):
    """管理某个项目的客户反馈及处理情况"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    if request.method == 'POST':
        content = (request.form.get('content') or '').strip()
        handler_id_raw = (request.form.get('handler_id') or '').strip()
        result = (request.form.get('result') or '').strip()
        completion_date_str = (request.form.get('completion_date') or '').strip()

        if not content:
            flash('反馈内容为必填')
            return redirect(url_for('contracts.manage_feedbacks', contract_id=contract.id))

        handler_id = None
        if handler_id_raw:
            try:
                handler_id = int(handler_id_raw)
            except ValueError:
                handler_id = None

        completion_time = None
        if completion_date_str:
            d = parse_date(completion_date_str)
            if d:
                completion_time = datetime.combine(d, datetime.min.time())

        fb = Feedback(
            contract_id=contract.id,
            content=content,
            handler_id=handler_id,
            result=result or None,
            completion_time=completion_time,
        )
        db.session.add(fb)
        db.session.commit()
        flash('反馈记录已添加')
        return redirect(url_for('contracts.manage_feedbacks', contract_id=contract.id))

    records = Feedback.query.filter_by(contract_id=contract.id).order_by(
        Feedback.feedback_time.asc(), Feedback.id.asc()
    ).all()
    persons = Person.query.order_by(Person.id.asc()).all()

    return render_template(
        'contracts/feedbacks.html',
        user=user,
        contract=contract,
        records=records,
        persons=persons,
       # feedbacks=feedbacks,
    )


@contracts_bp.route('/<int:contract_id>/feedbacks/<int:feedback_id>/delete', methods=['POST'])
@login_required
def delete_feedback(contract_id, feedback_id):
    contract = Contract.query.get_or_404(contract_id)
    fb = Feedback.query.filter_by(id=feedback_id, contract_id=contract.id).first_or_404()
    db.session.delete(fb)
    db.session.commit()
    flash('反馈记录已删除')
    return redirect(url_for('contracts.manage_feedbacks', contract_id=contract.id))

# 标记反馈为已解决 / 未解决

@contracts_bp.route('/<int:contract_id>/feedbacks/<int:feedback_id>/resolve', methods=['POST'])
@login_required
def resolve_feedback(contract_id, feedback_id):
    """标记反馈为已解决"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)
    fb = Feedback.query.filter_by(id=feedback_id, contract_id=contract.id).first_or_404()

    fb.is_resolved = True
    fb.completion_time = datetime.utcnow()   # 解决时间写入 completion_time
    db.session.commit()

    flash('该反馈已标记为“已解决”。')
    return redirect(url_for('contracts.manage_feedbacks', contract_id=contract.id))


@contracts_bp.route('/<int:contract_id>/feedbacks/<int:feedback_id>/unresolve', methods=['POST'])
@login_required
def unresolve_feedback(contract_id, feedback_id):
    """标记反馈为未解决"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)
    fb = Feedback.query.filter_by(id=feedback_id, contract_id=contract.id).first_or_404()

    fb.is_resolved = False
    fb.completion_time = None
    db.session.commit()

    flash('该反馈已标记为“未解决”。')
    return redirect(url_for('contracts.manage_feedbacks', contract_id=contract.id))



# 管理页面（列表+上传）

@contracts_bp.route('/<int:contract_id>/files', methods=['GET', 'POST'])
@login_required
def manage_files(contract_id):
    """管理某个项目的文件：上传 / 列表 / 删除"""
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)

    # 只显示未删除的文件
    files = (
        ProjectFile.query
        .filter_by(contract_id=contract.id, is_deleted=False)
        .order_by(ProjectFile.created_at.asc(), ProjectFile.id.asc())
        .all()
    )

    if request.method == 'POST':
        if not user:
            flash('请先登录')
            return redirect(url_for('auth.login'))

        uploaded_file = request.files.get('file')
        file_type = (request.form.get('file_type') or '').strip()
        version = (request.form.get('version') or '').strip() or 'V1'
        is_public_raw = request.form.get('is_public')

        if not uploaded_file or uploaded_file.filename == '':
            flash('请选择要上传的文件')
            return redirect(url_for('contracts.manage_files', contract_id=contract.id))

        # 对图纸 file_type='drawing' 放宽限制，不检查扩展名
        if file_type != 'drawing' and not allowed_file(uploaded_file.filename):
            flash('不支持的文件类型（非图纸文件请使用常见文档/图片格式）')
            return redirect(url_for('contracts.manage_files', contract_id=contract.id))

        # 校验角色是否允许上传这种类型
        allowed_types = get_role_allowed_types(user)
        if file_type not in allowed_types:
            flash('当前角色不允许上传此类型文件')
            return redirect(url_for('contracts.manage_files', contract_id=contract.id))

        # 文件是否公开：只允许合同/技术文档可公开
        is_public = False
        if is_public_raw == 'y' and file_type in ('contract', 'tech'):
            is_public = True

        original_filename = uploaded_file.filename
        author = user.username  # 如果你实际字段叫 name，就改成 user.name
        stored_filename = generate_file_name(
            contract, file_type, version, author, original_filename
        )

        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, stored_filename)

        uploaded_file.save(filepath)

        file_size = os.path.getsize(filepath)
        content_type = uploaded_file.mimetype

        pf = ProjectFile(
            contract_id=contract.id,
            uploader_id=user.id,
            file_type=file_type,
            version=version,
            author=author,
            original_filename=original_filename,
            stored_filename=stored_filename,
            content_type=content_type,
            file_size=file_size,
            is_public=is_public,
            owner_role=user.role,
        )

        db.session.add(pf)
        db.session.commit()

        flash('文件上传成功')
        return redirect(url_for('contracts.manage_files', contract_id=contract.id))

    # GET：展示列表 & 上传表单
    return render_template(
        'contracts/files.html',
        user=user,
        contract=contract,
        files=files,
    )


# 下载文件（权限检查）

@contracts_bp.route('/<int:contract_id>/files/<int:file_id>/download')
@login_required
def download_file(contract_id, file_id):
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)
    pf = ProjectFile.query.filter_by(
        id=file_id,
        contract_id=contract.id,
        is_deleted=False
    ).first_or_404()

    # 权限：简单版
    # - 管理员 / 老板 / 软件工程师：可以下载所有
    # - 其它员工：只能下载 owner_role == 自己 role 的文件
    # - 客户角色：只能下载 is_public=True 且 file_type in ('contract', 'tech')
    role = (user.role or '').strip().lower() if user and user.role else ''

    if role in ('admin', 'boss', 'software_engineer'):
        pass  # 全部允许
    elif role == 'customer':
        if not (pf.is_public and pf.file_type in ('contract', 'tech')):
            flash('你没有权限下载此文件')
            return redirect(url_for('contracts.manage_files', contract_id=contract.id))
    else:
        # 内部普通员工
        if pf.owner_role and pf.owner_role != user.role:
            flash('你只能下载自己部门上传的文件')
            return redirect(url_for('contracts.manage_files', contract_id=contract.id))

    upload_folder = current_app.config['UPLOAD_FOLDER']
    return send_from_directory(
        upload_folder,
        pf.stored_filename,
        as_attachment=True,
        download_name=pf.stored_filename #  pf.original_filename 用原始文件名下载
    )


# 删除文件（软删除+风险提示）

@contracts_bp.route('/<int:contract_id>/files/<int:file_id>/delete', methods=['POST'])
@login_required
def delete_file(contract_id, file_id):
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None

    contract = Contract.query.get_or_404(contract_id)
    pf = ProjectFile.query.filter_by(
        id=file_id,
        contract_id=contract.id,
        is_deleted=False
    ).first_or_404()

    # 权限控制：上传者 / 管理员 / 老板 可以删
    role = (user.role or '').strip().lower() if user and user.role else ''
    if not user or (user.id != pf.uploader_id and role not in ('admin', 'boss')):
        flash('你没有权限删除此文件')
        return redirect(url_for('contracts.manage_files', contract_id=contract.id))

    pf.is_deleted = True
    db.session.commit()

    flash('文件已标记为删除（普通用户将无法再访问）')
    return redirect(url_for('contracts.manage_files', contract_id=contract.id))