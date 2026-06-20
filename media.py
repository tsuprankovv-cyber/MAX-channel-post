"""
MAX Channel Poster Bot — точка входа
"""
import os
import sys
from aiohttp import web
from web.server import create_app

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    print(f"🌐 Starting on port {port}")
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=port, access_log=None)
