# -*- coding: utf-8 -*-
import os
from flask import Flask, render_template, session, redirect, url_for

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)

    app.config.from_object('config.Config')

    
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))


    app.config['SQLALCHEMY_DATABASE_URI'] ='mssql+pyodbc://fszn_test:fszn123!@localhost/fszn_db?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes'
    app.config['SECRET_KEY'] = 'dev' 
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 文件上传相关配置
    app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB，可调

    db.init_app(app)

    # 登录/注册
    from .auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # 项目/合同
    from .contracts import contracts_bp
    app.register_blueprint(contracts_bp)

    # 部门 & 人员
    from .org import org_bp
    app.register_blueprint(org_bp, url_prefix='/org')

    @app.route('/')
    def home():
        from .models import User
        user = None
        user_id = session.get('user_id')
        if user_id:
            user = User.query.get(user_id)
        return render_template('home.html', user=user)

    @app.context_processor
    def inject_common():
        def human_filesize(num_bytes):
            if num_bytes is None:
                return ''
            try:
                n = int(num_bytes)
            except (TypeError, ValueError):
                return str(num_bytes)

            if n < 1024:
                return f"{n} B"
            kb = n / 1024
            if kb < 1024:
                return f"{kb:.1f} KB"
            mb = kb / 1024
            return f"{mb:.1f} MB"

        return dict(
            config=app.config,
            human_filesize=human_filesize,
        )

       
    # 确保上传目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    return app
