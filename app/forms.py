from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, TextAreaField, FileField, SelectField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError
from app.models import User
from datetime import datetime
import os

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is taken. Please choose a different one.')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class PostForm(FlaskForm):
    # Post Type
    post_type = SelectField('Type', choices=[
        ('Waste Walk', 'Waste Walk Action Plan'),
        ('Quality', 'Quality Follow-up Action Plan'),
        ('Safety & Environmental, Health', 'Safety & Environmental, Health'),
        ('5S', '5S')
    ], validators=[DataRequired()])
    
    # Problem Details
    problem = StringField('Problem/Opportunity', validators=[DataRequired()])
    corrective_action = StringField('Corrective Action', validators=[DataRequired()])
    
    # Images
    image_problem = FileField('Problem/Opportunity Image')
    image_corrective = FileField('Corrective Action Image')
    
    # Assignment
    responsible = StringField('Area Responsible', validators=[DataRequired()])
    project_area = StringField('Project / Area')
    
    # Dates
    date_realization = StringField('Target Date', validators=[DataRequired()])
    audit_date = StringField('Audit Date')
    
    # Audit Type
    audit_type = SelectField('Audit Type', choices=[
        ('', 'Select Audit Type'),
        ('Internal', 'Internal'),
        ('External', 'External'),
        ('Scheduled', 'Scheduled'),
        ('Random', 'Random'),
        ('Follow-up', 'Follow-up')
    ])
    
    submit = SubmitField('Post')
    
    def validate_image_problem(self, image_problem):
        if image_problem.data and hasattr(image_problem.data, 'filename') and image_problem.data.filename:
            if not allowed_file(image_problem.data.filename):
                raise ValidationError('Invalid file type for problem image.')
    
    def validate_image_corrective(self, image_corrective):
        if image_corrective.data and hasattr(image_corrective.data, 'filename') and image_corrective.data.filename:
            if not allowed_file(image_corrective.data.filename):
                raise ValidationError('Invalid file type for corrective action image.')

