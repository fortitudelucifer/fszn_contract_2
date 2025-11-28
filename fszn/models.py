# -*- coding: utf-8 -*-
from datetime import datetime, date
from . import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(50), default='customer')  # 建议加一个默认角色


class Company(db.Model):
    __tablename__ = 'companies'

    id = db.Column(db.Integer, primary_key=True)
    # 客户公司名称
    name = db.Column(db.String(200), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 一家公司有多个项目/合同
    contracts = db.relationship('Contract', back_populates='company')


class Contract(db.Model):
    __tablename__ = 'contracts'

    id = db.Column(db.Integer, primary_key=True)

    # 所属客户公司
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    company = db.relationship('Company', back_populates='contracts')

    # 项目编号：全局唯一（不区分公司）
    project_code = db.Column(db.String(50), nullable=False, unique=True)
    # 合同编号
    contract_number = db.Column(db.String(50), nullable=False)
    # 合同名称
    name = db.Column(db.String(200), nullable=False)

    # 客户公司负责人 / 联系方式 / 我方负责人
    client_manager = db.Column(db.String(100))
    client_contact = db.Column(db.String(200))
    our_manager = db.Column(db.String(100))

    # 简单状态（后面可以细化）
    status = db.Column(db.String(50), default='新建')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 创建人（内部员工）
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', backref='contracts')


class Department(db.Model):
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    # 部门名称：采购 / 机械 / 电气 / 软件 ...
    name = db.Column(db.String(50), unique=True, nullable=False)


class Person(db.Model):
    __tablename__ = 'persons'

    id = db.Column(db.Integer, primary_key=True)
    # 人员姓名（工程师、销售、采购等）
    name = db.Column(db.String(100), nullable=False)
    # 职位 / 角色（可选：如“采购工程师”、“机械工程师”、“销售”等）
    position = db.Column(db.String(100))

    # 🔹 新增：人员所属部门
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    department = db.relationship('Department', backref='persons')

class ProjectDepartmentLeader(db.Model):
    __tablename__ = 'project_department_leaders'

    id = db.Column(db.Integer, primary_key=True)

    # 所属项目/合同
    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)
    # 所属部门
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    # 负责人（人员）
    person_id = db.Column(db.Integer, db.ForeignKey('persons.id'), nullable=False)

    contract = db.relationship('Contract', backref='department_leaders')
    department = db.relationship('Department', backref='project_leaders')
    person = db.relationship('Person', backref='project_departments')

    # 保证：同一个项目 + 部门 + 人员 不会重复记录
    __table_args__ = (
        db.UniqueConstraint(
            'contract_id', 'department_id', 'person_id',
            name='uq_contract_dept_person'
        ),
    )

class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)

    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey('persons.id'), nullable=True)

    title = db.Column(db.String(200), nullable=False)      # 任务名称
    start_date = db.Column(db.Date, nullable=False)        # 开始日期
    end_date = db.Column(db.Date, nullable=True)           # 完成日期
    status = db.Column(db.String(50), nullable=False, default='未开始')  # 未开始 / 进行中 / 已完成
    remarks = db.Column(db.String(500))                    # 备注 / 需求

    contract = db.relationship('Contract', backref='tasks')
    department = db.relationship('Department', backref='tasks')
    person = db.relationship('Person', backref='tasks')


class ProcurementItem(db.Model):
    __tablename__ = 'procurement_items'

    id = db.Column(db.Integer, primary_key=True)

    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)

    item_name = db.Column(db.String(200), nullable=False)          # 物料名称
    quantity = db.Column(db.Integer, nullable=False, default=0)    # 数量
    unit = db.Column(db.String(50))                                # 单位（件/套/米...）
    expected_date = db.Column(db.Date, nullable=True)              # 预计到货日期
    status = db.Column(db.String(50), nullable=False, default='未采购')  # 未采购 / 已下单 / 运输中 / 已到货 等
    remarks = db.Column(db.String(500))                            # 备注

    contract = db.relationship('Contract', backref='procurement_items')


class Acceptance(db.Model):
    __tablename__ = 'acceptances'

    id = db.Column(db.Integer, primary_key=True)

    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)
    stage_name = db.Column(db.String(100), nullable=False)          # 阶段名称
    person_id = db.Column(db.Integer, db.ForeignKey('persons.id'), nullable=True)  # 验收负责人
    date = db.Column(db.Date, nullable=False)                       # 验收日期
    status = db.Column(db.String(50), nullable=False, default='进行中')  # 进行中 / 通过 / 不通过
    remarks = db.Column(db.String(500))                             # 备注

    contract = db.relationship('Contract', backref='acceptances')
    person = db.relationship('Person', backref='acceptances')


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)

    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)

    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)  # 付款金额
    date = db.Column(db.Date, nullable=False)                         # 付款日期
    method = db.Column(db.String(50))                                 # 付款方式
    remarks = db.Column(db.String(500))                               # 备注

    contract = db.relationship('Contract', backref='payments')


class Invoice(db.Model):
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)

    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)

    invoice_number = db.Column(db.String(100), unique=True, nullable=True)  # 发票编号（可选唯一）
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)       # 开票金额
    date = db.Column(db.Date, nullable=False)                              # 开票日期
    remarks = db.Column(db.String(500))                                    # 备注

    contract = db.relationship('Contract', backref='invoices')


class Refund(db.Model):
    __tablename__ = 'refunds'

    id = db.Column(db.Integer, primary_key=True)

    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)

    amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)   # 退款金额
    date = db.Column(db.Date, nullable=False)                          # 退款日期
    reason = db.Column(db.String(200))                                 # 退款原因
    remarks = db.Column(db.String(500))                                # 备注

    contract = db.relationship('Contract', backref='refunds')


class Feedback(db.Model):
    __tablename__ = 'feedbacks'

    id = db.Column(db.Integer, primary_key=True)

    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)

    content = db.Column(db.Text, nullable=False)                       # 客户反馈内容
    feedback_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # 记录时间（创建时自动填）
    handler_id = db.Column(db.Integer, db.ForeignKey('persons.id'), nullable=True)   # 处理工程师
    result = db.Column(db.Text)                                        # 处理结果
    completion_time = db.Column(db.DateTime, nullable=True)           # 处理完成时间

    # 🔹 新增：是否已解决
    is_resolved = db.Column(db.Boolean, default=False)

    contract = db.relationship('Contract', backref='feedbacks')
    handler = db.relationship('Person', backref='feedbacks')

class SalesInfo(db.Model):
    __tablename__ = 'sales_infos'

    id = db.Column(db.Integer, primary_key=True)

    # 一份合同对应一条销售信息：报价 + 成交
    contract_id = db.Column(
        db.Integer,
        db.ForeignKey('contracts.id'),
        nullable=False,
        unique=True  # 保证一个合同最多一条销售记录
    )

    quote_amount = db.Column(db.Numeric(10, 2), nullable=True)  # 报价金额
    quote_date = db.Column(db.Date, nullable=True)              # 报价日期
    deal_date = db.Column(db.Date, nullable=True)               # 成交日期
    sales_person_id = db.Column(db.Integer, db.ForeignKey('persons.id'), nullable=True)  # 销售负责人
    remarks = db.Column(db.String(500))                         # 备注

    contract = db.relationship(
        'Contract',
        backref=db.backref('sales_info', uselist=False)
    )
    sales_person = db.relationship('Person', backref='sales_infos')

class ProjectFile(db.Model):
    __tablename__ = 'project_files'

    id = db.Column(db.Integer, primary_key=True)

    # 关联合同（合同里有项目编号和客户公司，可以通过 contract 拿到）
    contract_id = db.Column(db.Integer, db.ForeignKey('contracts.id'), nullable=False)

    # 上传者（内部用户）
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # 文件类别：contract / tech / drawing / invoice / ticket ...
    file_type = db.Column(db.String(50), nullable=False)

    # 版本号，比如 V1 / V2 / 1.0 等
    version = db.Column(db.String(20))

    # 作者（加入命名规则中的“作者”，通常就是上传人的名字/用户名）
    author = db.Column(db.String(100))

    # 文件原始名（用户电脑上的名称）
    original_filename = db.Column(db.String(255), nullable=False)
    # 系统生成的安全文件名（磁盘上的文件名，包含我们设计的命名规则）
    stored_filename = db.Column(db.String(255), nullable=False)

    # MIME 类型（如 application/pdf）
    content_type = db.Column(db.String(100))
    # 文件大小（字节）
    file_size = db.Column(db.Integer)

    # 是否公开给客户下载（只对合同/技术文档生效）
    is_public = db.Column(db.Boolean, default=False)

    # 拥有部门/角色，用于限制“只能下载自己部门的文件”
    owner_role = db.Column(db.String(50))

    # 软删除标记
    is_deleted = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract = db.relationship('Contract', backref='files')
    uploader = db.relationship('User', backref='uploaded_files')
