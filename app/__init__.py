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
    from app.se2026 import se2026
    app.register_blueprint(main)
    app.register_blueprint(auth)
    app.register_blueprint(se2026)

    with app.app_context():
        db.create_all()
        _migrasi_kolom_baru()
        _seed_default_users()

    return app

def _migrasi_kolom_baru():
    """Tambah / perlebar kolom di tabel yang sudah ada (safe migration)."""
    from sqlalchemy import text, inspect as sa_inspect
    inspector = sa_inspect(db.engine)
    tables    = inspector.get_table_names()

    # Kolom BARU yang perlu ditambahkan jika belum ada
    tambah = [
        ('kontrak_se2026', 'gelombang', 'INTEGER'),
        ('kontrak_se2026', 'kelas',     'VARCHAR(20)'),
        ('kontrak_se2026', 'nik',       'VARCHAR(30)'),
    ]

    # Kolom yang sudah ada tapi perlu diperlebar tipenya
    perlebar = [
        ('wilayah_se2026',     'kode_kecamatan', 'VARCHAR(100)'),
        ('wilayah_se2026',     'kode_desa',      'VARCHAR(100)'),
        ('ppl_diawasi_se2026', 'kode_kecamatan', 'VARCHAR(100)'),
        ('ppl_diawasi_se2026', 'kode_desa',      'VARCHAR(100)'),
    ]

    with db.engine.begin() as conn:
        # ADD COLUMN untuk kolom baru
        for tabel, kolom, tipe in tambah:
            if tabel not in tables:
                continue
            cols = [c['name'] for c in inspector.get_columns(tabel)]
            if kolom not in cols:
                try:
                    conn.execute(text(
                        f'ALTER TABLE "{tabel}" ADD COLUMN "{kolom}" {tipe}'
                    ))
                    print(f'✅ Migrasi ADD: {tabel}.{kolom}')
                except Exception as e:
                    print(f'⚠️  Migrasi ADD {tabel}.{kolom}: {e}')

        # ALTER COLUMN TYPE untuk kolom yang perlu diperlebar
        for tabel, kolom, tipe in perlebar:
            if tabel not in tables:
                continue
            try:
                conn.execute(text(
                    f'ALTER TABLE "{tabel}" ALTER COLUMN "{kolom}" TYPE {tipe}'
                ))
                print(f'✅ Migrasi ALTER: {tabel}.{kolom} → {tipe}')
            except Exception as e:
                print(f'⚠️  Migrasi ALTER {tabel}.{kolom}: {e}')


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
