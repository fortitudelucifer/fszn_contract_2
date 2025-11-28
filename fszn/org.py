# -*- coding: utf-8 -*-

from functools import wraps

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, session
)

from . import db
from .models import User, Department, Person, ProjectDepartmentLeader, Task, Acceptance, Feedback, SalesInfo
from .auth import login_required, staff_required


org_bp = Blueprint('org', __name__)


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            flash('请先登录')
            return redirect(url_for('auth.login'))
        return view(**kwargs)
    return wrapped_view


@org_bp.route('/departments')
@staff_required
def list_departments():
    """部门列表"""
    user = None
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)

    departments = Department.query.order_by(Department.id.asc()).all()

    return render_template(
        'org/departments.html',
        user=user,
        departments=departments,
    )


@org_bp.route('/departments/new', methods=['GET', 'POST'])
@staff_required
def new_department():
    """新增部门"""
    user = None
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name:
            flash('部门名称不能为空')
            return render_template('org/new_department.html', user=user)

        exists = Department.query.filter_by(name=name).first()
        if exists:
            flash('该部门已存在')
            return render_template('org/new_department.html', user=user)

        dept = Department(name=name)
        db.session.add(dept)
        db.session.commit()

        flash('部门已创建')
        return redirect(url_for('org.list_departments'))

    return render_template('org/new_department.html', user=user)


@org_bp.route('/persons')
@staff_required
def list_persons():
    """人员列表"""
    user = None
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)

    persons = (
        Person.query
        .order_by(Person.id.asc())
        .all()
    )

    departments = (
        Department.query
        .order_by(Department.id.asc())
        .all()
    )

    return render_template(
        'org/persons.html',
        user=user,
        persons=persons,
        departments=departments,
    )

# 编辑人员

@org_bp.route('/persons/<int:person_id>/edit', methods=['GET', 'POST'])
@staff_required
def edit_person(person_id):
    """编辑人员信息"""
    user = None
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)

    person = Person.query.get_or_404(person_id)
    departments = (
        Department.query
        .order_by(Department.id.asc())
        .all()
    )

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        position = (request.form.get('position') or '').strip()
        dept_id = request.form.get('department_id')

        if not name:
            flash('姓名不能为空')
            return render_template(
                'org/edit_person.html',
                user=user,
                person=person,
                departments=departments,
            )

        person.name = name
        person.position = position
        person.department_id = int(dept_id) if dept_id else None

        db.session.commit()
        flash('人员信息已更新')
        return redirect(url_for('org.list_persons'))

    return render_template(
        'org/edit_person.html',
        user=user,
        person=person,
        departments=departments,
    )



# 新增人员

@org_bp.route('/persons/new', methods=['GET', 'POST'])
@staff_required
def new_person():
    """新增人员"""
    user = None
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)

    # 所有部门列表，用于下拉框
    departments = (
        Department.query
        .order_by(Department.id.asc())
        .all()
    )

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        position = (request.form.get('position') or '').strip()
        dept_id = request.form.get('department_id')

        if not name:
            flash('姓名不能为空')
            return render_template(
                'org/new_person.html',
                user=user,
                departments=departments,
            )

        department_id = int(dept_id) if dept_id else None

        person = Person(
            name=name,
            position=position,
            department_id=department_id,
        )
        db.session.add(person)
        db.session.commit()

        flash('人员已创建')
        return redirect(url_for('org.list_persons'))

    return render_template(
        'org/new_person.html',
        user=user,
        departments=departments,
    )

# 删除部门

@org_bp.route('/departments/<int:dept_id>/delete', methods=['POST'])
@staff_required
def delete_department(dept_id):
    """删除部门：如果已经被项目使用，则不允许删除"""
    dept = Department.query.get_or_404(dept_id)

    used_leader = ProjectDepartmentLeader.query.filter_by(department_id=dept.id).first()
    used_task = Task.query.filter_by(department_id=dept.id).first()

    if used_leader or used_task:
        flash('该部门已被项目使用，暂时不能删除')
        return redirect(url_for('org.list_departments'))

    db.session.delete(dept)
    db.session.commit()
    flash('部门已删除')
    return redirect(url_for('org.list_departments'))


# 删除人员

@org_bp.route('/persons/<int:person_id>/delete', methods=['POST'])
@staff_required
def delete_person(person_id):
    """删除人员：如果已经被项目使用，则不允许删除"""
    person = Person.query.get_or_404(person_id)

    used_leader = ProjectDepartmentLeader.query.filter_by(person_id=person.id).first()
    used_task = Task.query.filter_by(person_id=person.id).first()
    used_acc = Acceptance.query.filter_by(person_id=person.id).first()
    used_fb = Feedback.query.filter_by(handler_id=person.id).first()
    used_sales = SalesInfo.query.filter_by(sales_person_id=person.id).first()

    if used_leader or used_task or used_acc or used_fb or used_sales:
        flash('该人员已被项目/任务/验收/反馈/销售使用，暂时不能删除')
        return redirect(url_for('org.list_persons'))


    db.session.delete(person)
    db.session.commit()
    flash('人员已删除')
    return redirect(url_for('org.list_persons'))
