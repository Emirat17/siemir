import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    # Ganti dengan string acak yang panjang untuk keamanan
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'ganti-dengan-kunci-rahasia-anda'

    # Database: Gunakan PostgreSQL di produksi, SQLite di lokal
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url:
        # Fix PostgreSQL URL scheme (Railway uses postgres:// but SQLAlchemy needs postgresql://)
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        SQLALCHEMY_DATABASE_URI = database_url
    else:
        # SQLite untuk development
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'database.db')
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
