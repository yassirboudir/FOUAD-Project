import os
import secrets
import io
from PIL import Image
from flask import render_template, url_for, flash, redirect, request, send_file, make_response
from app import app, db
from app.forms import RegistrationForm, LoginForm, PostForm
from app.models import User, Post, Comment, ActivityLog
from flask_login import login_user, current_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch


def log_activity(action, target_type, target_id=None, details=None):
    """Helper function to log user activities"""
    user_id = current_user.id if current_user.is_authenticated else None
    activity = ActivityLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details
    )
    db.session.add(activity)
    db.session.commit()

def save_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    
    # Ensure the uploads directory exists
    upload_dir = os.path.join(app.root_path, 'static/uploads')
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(upload_dir, picture_fn)
    
    # Resize image to multiple sizes for different uses
    output_size = (500, 500)  # Larger size for post viewing
    i = Image.open(form_picture)
    
    # Preserve aspect ratio
    i.thumbnail(output_size, Image.Resampling.LANCZOS)
    i.save(picture_path)

    return picture_fn

from functools import wraps
from flask import abort

def roles_required(*roles):
    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return wrapper

@app.route("/")
@app.route("/home")
def home():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '', type=str)
    status_filter = request.args.get('status', 'all', type=str)
    
    posts_query = Post.query
    
    # Apply search filter
    if search:
        posts_query = posts_query.filter(
            Post.problem.contains(search) | 
            Post.cause.contains(search) | 
            Post.corrective_action.contains(search) |
            Post.responsible.contains(search)
        )
    
    # Apply status filter
    if status_filter != 'all':
        posts_query = posts_query.filter(Post.status == status_filter)
    
    posts = posts_query.order_by(Post.date_realization.desc()).paginate(
        page=page, per_page=5)
    
    return render_template('index.html', posts=posts, search=search, status_filter=status_filter)

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = generate_password_hash(form.password.data)
        user = User(username=form.username.data, password=hashed_password, role='viewer')
        db.session.add(user)
        db.session.commit()
        flash('Your account has been created! You are now able to log in', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        else:
            flash('Login Unsuccessful. Please check username and password', 'danger')
    return render_template('login.html', title='Login', form=form)

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route("/post/new", methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'publisher')
def new_post():
    form = PostForm()
    if form.validate_on_submit():
        date_realization = datetime.strptime(form.date_realization.data, '%Y-%m-%d').date()
        
        # Parse optional audit_date
        audit_date = None
        if form.audit_date.data:
            audit_date = datetime.strptime(form.audit_date.data, '%Y-%m-%d').date()
        
        # Create post with new fields - status is 'Open' by default
        post = Post(
            post_type=form.post_type.data,
            problem=form.problem.data,
            cause='',  # No longer required in form
            corrective_action=form.corrective_action.data,
            responsible=form.responsible.data,
            area=form.project_area.data or None,
            date_realization=date_realization,
            audit_date=audit_date,
            audit_type=form.audit_type.data or None,
            status='Open',  # Always starts as Open
            author=current_user
        )
        
        # Handle problem image
        if form.image_problem.data and hasattr(form.image_problem.data, 'filename') and form.image_problem.data.filename:
            post.image_problem = save_picture(form.image_problem.data)
        
        # Handle corrective action image
        if form.image_corrective.data and hasattr(form.image_corrective.data, 'filename') and form.image_corrective.data.filename:
            post.image_corrective = save_picture(form.image_corrective.data)
        
        db.session.add(post)
        db.session.commit()
        log_activity('created', 'post', post.id, f"Created {post.post_type} post: {post.problem[:50]}")
        flash('Your post has been created!', 'success')
        return redirect(url_for('home'))
    return render_template('create_post.html', title='New Post', form=form, legend='New Post')


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('post_detail.html', title=post.problem[:50], post=post)


@app.route("/post/<int:post_id>/update", methods=['GET', 'POST'])
@login_required
@roles_required('admin', 'publisher')
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Check if the current user is the author of the post or an admin
    if post.author != current_user and current_user.role != 'admin':
        abort(403)
    
    form = PostForm()
    if form.validate_on_submit():
        date_realization = datetime.strptime(form.date_realization.data, '%Y-%m-%d').date()
        
        # Parse optional audit_date
        audit_date = None
        if form.audit_date.data:
            audit_date = datetime.strptime(form.audit_date.data, '%Y-%m-%d').date()
        
        # Update all fields
        post.post_type = form.post_type.data
        post.problem = form.problem.data
        post.corrective_action = form.corrective_action.data
        post.responsible = form.responsible.data
        post.area = form.project_area.data or None
        post.date_realization = date_realization
        post.audit_date = audit_date
        post.audit_type = form.audit_type.data or None
        # Don't update status here - it's managed through complete_post
        
        # Handle problem image
        if form.image_problem.data and hasattr(form.image_problem.data, 'filename') and form.image_problem.data.filename:
            post.image_problem = save_picture(form.image_problem.data)
        
        # Handle corrective action image
        if form.image_corrective.data and hasattr(form.image_corrective.data, 'filename') and form.image_corrective.data.filename:
            post.image_corrective = save_picture(form.image_corrective.data)
        
        db.session.commit()
        log_activity('updated', 'post', post.id, f"Updated {post.post_type} post: {post.problem[:50]}")
        flash('Your post has been updated!', 'success')
        return redirect(url_for('home'))
    elif request.method == 'GET':
        form.post_type.data = post.post_type
        form.problem.data = post.problem
        form.corrective_action.data = post.corrective_action
        form.responsible.data = post.responsible
        form.project_area.data = post.area
        form.date_realization.data = post.date_realization.strftime('%Y-%m-%d')
        form.audit_date.data = post.audit_date.strftime('%Y-%m-%d') if post.audit_date else ''
        form.audit_type.data = post.audit_type or ''
    
    return render_template('create_post.html', title='Update Post', form=form, legend='Update Post', post=post)


@app.route("/post/<int:post_id>/delete", methods=['POST'])
@login_required
@roles_required('admin', 'publisher')
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Check if the current user is the author of the post or an admin
    if post.author != current_user and current_user.role != 'admin':
        abort(403)
    
    post_problem = post.problem
    log_activity('deleted', 'post', post_id, f"Deleted post: {post_problem[:50]}")
    db.session.delete(post)
    db.session.commit()
    flash('Your post has been deleted!', 'success')
    return redirect(url_for('home'))


@app.route("/post/<int:post_id>/complete", methods=['POST'])
@login_required
@roles_required('admin', 'publisher')
def complete_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Check if the current user is the author of the post or an admin
    if post.author != current_user and current_user.role != 'admin':
        abort(403)
    
    # Check if corrective action image exists
    if not post.image_corrective:
        flash('Cannot complete post without uploading a corrective action image. Please edit the post and upload an image.', 'warning')
        return redirect(url_for('post_detail', post_id=post_id))
    
    # Mark as completed
    post.status = 'Completed'
    db.session.commit()
    log_activity('completed', 'post', post.id, f"Completed post: {post.problem[:50]}")
    flash('Post has been marked as Completed!', 'success')
    return redirect(url_for('post_detail', post_id=post_id))


@app.route("/post/<int:post_id>/reopen", methods=['POST'])
@login_required
@roles_required('admin', 'publisher')
def reopen_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Check if the current user is the author of the post or an admin
    if post.author != current_user and current_user.role != 'admin':
        abort(403)
    
    # Reopen the post
    post.status = 'Open'
    db.session.commit()
    log_activity('reopened', 'post', post.id, f"Reopened post: {post.problem[:50]}")
    flash('Post has been reopened.', 'info')
    return redirect(url_for('post_detail', post_id=post_id))


@app.route("/user/<string:username>")
def user_posts(username):
    user = User.query.filter_by(username=username).first_or_404()
    page = request.args.get('page', 1, type=int)
    posts = Post.query.filter_by(author=user).order_by(Post.date_realization.desc()).paginate(
        page=page, per_page=5)
    return render_template('user_posts.html', posts=posts, user=user)


@app.route("/account", methods=['GET', 'POST'])
@login_required
def account():
    if request.method == 'POST':
        username = request.form.get('username')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Validate username
        if username != current_user.username:
            user_with_username = User.query.filter_by(username=username).first()
            if user_with_username:
                flash('That username is taken. Please choose a different one.', 'danger')
                return render_template('account.html', title='Account')
            current_user.username = username
        
        # Validate passwords match if provided
        if new_password and new_password != confirm_password:
            flash('New passwords must match.', 'danger')
            return render_template('account.html', title='Account')
        
        if new_password:
            current_user.password = generate_password_hash(new_password)
        
        db.session.commit()
        flash('Your account has been updated!', 'success')
        return redirect(url_for('account'))
    return render_template('account.html', title='Account')

@app.route("/admin")
@login_required
@roles_required('admin')
def admin():
    users = User.query.all()
    all_posts = Post.query.all()
    return render_template('admin.html', title='Admin', users=users, all_posts=all_posts)


@app.context_processor
def utility_processor():
    def get_open_posts_count():
        return Post.query.filter_by(status='Open').count()
    return dict(get_open_posts_count=get_open_posts_count)

@app.route("/admin/change_role/<int:user_id>", methods=['POST'])
@login_required
@roles_required('admin')
def change_role(user_id):
    user = User.query.get_or_404(user_id)
    user.role = request.form['role']
    db.session.commit()
    flash(f"{user.username}'s role has been updated to {user.role}", 'success')
    return redirect(url_for('admin'))

@app.route("/admin/reset_password/<int:user_id>", methods=['POST'])
@login_required
@roles_required('admin')
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = secrets.token_urlsafe(8)
    user.password = generate_password_hash(new_password)
    db.session.commit()
    log_activity('password_reset', 'user', user_id, f"Password reset for {user.username}")
    flash(f"{user.username}'s password has been reset to: {new_password}", 'success')
    return redirect(url_for('admin'))


@app.route("/admin/delete_user/<int:user_id>", methods=['POST'])
@login_required
@roles_required('admin')
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # Prevent admin from deleting themselves
    if user.id == current_user.id:
        flash("You cannot delete your own account!", 'danger')
        return redirect(url_for('admin'))
    
    username = user.username
    log_activity('deleted', 'user', user_id, f"Deleted user: {username}")
    db.session.delete(user)
    db.session.commit()
    flash(f"User '{username}' has been deleted successfully.", 'success')
    return redirect(url_for('admin'))


# ============================================
# COMMENTS ROUTES
# ============================================
@app.route("/post/<int:post_id>/comment", methods=['POST'])
@login_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    content = request.form.get('content')
    if content and content.strip():
        comment = Comment(content=content.strip(), user_id=current_user.id, post_id=post_id)
        db.session.add(comment)
        db.session.commit()
        log_activity('commented', 'post', post_id, f"Comment added: {content[:50]}...")
        flash('Your comment has been added!', 'success')
    else:
        flash('Comment cannot be empty.', 'warning')
    return redirect(url_for('post_detail', post_id=post_id))


@app.route("/comment/<int:comment_id>/delete", methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    post_id = comment.post_id
    
    # Only comment author or admin can delete
    if comment.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    
    log_activity('deleted', 'comment', comment_id, f"Comment deleted from post {post_id}")
    db.session.delete(comment)
    db.session.commit()
    flash('Comment has been deleted.', 'success')
    return redirect(url_for('post_detail', post_id=post_id))


# ============================================
# ACTIVITY LOG ROUTE
# ============================================
@app.route("/admin/activity-log")
@login_required
@roles_required('admin')
def activity_log():
    page = request.args.get('page', 1, type=int)
    activities = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).paginate(page=page, per_page=20)
    return render_template('activity_log.html', title='Activity Log', activities=activities)


# ============================================
# PDF EXPORT ROUTE
# ============================================
@app.route("/post/<int:post_id>/export-pdf")
def export_post_pdf(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle', 
        parent=styles['Heading1'], 
        fontSize=24, 
        spaceAfter=5,
        textColor=colors.white,
        alignment=1  # Center
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.white,
        alignment=1
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading', 
        parent=styles['Heading2'], 
        fontSize=14, 
        spaceBefore=15,
        spaceAfter=8,
        textColor=colors.HexColor('#c21807'),
        borderPadding=5
    )
    
    body_style = ParagraphStyle(
        'CustomBody', 
        parent=styles['Normal'], 
        fontSize=11, 
        spaceAfter=8,
        leading=16
    )
    
    label_style = ParagraphStyle(
        'Label',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#666666'),
        spaceAfter=2
    )
    
    value_style = ParagraphStyle(
        'Value',
        parent=styles['Normal'],
        fontSize=12,
        fontName='Helvetica-Bold',
        spaceAfter=10
    )
    
    elements = []
    
    # Header Banner
    header_data = [[
        Paragraph("WASTE WALK", title_style),
    ], [
        Paragraph("Action Plan Report", subtitle_style)
    ]]
    
    header_table = Table(header_data, colWidths=[7*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#c21807')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, 0), 20),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 20),
        ('LEFTPADDING', (0, 0), (-1, -1), 20),
        ('RIGHTPADDING', (0, 0), (-1, -1), 20),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 25))
    
    # Status Badge
    status_color = colors.HexColor('#28a745') if post.status == 'Completed' else \
                   colors.HexColor('#ffc107') if post.status == 'In Progress' else \
                   colors.HexColor('#dc3545')
    
    status_data = [[Paragraph(f"<b>STATUS: {post.status.upper()}</b>", 
                              ParagraphStyle('Status', parent=styles['Normal'], 
                                           fontSize=12, textColor=colors.white, alignment=1))]]
    status_table = Table(status_data, colWidths=[2*inch])
    status_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), status_color),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 15),
        ('RIGHTPADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(status_table)
    elements.append(Spacer(1, 20))
    
    # Problem Section
    elements.append(Paragraph("PROBLEM", heading_style))
    problem_data = [[Paragraph(post.problem, value_style)]]
    problem_table = Table(problem_data, colWidths=[7*inch])
    problem_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(problem_table)
    elements.append(Spacer(1, 15))
    
    # Details Grid
    details_data = [
        [Paragraph("<b>Responsible</b>", label_style), Paragraph("<b>Date</b>", label_style), Paragraph("<b>Author</b>", label_style)],
        [Paragraph(post.responsible, body_style), 
         Paragraph(post.date_realization.strftime('%B %d, %Y'), body_style), 
         Paragraph(post.author.username, body_style)]
    ]
    details_table = Table(details_data, colWidths=[2.3*inch, 2.3*inch, 2.3*inch])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.white),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    elements.append(details_table)
    elements.append(Spacer(1, 20))
    
    # Image
    if post.image_file and post.image_file != 'default.jpg':
        image_path = os.path.join(app.root_path, 'static/uploads', post.image_file)
        if os.path.exists(image_path):
            elements.append(Paragraph("IMAGE", heading_style))
            try:
                img = RLImage(image_path)
                max_width = 5 * inch
                max_height = 3.5 * inch
                img_width, img_height = img.drawWidth, img.drawHeight
                ratio = min(max_width / img_width, max_height / img_height)
                img.drawWidth = img_width * ratio
                img.drawHeight = img_height * ratio
                
                # Center the image in a table
                img_data = [[img]]
                img_table = Table(img_data, colWidths=[7*inch])
                img_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
                    ('TOPPADDING', (0, 0), (-1, -1), 15),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                ]))
                elements.append(img_table)
                elements.append(Spacer(1, 20))
            except Exception as e:
                pass
    
    # Cause & Corrective Action - Side by Side
    elements.append(Paragraph("ANALYSIS", heading_style))
    analysis_data = [
        [Paragraph("<b>Cause</b>", ParagraphStyle('CauseHeader', fontSize=11, textColor=colors.white)), 
         Paragraph("<b>Corrective Action</b>", ParagraphStyle('ActionHeader', fontSize=11, textColor=colors.white))],
        [Paragraph(post.cause, body_style), Paragraph(post.corrective_action, body_style)]
    ]
    analysis_table = Table(analysis_data, colWidths=[3.5*inch, 3.5*inch])
    analysis_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#856404')),  # Warning yellow-dark
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#155724')),  # Success green-dark
        ('BACKGROUND', (0, 1), (-1, 1), colors.white),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(analysis_table)
    elements.append(Spacer(1, 30))
    
    # Footer
    footer_text = f"Generated on {datetime.now().strftime('%B %d, %Y at %H:%M')} | Waste Walk Action Plan System"
    footer_data = [[Paragraph(footer_text, ParagraphStyle('Footer', fontSize=9, textColor=colors.HexColor('#666666'), alignment=1))]]
    footer_table = Table(footer_data, colWidths=[7*inch])
    footer_table.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1, colors.HexColor('#dee2e6')),
        ('TOPPADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(footer_table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    # Create response
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=waste_walk_post_{post_id}.pdf'
    return response


# ============================================
# EXPORT ALL POSTS PDF
# ============================================
@app.route("/export-all-pdf")
def export_all_posts_pdf():
    posts = Post.query.order_by(Post.date_realization.desc()).all()
    
    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=20, spaceAfter=5, textColor=colors.white, alignment=1)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=12, spaceBefore=10, spaceAfter=5, textColor=colors.HexColor('#c21807'))
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=9, spaceAfter=4, leading=12)
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#666666'))
    
    elements = []
    
    # Header
    header_data = [[Paragraph("WASTE WALK - ALL POSTS REPORT", title_style)]]
    header_table = Table(header_data, colWidths=[7.5*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#c21807')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 15),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 5))
    
    # Summary stats
    open_count = len([p for p in posts if p.status == 'Open'])
    in_progress_count = len([p for p in posts if p.status == 'In Progress'])
    completed_count = len([p for p in posts if p.status == 'Completed'])
    
    summary_text = f"Total: {len(posts)} posts | Open: {open_count} | In Progress: {in_progress_count} | Completed: {completed_count}"
    elements.append(Paragraph(summary_text, ParagraphStyle('Summary', fontSize=10, alignment=1, spaceAfter=15)))
    
    # Posts Table
    table_data = [['#', 'Problem', 'Status', 'Responsible', 'Date', 'Author']]
    
    for i, post in enumerate(posts, 1):
        status_text = post.status
        table_data.append([
            str(i),
            Paragraph(post.problem[:60] + ('...' if len(post.problem) > 60 else ''), body_style),
            status_text,
            post.responsible[:20] + ('...' if len(post.responsible) > 20 else ''),
            post.date_realization.strftime('%Y-%m-%d'),
            post.author.username
        ])
    
    table = Table(table_data, colWidths=[0.4*inch, 2.5*inch, 0.9*inch, 1.3*inch, 0.9*inch, 0.9*inch])
    
    # Color-code status cells
    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#343a40')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),  # Problem column left-aligned
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]
    
    # Add status cell coloring
    for i, post in enumerate(posts, 1):
        if post.status == 'Completed':
            table_style.append(('BACKGROUND', (2, i), (2, i), colors.HexColor('#d4edda')))
        elif post.status == 'In Progress':
            table_style.append(('BACKGROUND', (2, i), (2, i), colors.HexColor('#fff3cd')))
        else:
            table_style.append(('BACKGROUND', (2, i), (2, i), colors.HexColor('#f8d7da')))
    
    table.setStyle(TableStyle(table_style))
    elements.append(table)
    elements.append(Spacer(1, 20))
    
    # Footer
    footer_text = f"Generated on {datetime.now().strftime('%B %d, %Y at %H:%M')} | Waste Walk Action Plan System"
    elements.append(Paragraph(footer_text, ParagraphStyle('Footer', fontSize=8, textColor=colors.HexColor('#666666'), alignment=1)))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=waste_walk_summary_{datetime.now().strftime("%Y%m%d")}.pdf'
    return response


# ============================================
# EXPORT ALL POSTS - DETAILED PDF
# ============================================
@app.route("/export-all-detailed-pdf")
def export_all_posts_detailed_pdf():
    from reportlab.platypus import PageBreak
    
    posts = Post.query.order_by(Post.date_realization.desc()).all()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=24, spaceAfter=5, textColor=colors.white, alignment=1)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=12, textColor=colors.white, alignment=1)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=14, spaceBefore=15, spaceAfter=8, textColor=colors.HexColor('#c21807'))
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=11, spaceAfter=8, leading=16)
    label_style = ParagraphStyle('Label', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#666666'), spaceAfter=2)
    value_style = ParagraphStyle('Value', parent=styles['Normal'], fontSize=12, fontName='Helvetica-Bold', spaceAfter=10)
    
    elements = []
    
    for idx, post in enumerate(posts):
        # Header Banner
        header_data = [[Paragraph("WASTE WALK", title_style)], [Paragraph("Action Plan Report", subtitle_style)]]
        header_table = Table(header_data, colWidths=[7*inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#c21807')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, 0), 15),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 15),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 20))
        
        # Status Badge
        status_color = colors.HexColor('#28a745') if post.status == 'Completed' else \
                       colors.HexColor('#ffc107') if post.status == 'In Progress' else \
                       colors.HexColor('#dc3545')
        
        status_data = [[Paragraph(f"<b>STATUS: {post.status.upper()}</b>", 
                                  ParagraphStyle('Status', fontSize=12, textColor=colors.white, alignment=1))]]
        status_table = Table(status_data, colWidths=[2*inch])
        status_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), status_color),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(status_table)
        elements.append(Spacer(1, 15))
        
        # Problem Section
        elements.append(Paragraph("PROBLEM", heading_style))
        problem_data = [[Paragraph(post.problem, value_style)]]
        problem_table = Table(problem_data, colWidths=[7*inch])
        problem_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(problem_table)
        elements.append(Spacer(1, 10))
        
        # Details Grid
        details_data = [
            [Paragraph("<b>Responsible</b>", label_style), Paragraph("<b>Date</b>", label_style), Paragraph("<b>Author</b>", label_style)],
            [Paragraph(post.responsible, body_style), 
             Paragraph(post.date_realization.strftime('%B %d, %Y'), body_style), 
             Paragraph(post.author.username, body_style)]
        ]
        details_table = Table(details_data, colWidths=[2.3*inch, 2.3*inch, 2.3*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.white),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 15))
        
        # Image
        if post.image_file and post.image_file != 'default.jpg':
            image_path = os.path.join(app.root_path, 'static/uploads', post.image_file)
            if os.path.exists(image_path):
                elements.append(Paragraph("IMAGE", heading_style))
                try:
                    img = RLImage(image_path)
                    max_width = 4.5 * inch
                    max_height = 3 * inch
                    img_width, img_height = img.drawWidth, img.drawHeight
                    ratio = min(max_width / img_width, max_height / img_height)
                    img.drawWidth = img_width * ratio
                    img.drawHeight = img_height * ratio
                    
                    img_data = [[img]]
                    img_table = Table(img_data, colWidths=[7*inch])
                    img_table.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
                        ('TOPPADDING', (0, 0), (-1, -1), 10),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                    ]))
                    elements.append(img_table)
                    elements.append(Spacer(1, 15))
                except:
                    pass
        
        # Cause & Corrective Action
        elements.append(Paragraph("ANALYSIS", heading_style))
        analysis_data = [
            [Paragraph("<b>Cause</b>", ParagraphStyle('H', fontSize=10, textColor=colors.white)), 
             Paragraph("<b>Corrective Action</b>", ParagraphStyle('H', fontSize=10, textColor=colors.white))],
            [Paragraph(post.cause, body_style), Paragraph(post.corrective_action, body_style)]
        ]
        analysis_table = Table(analysis_data, colWidths=[3.5*inch, 3.5*inch])
        analysis_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#856404')),
            ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#155724')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.white),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(analysis_table)
        
        # Post separator border
        elements.append(Spacer(1, 20))
        separator_data = [['']]
        separator_table = Table(separator_data, colWidths=[7*inch], rowHeights=[3])
        separator_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#c21807')),
        ]))
        elements.append(separator_table)
        
        # Page break between posts (except for last post)
        if idx < len(posts) - 1:
            elements.append(PageBreak())
    
    # Final footer
    elements.append(Spacer(1, 30))
    footer_text = f"Generated on {datetime.now().strftime('%B %d, %Y at %H:%M')} | Waste Walk Action Plan System | {len(posts)} posts"
    elements.append(Paragraph(footer_text, ParagraphStyle('Footer', fontSize=9, textColor=colors.HexColor('#666666'), alignment=1)))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=waste_walk_detailed_{datetime.now().strftime("%Y%m%d")}.pdf'
    return response


# ============================================
# FILTERED PDF EXPORT ROUTE
# ============================================
@app.route("/export-pdf")
def export_filtered_pdf():
    """Export posts to PDF with filters applied"""
    from sqlalchemy import and_
    
    # Get filter parameters
    export_format = request.args.get('export_format', 'summary')
    post_type = request.args.get('post_type', '')
    status = request.args.get('status', '')
    audit_date_from = request.args.get('audit_date_from', '')
    audit_date_to = request.args.get('audit_date_to', '')
    responsible = request.args.get('responsible', '')
    area = request.args.get('area', '')
    author = request.args.get('author', '')
    audit_type = request.args.get('audit_type', '')
    project = request.args.get('project', '')
    
    # Build query with filters
    query = Post.query
    
    if post_type:
        query = query.filter(Post.post_type == post_type)
    if status:
        query = query.filter(Post.status == status)
    if audit_date_from:
        date_from = datetime.strptime(audit_date_from, '%Y-%m-%d')
        query = query.filter(Post.audit_date >= date_from)
    if audit_date_to:
        date_to = datetime.strptime(audit_date_to, '%Y-%m-%d')
        query = query.filter(Post.audit_date <= date_to)
    if responsible:
        query = query.filter(Post.responsible.ilike(f'%{responsible}%'))
    if area:
        query = query.filter(Post.area.ilike(f'%{area}%'))
    if author:
        query = query.join(User).filter(User.username.ilike(f'%{author}%'))
    if audit_type:
        query = query.filter(Post.audit_type == audit_type)
    if project:
        query = query.filter(Post.project.ilike(f'%{project}%'))
    
    posts = query.order_by(Post.date_realization.desc()).all()
    
    if not posts:
        flash('No posts found matching your filter criteria.', 'warning')
        return redirect(url_for('home'))
    
    # Generate PDF based on format
    if export_format == 'detailed':
        return generate_detailed_pdf(posts, post_type or 'All Types')
    else:
        return generate_summary_pdf(posts, post_type or 'All Types')


def generate_summary_pdf(posts, title_type):
    """Generate summary/table format PDF"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=40, bottomMargin=40)
    
    styles = getSampleStyleSheet()
    elements = []
    
    # Title
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=20, textColor=colors.HexColor('#c21807'), alignment=1, spaceAfter=20)
    elements.append(Paragraph(f"{title_type} - Action Plan Summary", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')}", ParagraphStyle('Date', alignment=1, textColor=colors.grey)))
    elements.append(Spacer(1, 20))
    
    # Stats Summary
    status_counts = {}
    for post in posts:
        status_counts[post.status] = status_counts.get(post.status, 0) + 1
    
    stats_text = f"Total: {len(posts)} | "
    stats_text += " | ".join([f"{s}: {c}" for s, c in status_counts.items()])
    elements.append(Paragraph(stats_text, ParagraphStyle('Stats', alignment=1, fontSize=11, spaceAfter=15)))
    elements.append(Spacer(1, 10))
    
    # Table Data
    cell_style = ParagraphStyle('Cell', fontSize=8, leading=10)
    header = ['#', 'Type', 'Problem', 'Responsible', 'Area', 'Target Date', 'Status']
    data = [header]
    
    for i, post in enumerate(posts, 1):
        row = [
            str(i),
            Paragraph(post.post_type or '-', cell_style),
            Paragraph(post.problem[:40] + '...' if len(post.problem) > 40 else post.problem, cell_style),
            Paragraph(post.responsible[:15] + '...' if len(post.responsible) > 15 else post.responsible, cell_style),
            Paragraph(post.area or '-', cell_style),
            post.date_realization.strftime('%Y-%m-%d'),
            post.status
        ]
        data.append(row)
    
    table = Table(data, colWidths=[0.3*inch, 0.8*inch, 2.2*inch, 1.2*inch, 1*inch, 0.9*inch, 0.8*inch])
    
    # Status-based row coloring
    table_style = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c21807')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]
    
    for i, post in enumerate(posts, 1):
        if post.status == 'Completed':
            table_style.append(('BACKGROUND', (-1, i), (-1, i), colors.HexColor('#d4edda')))
        elif post.status == 'In Progress':
            table_style.append(('BACKGROUND', (-1, i), (-1, i), colors.HexColor('#fff3cd')))
        else:
            table_style.append(('BACKGROUND', (-1, i), (-1, i), colors.HexColor('#f8d7da')))
    
    table.setStyle(TableStyle(table_style))
    elements.append(table)
    
    doc.build(elements)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=action_plan_summary_{datetime.now().strftime("%Y%m%d")}.pdf'
    return response


def generate_detailed_pdf(posts, title_type):
    """Generate detailed full-page format PDF"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=22, textColor=colors.white, alignment=1, spaceAfter=5)
    subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], fontSize=11, textColor=colors.white, alignment=1)
    heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=13, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor('#c21807'))
    body_style = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, spaceAfter=8, leading=14)
    
    elements = []
    
    for idx, post in enumerate(posts):
        # Header Banner
        header_data = [[Paragraph(title_type.upper(), title_style)], [Paragraph("Action Plan Report", subtitle_style)]]
        header_table = Table(header_data, colWidths=[7*inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#c21807')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 12),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 15))
        
        # Status & Type Badge
        status_color = colors.HexColor('#28a745') if post.status == 'Completed' else colors.HexColor('#ffc107') if post.status == 'In Progress' else colors.HexColor('#dc3545')
        badge_data = [[Paragraph(f"<b>{post.status}</b>", ParagraphStyle('Badge', fontSize=11, textColor=colors.white, alignment=1))]]
        badge_table = Table(badge_data, colWidths=[1.5*inch])
        badge_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), status_color), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        elements.append(badge_table)
        elements.append(Spacer(1, 15))
        
        # Problem Section
        elements.append(Paragraph("PROBLEM / OPPORTUNITY", heading_style))
        problem_data = [[Paragraph(post.problem, body_style)]]
        problem_table = Table(problem_data, colWidths=[7*inch])
        problem_table.setStyle(TableStyle([('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#c21807')), ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10), ('LEFTPADDING', (0, 0), (-1, -1), 10)]))
        elements.append(problem_table)
        elements.append(Spacer(1, 12))
        
        # Details Grid
        details_data = [
            [Paragraph("<b>Responsible:</b>", body_style), Paragraph("<b>Area:</b>", body_style), Paragraph("<b>Project:</b>", body_style)],
            [Paragraph(post.responsible, body_style), Paragraph(post.area or '-', body_style), Paragraph(post.project or '-', body_style)],
            [Paragraph("<b>Target Date:</b>", body_style), Paragraph("<b>Audit Date:</b>", body_style), Paragraph("<b>Author:</b>", body_style)],
            [Paragraph(post.date_realization.strftime('%B %d, %Y'), body_style), Paragraph(post.audit_date.strftime('%B %d, %Y') if post.audit_date else '-', body_style), Paragraph(post.author.username, body_style)]
        ]
        details_table = Table(details_data, colWidths=[2.3*inch, 2.3*inch, 2.4*inch])
        details_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8f9fa')), ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#f8f9fa')), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6), ('LEFTPADDING', (0, 0), (-1, -1), 8)]))
        elements.append(details_table)
        elements.append(Spacer(1, 12))
        
        # Images Section
        has_problem_img = post.image_problem
        has_corrective_img = post.image_corrective
        
        if has_problem_img or has_corrective_img:
            elements.append(Paragraph("IMAGES", heading_style))
            img_row = []
            
            # Problem Image
            if has_problem_img:
                try:
                    img_path = os.path.join(app.root_path, 'static', 'uploads', post.image_problem)
                    if os.path.exists(img_path):
                        img = Image(img_path, width=3*inch, height=2.2*inch)
                        img_cell = [[Paragraph("<b>Problem/Opportunity</b>", ParagraphStyle('ImgLabel', fontSize=9, alignment=1, textColor=colors.HexColor('#856404')))], [img]]
                        img_table = Table(img_cell, colWidths=[3.2*inch])
                        img_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
                        img_row.append(img_table)
                except:
                    pass
            
            # Corrective Action Image
            if has_corrective_img:
                try:
                    img_path = os.path.join(app.root_path, 'static', 'uploads', post.image_corrective)
                    if os.path.exists(img_path):
                        img = Image(img_path, width=3*inch, height=2.2*inch)
                        img_cell = [[Paragraph("<b>Corrective Action</b>", ParagraphStyle('ImgLabel', fontSize=9, alignment=1, textColor=colors.HexColor('#155724')))], [img]]
                        img_table = Table(img_cell, colWidths=[3.2*inch])
                        img_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5)]))
                        img_row.append(img_table)
                except:
                    pass
            
            if img_row:
                images_table = Table([img_row], colWidths=[3.5*inch] * len(img_row))
                images_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
                elements.append(images_table)
                elements.append(Spacer(1, 12))
        
        # Cause & Corrective Action
        elements.append(Paragraph("ANALYSIS", heading_style))
        analysis_data = [
            [Paragraph("<b>Cause</b>", ParagraphStyle('H', fontSize=10, textColor=colors.white)), Paragraph("<b>Corrective Action</b>", ParagraphStyle('H', fontSize=10, textColor=colors.white))],
            [Paragraph(post.cause, body_style), Paragraph(post.corrective_action, body_style)]
        ]
        analysis_table = Table(analysis_data, colWidths=[3.5*inch, 3.5*inch])
        analysis_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#856404')),
            ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#155724')),
            ('BACKGROUND', (0, 1), (-1, 1), colors.white),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(analysis_table)
        
        # Separator
        elements.append(Spacer(1, 20))
        sep_table = Table([['']], colWidths=[7*inch], rowHeights=[3])
        sep_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#c21807'))]))
        elements.append(sep_table)
        
        if idx < len(posts) - 1:
            elements.append(PageBreak())
    
    # Footer
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')} | {len(posts)} posts", ParagraphStyle('Footer', fontSize=9, textColor=colors.grey, alignment=1)))
    
    doc.build(elements)
    buffer.seek(0)
    
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=action_plan_detailed_{datetime.now().strftime("%Y%m%d")}.pdf'
    return response
