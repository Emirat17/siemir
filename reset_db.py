"""
Jalankan sekali untuk migrasi database ke struktur terbaru.
Data petugas TETAP ada. Kontrak, kegiatan, dan tabel user akan dibuat ulang.
"""
from app import create_app, db
from app.models import Petugas, Kontrak, Kegiatan, NomorUrut, DaftarKegiatan, BAST, BASTKegiatan, User

app = create_app()
with app.app_context():
    BASTKegiatan.__table__.drop(db.engine, checkfirst=True)
    BAST.__table__.drop(db.engine, checkfirst=True)
    DaftarKegiatan.__table__.drop(db.engine, checkfirst=True)
    Kegiatan.__table__.drop(db.engine, checkfirst=True)
    Kontrak.__table__.drop(db.engine, checkfirst=True)
    NomorUrut.__table__.drop(db.engine, checkfirst=True)
    User.__table__.drop(db.engine, checkfirst=True)
    db.create_all()

    db.session.add(NomorUrut(jenis='SPK',  terakhir=148))
    db.session.add(NomorUrut(jenis='BAST', terakhir=148))
    db.session.commit()

    print("✅ Database diperbarui.")
    print("   Akun default dibuat otomatis saat server pertama kali dijalankan.")
