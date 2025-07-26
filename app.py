import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import stripe

# --- dotenv laden ---
from dotenv import load_dotenv
load_dotenv()

# --- 1. App & Datenbank Konfiguration ---
app = Flask(__name__, template_folder='template')
app.secret_key = os.getenv('SECRET_KEY')


database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
if database_url and "sslmode" not in database_url:
    database_url += "?sslmode=require"
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- 2. Stripe Konfiguration ---
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# --- 3. Datenbank Modelle ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    plan = db.Column(db.String(50), nullable=False, default='free')
    auftraege = db.relationship('Auftrag', backref='author', lazy=True, cascade="all, delete-orphan")

class Auftrag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    keywords = db.Column(db.String(300), nullable=False)
    filter = db.Column(db.String(500), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    funde = db.relationship('Fund', backref='auftrag', lazy=True, cascade="all, delete-orphan")
    aktiv = db.Column(db.Boolean, default=True, nullable=False)

class Fund(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(300), nullable=False)
    price = db.Column(db.String(50), nullable=False)
    item_url = db.Column(db.String(1000), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    auftrag_id = db.Column(db.Integer, db.ForeignKey('auftrag.id'), nullable=False)

# --- 4. Webseiten Routen ---
@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('dashboard.html', user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Diese E-Mail-Adresse ist bereits registriert.')
            return redirect(url_for('register'))
        password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(email=email, password_hash=password_hash)
        db.session.add(new_user)
        db.session.commit()
        flash('Registrierung erfolgreich! Du kannst dich jetzt einloggen.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Bitte ueberpruefe deine Login-Daten.')
            return redirect(url_for('login'))
        session['logged_in'] = True
        session['user_id'] = user.id
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Du wurdest erfolgreich ausgeloggt.")
    return redirect(url_for('login'))

@app.route('/add', methods=['POST'])
def neuer_auftrag():
    if not session.get('logged_in'): return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    limit_free_plan = 2
    if user.plan == 'free' and len(user.auftraege) >= limit_free_plan:
        flash(f"Limit von {limit_free_plan} Auftraegen erreicht. Bitte upgraden!")
        return redirect(url_for('upgrade_seite'))
    
    name = request.form.get('name')
    keywords = request.form.get('keywords')
    min_price = request.form.get('min_price')
    max_price = request.form.get('max_price')
    condition_new = request.form.get('condition_new')

    filter_teile = []
    if min_price or max_price:
        price_filter = f"price:[{min_price or ''}..{max_price or ''}]"
        filter_teile.append(price_filter)
        filter_teile.append("priceCurrency:EUR")
    if condition_new:
        filter_teile.append("conditions:{NEW}")
    final_filter = ",".join(filter_teile)

    neuer_auftrag = Auftrag(name=name, keywords=keywords, filter=final_filter, user_id=session['user_id'], aktiv=True)
    db.session.add(neuer_auftrag)
    db.session.commit()
    flash("Neuer Suchauftrag erfolgreich hinzugefuegt!")
    return redirect(url_for('dashboard'))

@app.route('/delete/<int:auftrag_id>', methods=['POST'])
def loesche_auftrag(auftrag_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    auftrag = Auftrag.query.get_or_404(auftrag_id)
    if auftrag.author.id != session['user_id']:
        return "Nicht autorisiert", 403
    db.session.delete(auftrag)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/upgrade')
def upgrade_seite():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('upgrade.html')

@app.route('/make_me_premium_please')
def make_me_premium():
    if 'user_id' not in session:
        flash("Bitte zuerst einloggen.")
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if user:
        user.plan = 'premium'
        db.session.commit()
        session.clear()
        session['logged_in'] = True
        session['user_id'] = user.id
        flash(f"Dein Account ({user.email}) wurde erfolgreich auf PREMIUM hochgestuft!")
    else:
        flash("Fehler: Benutzer nicht gefunden.")
    return redirect(url_for('dashboard'))

@app.route('/toggle_auftrag/<int:auftrag_id>', methods=['POST'])
def toggle_auftrag(auftrag_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    auftrag = Auftrag.query.get_or_404(auftrag_id)
    if auftrag.author.id != session['user_id']:
        return "Nicht autorisiert", 403
    auftrag.aktiv = not auftrag.aktiv
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    try:
        checkout_session = stripe.checkout.Session.create(
            line_items=[{'price': os.getenv('STRIPE_PRICE_ID'), 'quantity': 1}],
            mode='subscription',
            client_reference_id=session['user_id'],
            success_url=url_for('success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('cancel', _external=True),
        )
    except Exception as e:
        print(f"Stripe Error: {str(e)}")
        flash("Etwas ist beim Starten der Bezahlung schiefgelaufen.")
        return redirect(url_for('upgrade_seite'))
    return redirect(checkout_session.url, code=303)

@app.route('/success')
def success():
    session_id = request.args.get('session_id')
    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        user_id = int(checkout_session.client_reference_id)
        user = User.query.get(user_id)
        if user:
            user.plan = 'premium'
            db.session.commit()
            session.clear()
            session['logged_in'] = True
            session['user_id'] = user.id
            flash("Upgrade erfolgreich! Willkommen im Premium-Club.")
        else:
            flash("Fehler: Der Benutzer fuer diese Zahlung konnte nicht gefunden werden.")
    except Exception as e:
        print(f"Success-Route Error: {str(e)}")
        flash("Es gab ein Problem bei der Verarbeitung deines Upgrades.")
    return redirect(url_for('dashboard'))

@app.route('/cancel')
def cancel():
    flash("Die Zahlung wurde abgebrochen. Du bist weiterhin im kostenlosen Plan.")

# --- 5. Initialisierung ---
with app.app_context():
    db.create_all()
    return redirect(url_for('dashboard'))

@app.route('/api/get_all_jobs')
def get_all_jobs():
    jobs = Auftrag.query.filter_by(aktiv=True).all()

    daten = [
        {
            "id": a.id,
            "user_id": a.user_id,
            "name": a.name,
            "keywords": a.keywords,
            "filter": a.filter,
            "aktiv": a.aktiv
        } for a in jobs
    ]
    return jsonify(daten)

if __name__ == "__main__":
    app.run(debug=False)
