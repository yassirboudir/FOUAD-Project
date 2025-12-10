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
    problem = StringField('Problem', validators=[DataRequired()])
    cause = StringField('Cause', validators=[DataRequired()])
    corrective_action = StringField('Corrective Action', validators=[DataRequired()])
    image_file = FileField('Add Image', validators=[])
    responsible = StringField('Responsible', validators=[DataRequired()])
    date_realization = StringField('Date of Realization', validators=[DataRequired()])
    status = SelectField('Status', choices=[('Open', 'Open'), ('In Progress', 'In Progress'), ('Completed', 'Completed')], validators=[DataRequired()])
    submit = SubmitField('Post')
    
    def validate_image_file(self, image_file):
        if image_file.data:
            filename = image_file.data.filename
            if not allowed_file(filename):
                raise ValidationError('Invalid file type. Please upload an image file (png, jpg, jpeg, gif, bmp, webp).')
