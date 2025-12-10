import argparse
from app import app, db
from app.models import User
from werkzeug.security import generate_password_hash

def create_admin(username, password):
    with app.app_context():
        hashed_password = generate_password_hash(password)
        admin = User(username=username, password=hashed_password, role='admin')
        db.session.add(admin)
        db.session.commit()
        print(f"Admin user '{username}' created successfully.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a new admin user.')
    parser.add_argument('username', type=str, help='The username for the new admin user.')
    parser.add_argument('password', type=str, help='The password for the new admin user.')
    args = parser.parse_args()
    create_admin(args.username, args.password)
