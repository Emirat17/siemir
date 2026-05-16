"""
config.py — Konfigurasi SIEMIR
Otomatis pakai PostgreSQL jika DATABASE_URL tersedia (Railway),
pakai SQLite jika tidak (lokal/development).
"""
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'siemir-bps-meranti-2026-dev-key')

    # Database: Railway set DATABASE_URL otomatis saat add PostgreSQL plugin
    DATABASE_URL = os.environ.get('DATABASE_URL', '')

    if DATABASE_URL:
        # Railway/PostgreSQL — ganti postgres:// ke postgresql:// (SQLAlchemy requirement)
        if DATABASE_URL.startswith('postgres://'):
            DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        # Lokal — pakai SQLite di folder instance/
        basedir = os.path.abspath(os.path.dirname(__file__))
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'instance', 'database.db')

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Upload
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

config = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
    'default':     ProductionConfig,
}
