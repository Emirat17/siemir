import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import Config

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Baca DATABASE_URL saat runtime agar Railway variable injection bekerja
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url:
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url

    db.init_app(app)

    from app.routes import main
    from app.auth import auth
    app.register_blueprint(main)
    app.register_blueprint(auth)

    with app.app_context():
        db.create_all()
        _seed_default_users()

    return app

def _seed_default_users():
    """Buat akun default jika belum ada."""
    from app.models import User
    if User.query.count() == 0:
        defaults = [
            {'username': 'admin',    'nama': 'Administrator Kabupaten',
             'role': 'admin_kabupaten', 'password': 'admin123', 'fungsi': None},
            {'username': 'ppk',      'nama': 'Pejabat Pembuat Komitmen',
             'role': 'ppk',             'password': 'ppk123',   'fungsi': None},
            {'username': 'sosial',   'nama': 'Admin Fungsi Sosial',
             'role': 'admin_fungsi',    'password': 'sosial123', 'fungsi': 'Sosial'},
            {'username': 'produksi', 'nama': 'Admin Fungsi Produksi',
             'role': 'admin_fungsi',    'password': 'produksi123', 'fungsi': 'Produksi'},
        ]
        for d in defaults:
            u = User(username=d['username'], nama_lengkap=d['nama'],
                     role=d['role'], fungsi=d['fungsi'], aktif=True)
            u.set_password(d['password'])
            db.session.add(u)
        db.session.commit()
        print("✅ Akun default dibuat.")
