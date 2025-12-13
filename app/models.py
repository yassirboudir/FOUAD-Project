from datetime import datetime
from app import db, login_manager
from flask_login import UserMixin

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='viewer')
    posts = db.relationship('Post', backref='author', lazy=True)

    def __repr__(self):
        return f"User('{self.username}', '{self.role}')"

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Post Type
    post_type = db.Column(db.String(50), nullable=False, default='Waste Walk')
    # Problem/Opportunity
    problem = db.Column(db.String(200), nullable=False)
    cause = db.Column(db.String(200), nullable=False)
    corrective_action = db.Column(db.String(200), nullable=False)
    # Images - separate for problem and corrective action
    image_file = db.Column(db.String(100), nullable=True, default='default.jpg')  # Legacy support
    image_problem = db.Column(db.String(100), nullable=True)  # Problem/Opportunity image
    image_corrective = db.Column(db.String(100), nullable=True)  # Corrective action image
    # Assignment
    responsible = db.Column(db.String(100), nullable=False)
    area = db.Column(db.String(100), nullable=True)
    project = db.Column(db.String(100), nullable=True)
    # Dates
    date_realization = db.Column(db.DateTime, nullable=False)
    date_created = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    audit_date = db.Column(db.DateTime, nullable=True)
    # Audit info
    audit_type = db.Column(db.String(50), nullable=True)
    # Status
    status = db.Column(db.String(20), nullable=False, default='Open')
    # Relationships
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comments = db.relationship('Comment', backref='post', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f"Post('{self.problem}', '{self.date_realization}')"


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    date_posted = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user = db.relationship('User', backref='comments')

    def __repr__(self):
        return f"Comment('{self.content[:20]}...', '{self.date_posted}')"


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(50), nullable=False)  # 'created', 'updated', 'deleted', 'commented', 'status_changed'
    target_type = db.Column(db.String(20), nullable=False)  # 'post', 'comment', 'user'
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship('User', backref='activities')

    def __repr__(self):
        return f"ActivityLog('{self.action}', '{self.target_type}', '{self.timestamp}')"
