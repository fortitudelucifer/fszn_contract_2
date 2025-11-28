from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import generate_password_hash, check_password_hash

from .models import User
from . import db

auth_bp = Blueprint('auth', __name__)  # 模板用全局 templates 目录，不用单独指定

# 简单的登录检查装饰器，供其它模块使用
def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            flash('请先登录')
            return redirect(url_for('auth.login'))
        return view(**kwargs)
    return wrapped_view

# 允许访问内部管理页面的角色（内部员工）
INTERNAL_ROLES = {
    'boss',
    'software_engineer',
    'electrical_engineer',
    'mechanical_engineer',
    'sales',
    'service',
    'procurements',
    'finance',
}

def staff_required(view):
    """只允许内部员工访问的装饰器（客户 customer 会被拒绝）"""
    @wraps(view)
    def wrapped_view(**kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('请先登录')
            return redirect(url_for('auth.login'))

        user = User.query.get(user_id)
        if not user or user.role not in INTERNAL_ROLES:
            # 这里直接 403，后面可以再自定义提示页
            abort(403)

        return view(**kwargs)
    return wrapped_view



@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password')
        confirm = request.form.get('confirm')

        if not username or not email or not password:
            flash('请填写所有必填项')
            return render_template('auth/register.html')

        if password != confirm:
            flash('两次输入的密码不一致')
            return render_template('auth/register.html')

        # 检查是否已存在
        exists = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if exists:
            flash('用户名或邮箱已被占用')
            return render_template('auth/register.html')

        # 创建用户，密码用哈希保存
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role = 'customer'
        )
        db.session.add(user)
        db.session.commit()

        flash('注册成功，请登录')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name_or_email = (request.form.get('username') or '').strip()
        password = request.form.get('password')

        user = User.query.filter(
            (User.username == name_or_email) | (User.email == name_or_email)
        ).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            flash('登录成功')
            return redirect(url_for('home'))

        flash('用户名/邮箱或密码错误')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('已退出登录')
    return redirect(url_for('auth.login'))
