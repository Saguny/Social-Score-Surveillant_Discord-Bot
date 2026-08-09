import os

DATABASE_URL  = os.getenv('VN_DATABASE_URL') or os.getenv('DATABASE_URL', '')
PORT          = int(os.getenv('VN_EDITOR_PORT', '8765'))
HOST          = os.getenv('VN_EDITOR_HOST', '127.0.0.1')

R2_TOKEN      = os.getenv('R2_TOKEN', '')
R2_ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID', '')
R2_BUCKET     = os.getenv('R2_BUCKET', 'social-credit-gacha')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', '').rstrip('/')
