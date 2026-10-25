import os
from app import create_app

env = os.environ.get('FLASK_ENV', 'development')
app = create_app(env)

if __name__ == '__main__':
    # Run development server on port 5000
    app.run(host='127.0.0.1', port=5000, debug=True)
