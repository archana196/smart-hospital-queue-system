import os
from app import create_app

env = os.environ.get('FLASK_ENV', 'development')
app = create_app(env)

if __name__ == '__main__':
    # Host and port configurable via environment variables (e.g. for ESP8266 local Wi-Fi connectivity)
    host = os.environ.get('FLASK_RUN_HOST') or os.environ.get('HOST') or '127.0.0.1'
    port = int(os.environ.get('FLASK_RUN_PORT') or os.environ.get('PORT') or 5000)
    debug = os.environ.get('FLASK_DEBUG', '1').lower() in ('1', 'true', 'yes')
    app.run(host=host, port=port, debug=debug)
