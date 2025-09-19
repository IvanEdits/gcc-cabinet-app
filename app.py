from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, send_file
import sqlite3
import json
from datetime import datetime, date
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os

app = Flask(__name__)
app.secret_key = 'gcc_cabinet_secret_key_2025'

# SQLite database setup
DATABASE = 'gcc_cabinet.db'

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY, name TEXT, cls TEXT, stream TEXT, house TEXT, type TEXT, term TEXT,
            amount REAL, required REAL, balance REAL, date TEXT, time TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS expenditures (
            id TEXT PRIMARY KEY, desc TEXT, amt REAL, date TEXT, time TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS loans (
            id TEXT PRIMARY KEY, name TEXT, principal REAL, interestPct REAL, total REAL, totalRemaining REAL,
            status TEXT, date TEXT, dueDate TEXT, disbursed INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS repayments (
            id TEXT PRIMARY KEY, loanId TEXT, name TEXT, paid REAL, balance REAL, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS savings (
            id TEXT PRIMARY KEY, name TEXT, amount REAL, dateSaved TEXT, sched TEXT, termWeeks INTEGER,
            interestPct REAL, interestIfHeld REAL, daysScheduled INTEGER, withdrawn INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS minister_payments (
            id TEXT PRIMARY KEY, name TEXT, type TEXT, required REAL, paid REAL, balance REAL, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS incomes (
            id TEXT PRIMARY KEY, source TEXT, amt REAL, date TEXT, time TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS attendance (
            id TEXT PRIMARY KEY, name TEXT, role TEXT, date TEXT, time TEXT, status TEXT, fine REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS duties (
            id TEXT PRIMARY KEY, name TEXT, role TEXT, task TEXT, week TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY, name TEXT, cls TEXT, stream TEXT, house TEXT, date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, from_user TEXT, to_user TEXT, content TEXT, date TEXT, time TEXT, read INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS state (
            id INTEGER PRIMARY KEY, totalCollected REAL, totalExpenditure REAL, financePin TEXT)''')
        # Initialize state if not exists
        c.execute('SELECT COUNT(*) FROM state')
        if c.fetchone()[0] == 0:
            c.execute('INSERT INTO state (totalCollected, totalExpenditure, financePin) VALUES (?, ?, ?)', (0, 0, None))
        conn.commit()

# Pre-set role PINs
ROLE_PINS = {
    'President': '1111', 'PrimeMinister': '2222', 'Finance': '3333', 'Skills': '4444', 'Notice': '5555',
    'ChiefJustice': '6666', 'PermanentSec': '7777', 'Patron': '8888', 'VicePresident': '9999'
}

# Fixed prices and savings tiers
FIXED = {'House Fee': 10000, 'Jersey': 35000, 'Tag': 13000, 'T-Shirt': 25000, 'Membership': 15000}
SAVINGS_TIERS = [
    {'min': 10000, 'weeks': 4, 'pct': 0.10},
    {'min': 20000, 'weeks': 6, 'pct': 0.15},
    {'min': 40000, 'weeks': 8, 'pct': 0.20},
    {'min': 50000, 'weeks': 12, 'pct': 0.30}
]
MEETING_START_DEFAULT = "09:00"
LATE_FINE_AMOUNT = 5000
LOAN_LATE_PENALTY_PCT = 0.05

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def format_ugx(x):
    return "{:,.0f}".format(float(x or 0))

def now_date():
    return datetime.now().strftime('%Y-%m-%d')

def now_time():
    return datetime.now().strftime('%H:%M')

def timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

@app.route('/')
def index():
    if 'role' not in session:
        return render_template('index.html', logged_in=False)
    return render_template('index.html', logged_in=True, role=session['role'])

@app.route('/login', methods=['POST'])
def login():
    role = request.form.get('role')
    pin = request.form.get('pin')
    if not role or not pin:
        flash('Select role and enter PIN')
        return redirect(url_for('index'))
    if role not in ROLE_PINS or pin != ROLE_PINS[role]:
        flash(f'Invalid PIN for {role}')
        return redirect(url_for('index'))
    session['role'] = role
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('role', None)
    return redirect(url_for('index'))

@app.route('/dashboard_data')
def dashboard_data():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT totalCollected, totalExpenditure FROM state WHERE id=1')
        state = c.fetchone()
        c.execute('SELECT COUNT(*) FROM loans WHERE status != ?', ('Cleared',))
        active_loans = c.fetchone()[0]
        c.execute('SELECT house, SUM(amount) as total FROM payments GROUP BY house')
        house_data = {row['house']: row['total'] for row in c.fetchall()}
        houses = ['Onyx', 'Chrysotile', 'Phinix', 'Anonymous']
        totals = [house_data.get(h, 0) for h in houses]
        c.execute('SELECT SUM(totalRemaining) FROM loans WHERE status != ?', ('Cleared',))
        loan_outstanding = c.fetchone()[0] or 0
        net_balance = (state['totalCollected'] or 0) - (state['totalExpenditure'] or 0) - loan_outstanding
    return jsonify({
        'totalCollected': format_ugx(state['totalCollected']),
        'totalExpenditure': format_ugx(state['totalExpenditure']),
        'activeLoansCount': active_loans,
        'netBalance': format_ugx(net_balance),
        'houseChart': {'labels': houses, 'data': totals}
    })

@app.route('/add_payment', methods=['POST'])
def add_payment():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.form
    name = data.get('name')
    cls = data.get('class')
    stream = data.get('stream')
    house = data.get('house')
    type_ = data.get('type')
    term = data.get('term')
    amount = float(data.get('amount') or 0)
    date_ = data.get('date') or now_date()
    if not all([name, cls, stream, house, type_, date_]):
        return jsonify({'error': 'Fill all required fields'}), 400
    if amount <= 0:
        return jsonify({'error': 'Enter amount paid'}), 400
    required = FIXED.get(type_, amount)
    balance = max(0, required - amount)
    rec_id = f'PAY{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO payments (id, name, cls, stream, house, type, term, amount, required, balance, date, time)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (rec_id, name, cls, stream, house, type_, term, amount, required, balance, date_, now_time()))
        c.execute('UPDATE state SET totalCollected = totalCollected + ? WHERE id=1', (amount,))
        conn.commit()
    receipt_text = f'''Good Choice Cabinet Receipt\n
Payment\nName: {name}\nClass: {cls}\nStream: {stream}\nHouse: {house}\nPayment Type: {type_}\nTerm: {term}
Amount Paid: {format_ugx(amount)}\nRequired: {format_ugx(required)}\nBalance: {format_ugx(balance)}
Date: {date_} {now_time()}\nTimestamp: {timestamp()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/pay_balance/<payment_id>', methods=['POST'])
def pay_balance(payment_id):
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    amount = float(request.form.get('amount') or 0)
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM payments WHERE id=?', (payment_id,))
        p = c.fetchone()
        if not p:
            return jsonify({'error': 'Record not found'}), 404
        to_pay = min(amount, p['balance'])
        if to_pay <= 0:
            return jsonify({'error': 'Invalid amount'}), 400
        c.execute('UPDATE payments SET amount=amount+?, balance=balance-? WHERE id=?', (to_pay, to_pay, payment_id))
        c.execute('UPDATE state SET totalCollected=totalCollected+? WHERE id=1', (to_pay,))
        conn.commit()
        receipt_text = f'''Balance Payment\nName: {p['name']}\nPaid: {format_ugx(to_pay)}
Remaining Balance: {format_ugx(p['balance']-to_pay)}\nTime: {timestamp()}'''
        return jsonify({'receipt': receipt_text})

@app.route('/payments')
def get_payments():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM payments')
        payments = [dict(row) for row in c.fetchall()]
    return jsonify(payments)

@app.route('/add_expenditure', methods=['POST'])
def add_expenditure():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    desc = request.form.get('desc')
    amt = float(request.form.get('amount') or 0)
    date_ = request.form.get('date') or now_date()
    if not desc or not amt:
        return jsonify({'error': 'Fill expenditure fields'}), 400
    rec_id = f'EXP{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO expenditures (id, desc, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                  (rec_id, desc, amt, date_, now_time()))
        c.execute('UPDATE state SET totalExpenditure=totalExpenditure+? WHERE id=1', (amt,))
        conn.commit()
    receipt_text = f'''Expenditure Receipt\nDesc: {desc}\nAmount: {format_ugx(amt)}\nDate: {date_} {now_time()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/expenditures')
def get_expenditures():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM expenditures')
        expenditures = [dict(row) for row in c.fetchall()]
    return jsonify(expenditures)

@app.route('/add_loan', methods=['POST'])
def add_loan():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.form
    id_ = data.get('id')
    name = data.get('name')
    amt = float(data.get('amount') or 0)
    interest_pct = float(data.get('interest') or 10)
    due_date = data.get('due_date')
    date_ = data.get('date') or now_date()
    if not all([id_, name, amt, due_date]):
        return jsonify({'error': 'Fill loan fields with due date'}), 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM loans WHERE name=? AND status!=?', (name, 'Cleared'))
        if c.fetchone():
            return jsonify({'error': f'This person has an active loan'}), 400
        total = round(amt + (amt * interest_pct / 100))
        c.execute('''INSERT INTO loans (id, name, principal, interestPct, total, totalRemaining, status, date, dueDate, disbursed)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (id_, name, amt, interest_pct, total, total, 'Active', date_, due_date, 1))
        c.execute('INSERT INTO expenditures (id, desc, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                  (f'EXP-LOAN-{int(datetime.now().timestamp()*1000)}', f'Loan disbursed {id_} to {name}', amt, date_, now_time()))
        c.execute('UPDATE state SET totalExpenditure=totalExpenditure+? WHERE id=1', (amt,))
        conn.commit()
    receipt_text = f'''Loan Disbursement Receipt\nLoan ID: {id_}\nName: {name}\nPrincipal: {format_ugx(amt)}
Interest%: {interest_pct}\nTotal to Repay: {format_ugx(total)}\nDue Date: {due_date}\nDisbursement Date: {date_} {now_time()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/repay_loan', methods=['POST'])
def repay_loan():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    id_ = request.form.get('id')
    name = request.form.get('name')
    amt = float(request.form.get('amount') or 0)
    date_ = request.form.get('date') or now_date()
    if not all([id_, name, amt]):
        return jsonify({'error': 'Fill loan repayment fields'}), 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM loans WHERE id=? AND name=?', (id_, name))
        loan = c.fetchone()
        if not loan:
            return jsonify({'error': 'Loan not found'}), 404
        if loan['status'] == 'Cleared':
            return jsonify({'error': 'Loan already cleared'}), 400
        today = datetime.strptime(date_, '%Y-%m-%d').date()
        due = datetime.strptime(loan['dueDate'], '%Y-%m-%d').date()
        penalty = 0
        if today > due and loan['totalRemaining'] > 0:
            penalty = round(loan['totalRemaining'] * LOAN_LATE_PENALTY_PCT)
            c.execute('UPDATE loans SET totalRemaining=totalRemaining+? WHERE id=?', (penalty, id_))
            c.execute('INSERT INTO incomes (id, source, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                      (f'PEN{int(datetime.now().timestamp()*1000)}', f'Late penalty on loan {id_}', penalty, date_, now_time()))
            c.execute('UPDATE state SET totalCollected=totalCollected+? WHERE id=1', (penalty,))
        paid = min(amt, loan['totalRemaining'])
        new_remaining = max(0, loan['totalRemaining'] - paid)
        status = 'Cleared' if new_remaining <= 0 else 'Active'
        c.execute('UPDATE loans SET totalRemaining=?, status=? WHERE id=?', (new_remaining, status, id_))
        c.execute('INSERT INTO repayments (id, loanId, name, paid, balance, date) VALUES (?, ?, ?, ?, ?, ?)',
                  (f'R{int(datetime.now().timestamp()*1000)}', id_, name, paid, new_remaining, date_))
        c.execute('INSERT INTO incomes (id, source, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                  (f'INC-LOAN-PAY-{int(datetime.now().timestamp()*1000)}', f'Loan repayment {id_}', paid, date_, now_time()))
        c.execute('UPDATE state SET totalCollected=totalCollected+? WHERE id=1', (paid,))
        conn.commit()
    receipt_text = f'''Loan Repayment Receipt\nLoan ID: {id_}\nName: {name}\nPaid: {format_ugx(paid)}
Remaining: {format_ugx(new_remaining)}\nDate: {date_} {now_time()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/loans')
def get_loans():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM loans')
        loans = [dict(row) for row in c.fetchall()]
    return jsonify(loans)

@app.route('/repayments')
def get_repayments():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM repayments')
        repayments = [dict(row) for row in c.fetchall()]
    return jsonify(repayments)

@app.route('/add_saving', methods=['POST'])
def add_saving():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    name = request.form.get('name')
    amount = float(request.form.get('amount') or 0)
    date_saved = request.form.get('date') or now_date()
    sched = request.form.get('sched')
    if not all([name, amount, date_saved, sched]):
        return jsonify({'error': 'Fill all savings fields'}), 400
    if amount < 10000:
        return jsonify({'error': 'Minimum saving is UGX 10,000'}), 400
    tier = max([t for t in SAVINGS_TIERS if amount >= t['min']], key=lambda x: x['min'], default=None)
    if not tier:
        return jsonify({'error': 'No tier found for this amount'}), 400
    required_weeks = tier['weeks']
    interest_pct = tier['pct']
    d1 = datetime.strptime(date_saved, '%Y-%m-%d')
    d2 = datetime.strptime(sched, '%Y-%m-%d')
    days = max(0, (d2 - d1).days)
    full_term_days = required_weeks * 7
    full_interest = round(amount * interest_pct) if days >= full_term_days else 0
    rec_id = f'S{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO savings (id, name, amount, dateSaved, sched, termWeeks, interestPct, interestIfHeld, daysScheduled, withdrawn)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (rec_id, name, amount, date_saved, sched, required_weeks, interest_pct, full_interest, days, 0))
        conn.commit()
    receipt_text = f'''Saving Order\nName: {name}\nAmount: {format_ugx(amount)}\nTerm weeks (tier): {required_weeks}
Interest% (if held): {round(interest_pct*100)}%\nInterest(if held): {format_ugx(full_interest)}
Scheduled withdraw: {sched}\nSaved on: {date_saved} {now_time()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/process_withdrawal', methods=['POST'])
def process_withdrawal():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    name = request.form.get('name')
    amount_requested = float(request.form.get('amount') or 0)
    actual_date = request.form.get('date') or now_date()
    if not name or not amount_requested:
        return jsonify({'error': 'Fill withdrawal fields'}), 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM savings WHERE name=? AND withdrawn=0', (name,))
        s = c.fetchone()
        if not s:
            return jsonify({'error': 'No active saving found for that name'}), 404
        ds = datetime.strptime(s['dateSaved'], '%Y-%m-%d')
        da = datetime.strptime(actual_date, '%Y-%m-%d')
        days_held = max(0, (da - ds).days)
        pct = s['interestPct']
        full_term_days = s['termWeeks'] * 7
        earned_interest = 0 if days_held <= 0 else round(s['amount'] * pct * (min(days_held, full_term_days) / full_term_days))
        matured = da.date() >= datetime.strptime(s['sched'], '%Y-%m-%d').date()
        payout_available = (s['amount'] + s['interestIfHeld']) if matured else (s['amount'] + earned_interest)
        if amount_requested > payout_available:
            return jsonify({'error': f'Requested {format_ugx(amount_requested)} exceeds available {format_ugx(payout_available)}'}), 400
        c.execute('INSERT INTO expenditures (id, desc, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                  (f'EXP-WD-{int(datetime.now().timestamp()*1000)}', f'Saving Withdrawal {s["id"]} by {name}', amount_requested, actual_date, now_time()))
        c.execute('UPDATE state SET totalExpenditure=totalExpenditure+? WHERE id=1', (amount_requested,))
        if abs(amount_requested - payout_available) < 1:
            c.execute('UPDATE savings SET withdrawn=1 WHERE id=?', (s['id'],))
        else:
            c.execute('UPDATE savings SET amount=? WHERE id=?', (max(0, s['amount'] - amount_requested), s['id']))
        conn.commit()
    receipt_text = f'''Saving Withdrawal Receipt\nName: {name}\nRequested: {format_ugx(amount_requested)}
Paid: {format_ugx(amount_requested)}\nInterest earned (days): {format_ugx(earned_interest)}\nMatured: {matured}
Date: {actual_date} {now_time()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/savings')
def get_savings():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM savings')
        savings = [dict(row) for row in c.fetchall()]
    return jsonify(savings)

@app.route('/add_minister_payment', methods=['POST'])
def add_minister_payment():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    name = request.form.get('name')
    type_ = request.form.get('type')
    paid = float(request.form.get('amount') or 0)
    date_ = request.form.get('date') or now_date()
    if not name or not type_:
        return jsonify({'error': 'Fill minister payment fields'}), 400
    if paid <= 0:
        return jsonify({'error': 'Enter paid amount'}), 400
    required = FIXED.get(type_, paid)
    balance = max(0, required - paid)
    rec_id = f'MIN{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO minister_payments (id, name, type, required, paid, balance, date)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''', (rec_id, name, type_, required, paid, balance, date_))
        c.execute('UPDATE state SET totalCollected=totalCollected+? WHERE id=1', (paid,))
        conn.commit()
    receipt_text = f'''Minister Payment\nName: {name}\nType: {type_}\nPaid: {format_ugx(paid)}
Required: {format_ugx(required)}\nBalance: {format_ugx(balance)}\nDate: {date_} {now_time()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/pay_minister_balance/<min_id>', methods=['POST'])
def pay_minister_balance(min_id):
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    amount = float(request.form.get('amount') or 0)
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM minister_payments WHERE id=?', (min_id,))
        rec = c.fetchone()
        if not rec:
            return jsonify({'error': 'Not found'}), 404
        to_pay = min(amount, rec['balance'])
        if to_pay <= 0:
            return jsonify({'error': 'Invalid amount'}), 400
        c.execute('UPDATE minister_payments SET paid=paid+?, balance=balance-? WHERE id=?', (to_pay, to_pay, min_id))
        c.execute('UPDATE state SET totalCollected=totalCollected+? WHERE id=1', (to_pay,))
        conn.commit()
        receipt_text = f'''Minister Balance Payment\nName: {rec['name']}\nType: {rec['type']}\nPaid: {format_ugx(to_pay)}
Remaining Balance: {format_ugx(rec['balance']-to_pay)}\nTime: {timestamp()}'''
        return jsonify({'receipt': receipt_text})

@app.route('/minister_payments')
def get_minister_payments():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM minister_payments')
        payments = [dict(row) for row in c.fetchall()]
    return jsonify(payments)

@app.route('/add_income', methods=['POST'])
def add_income():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    source = request.form.get('source')
    amt = float(request.form.get('amount') or 0)
    date_ = request.form.get('date') or now_date()
    if not source or not amt:
        return jsonify({'error': 'Fill income fields'}), 400
    rec_id = f'INC{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO incomes (id, source, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                  (rec_id, source, amt, date_, now_time()))
        c.execute('UPDATE state SET totalCollected=totalCollected+? WHERE id=1', (amt,))
        conn.commit()
    receipt_text = f'''Income Receipt\nSource: {source}\nAmount: {format_ugx(amt)}\nDate: {date_} {now_time()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/incomes')
def get_incomes():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM incomes')
        incomes = [dict(row) for row in c.fetchall()]
    return jsonify(incomes)

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    name = request.form.get('name')
    role = request.form.get('role')
    date_ = request.form.get('date') or now_date()
    time_ = request.form.get('time') or now_time()
    meeting_start = request.form.get('start') or MEETING_START_DEFAULT
    if not all([name, role, date_, time_]):
        return jsonify({'error': 'Fill attendance fields'}), 400
    h_check, m_check = map(int, time_.split(':'))
    h_start, m_start = map(int, meeting_start.split(':'))
    late = (h_check > h_start) or (h_check == h_start and m_check > m_start)
    status = 'Late' if late else 'Present'
    fine = LATE_FINE_AMOUNT if late else 0
    rec_id = f'ATT{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO attendance (id, name, role, date, time, status, fine) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (rec_id, name, role, date_, time_, status, fine))
        if late:
            c.execute('INSERT INTO incomes (id, source, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                      (f'FINE{int(datetime.now().timestamp()*1000)}', f'Late fine: {name}', fine, date_, now_time()))
            c.execute('UPDATE state SET totalCollected=totalCollected+? WHERE id=1', (fine,))
        conn.commit()
    receipt_text = f'''Attendance Receipt\nName: {name}\nRole: {role}\nDate: {date_}\nTime: {time_}
Status: {status}\nFine: {format_ugx(fine)}\nTimestamp: {timestamp()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/attendance')
def get_attendance():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM attendance')
        attendance = [dict(row) for row in c.fetchall()]
    return jsonify(attendance)

@app.route('/assign_duty', methods=['POST'])
def assign_duty():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    name = request.form.get('name')
    role = request.form.get('role')
    task = request.form.get('task')
    week = request.form.get('week')
    if not all([name, role, task, week]):
        return jsonify({'error': 'Fill duty fields'}), 400
    rec_id = f'D{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO duties (id, name, role, task, week) VALUES (?, ?, ?, ?, ?)',
                  (rec_id, name, role, task, week))
        conn.commit()
    return jsonify({'message': 'Duty assigned'})

@app.route('/duties')
def get_duties():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM duties')
        duties = [dict(row) for row in c.fetchall()]
    return jsonify(duties)

@app.route('/register_student', methods=['POST'])
def register_student():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    name = request.form.get('name')
    cls = request.form.get('class')
    stream = request.form.get('stream')
    house = request.form.get('house')
    date_ = request.form.get('date') or now_date()
    if not all([name, cls, stream, house]):
        return jsonify({'error': 'Fill student fields'}), 400
    rec_id = f'ST{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO students (id, name, cls, stream, house, date) VALUES (?, ?, ?, ?, ?, ?)',
                  (rec_id, name, cls, stream, house, date_))
        conn.commit()
    receipt_text = f'''Student Registration\nName: {name}\nClass: {cls}\nStream: {stream}\nHouse: {house}\nDate: {date_} {now_time()}'''
    return jsonify({'receipt': receipt_text})

@app.route('/students')
def get_students():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM students')
        students = [dict(row) for row in c.fetchall()]
    return jsonify(students)

@app.route('/send_message', methods=['POST'])
def send_message():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    from_user = request.form.get('from')
    to_user = request.form.get('to')
    content = request.form.get('content')
    date_ = request.form.get('date') or now_date()
    if not all([from_user, to_user, content]):
        return jsonify({'error': 'Fill message fields'}), 400
    rec_id = f'MSG{int(datetime.now().timestamp()*1000)}'
    with get_db() as conn:
        c = conn.cursor()
        c.execute('INSERT INTO messages (id, from_user, to_user, content, date, time, read) VALUES (?, ?, ?, ?, ?, ?, ?)',
                  (rec_id, from_user, to_user, content, date_, now_time(), 0))
        conn.commit()
    return jsonify({'message': 'Message sent'})

@app.route('/messages')
def get_messages():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT * FROM messages')
        messages = [dict(row) for row in c.fetchall()]
    return jsonify(messages)

@app.route('/set_finance_pin', methods=['POST'])
def set_finance_pin():
    if 'role' not in session or session['role'] != 'Finance':
        return jsonify({'error': 'Unauthorized'}), 401
    new_pin = request.form.get('new_pin')
    cur_pin = request.form.get('cur_pin')
    if not new_pin:
        return jsonify({'error': 'Enter new finance PIN'}), 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT financePin FROM state WHERE id=1')
        current = c.fetchone()['financePin']
        if current and current != cur_pin:
            return jsonify({'error': 'Current finance PIN incorrect'}), 400
        c.execute('UPDATE state SET financePin=? WHERE id=1', (new_pin,))
        conn.commit()
    return jsonify({'message': 'Finance PIN set'})

@app.route('/override_finance_pin', methods=['POST'])
def override_finance_pin():
    if 'role' not in session or session['role'] not in ['Patron', 'President']:
        return jsonify({'error': 'Only Patron or President can override'}), 401
    role = request.form.get('role')
    pin = request.form.get('pin')
    new_pin = request.form.get('new_pin')
    if role not in ['Patron', 'President'] or pin != ROLE_PINS[role]:
        return jsonify({'error': 'Incorrect leader PIN'}), 400
    if not new_pin:
        return jsonify({'error': 'Enter new finance PIN'}), 400
    with get_db() as conn:
        c = conn.cursor()
        c.execute('UPDATE state SET financePin=? WHERE id=1', (new_pin,))
        conn.commit()
    return jsonify({'message': 'Finance PIN overridden and set'})

@app.route('/clear_all_data', methods=['POST'])
def clear_all_data():
    if 'role' not in session or session['role'] != 'Finance':
        return jsonify({'error': 'Unauthorized'}), 401
    pin = request.form.get('pin')
    with get_db() as conn:
        c = conn.cursor()
        c.execute('SELECT financePin FROM state WHERE id=1')
        finance_pin = c.fetchone()['financePin']
        if not finance_pin:
            return jsonify({'error': 'No finance PIN set. Use override.'}), 400
        if pin != finance_pin:
            return jsonify({'error': 'Finance PIN incorrect'}), 400
        c.executescript('''
            DELETE FROM payments; DELETE FROM expenditures; DELETE FROM loans; DELETE FROM repayments;
            DELETE FROM savings; DELETE FROM minister_payments; DELETE FROM incomes; DELETE FROM attendance;
            DELETE FROM duties; DELETE FROM students; DELETE FROM messages;
            UPDATE state SET totalCollected=0, totalExpenditure=0 WHERE id=1;
        ''')
        conn.commit()
    return jsonify({'message': 'All data cleared'})

@app.route('/export_data')
def export_data():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    with get_db() as conn:
        c = conn.cursor()
        state = {
            'payments': [dict(row) for row in c.execute('SELECT * FROM payments').fetchall()],
            'expenditures': [dict(row) for row in c.execute('SELECT * FROM expenditures').fetchall()],
            'loans': [dict(row) for row in c.execute('SELECT * FROM loans').fetchall()],
            'repayments': [dict(row) for row in c.execute('SELECT * FROM repayments').fetchall()],
            'savings': [dict(row) for row in c.execute('SELECT * FROM savings').fetchall()],
            'ministerPayments': [dict(row) for row in c.execute('SELECT * FROM minister_payments').fetchall()],
            'incomes': [dict(row) for row in c.execute('SELECT * FROM incomes').fetchall()],
            'attendance': [dict(row) for row in c.execute('SELECT * FROM attendance').fetchall()],
            'duties': [dict(row) for row in c.execute('SELECT * FROM duties').fetchall()],
            'students': [dict(row) for row in c.execute('SELECT * FROM students').fetchall()],
            'messages': [dict(row) for row in c.execute('SELECT * FROM messages').fetchall()],
            'totalCollected': c.execute('SELECT totalCollected FROM state WHERE id=1').fetchone()['totalCollected'],
            'totalExpenditure': c.execute('SELECT totalExpenditure FROM state WHERE id=1').fetchone()['totalExpenditure'],
            'financePin': c.execute('SELECT financePin FROM state WHERE id=1').fetchone()['financePin']
        }
    data_str = json.dumps(state, indent=2)
    output = io.BytesIO()
    output.write(data_str.encode('utf-8'))
    output.seek(0)
    return send_file(output, download_name=f'gcc_cabinet_data_{now_date()}.json', as_attachment=True)

@app.route('/import_data', methods=['POST'])
def import_data():
    if 'role' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    if not file.filename.endswith('.json'):
        return jsonify({'error': 'Invalid file type'}), 400
    try:
        state = json.load(file)
        with get_db() as conn:
            c = conn.cursor()
            c.executescript('''
                DELETE FROM payments; DELETE FROM expenditures; DELETE FROM loans; DELETE FROM repayments;
                DELETE FROM savings; DELETE FROM minister_payments; DELETE FROM incomes; DELETE FROM attendance;
                DELETE FROM duties; DELETE FROM students; DELETE FROM messages;
            ''')
            for p in state.get('payments', []):
                c.execute('''INSERT INTO payments (id, name, cls, stream, house, type, term, amount, required, balance, date, time)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (p['id'], p['name'], p['cls'], p['stream'], p['house'], p['type'], p['term'], p['amount'], p['required'], p['balance'], p['date'], p.get('time')))
            for e in state.get('expenditures', []):
                c.execute('INSERT INTO expenditures (id, desc, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                          (e['id'], e['desc'], e['amt'], e['date'], e.get('time')))
            for l in state.get('loans', []):
                c.execute('''INSERT INTO loans (id, name, principal, interestPct, total, totalRemaining, status, date, dueDate, disbursed)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (l['id'], l['name'], l['principal'], l['interestPct'], l['total'], l['totalRemaining'], l['status'], l['date'], l['dueDate'], l['disbursed']))
            for r in state.get('repayments', []):
                c.execute('INSERT INTO repayments (id, loanId, name, paid, balance, date) VALUES (?, ?, ?, ?, ?, ?)',
                          (r['id'], r['loanId'], r['name'], r['paid'], r['balance'], r['date']))
            for s in state.get('savings', []):
                c.execute('''INSERT INTO savings (id, name, amount, dateSaved, sched, termWeeks, interestPct, interestIfHeld, daysScheduled, withdrawn)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                          (s['id'], s['name'], s['amount'], s['dateSaved'], s['sched'], s['termWeeks'], s['interestPct'], s['interestIfHeld'], s['daysScheduled'], s['withdrawn']))
            for m in state.get('ministerPayments', []):
                c.execute('INSERT INTO minister_payments (id, name, type, required, paid, balance, date) VALUES (?, ?, ?, ?, ?, ?, ?)',
                          (m['id'], m['name'], m['type'], m['required'], m['paid'], m['balance'], m['date']))
            for i in state.get('incomes', []):
                c.execute('INSERT INTO incomes (id, source, amt, date, time) VALUES (?, ?, ?, ?, ?)',
                          (i['id'], i['source'], i['amt'], i['date'], i.get('time')))
            for a in state.get('attendance', []):
                c.execute('INSERT INTO attendance (id, name, role, date, time, status, fine) VALUES (?, ?, ?, ?, ?, ?, ?)',
                          (a['id'], a['name'], a['role'], a['date'], a['time'], a['status'], a['fine']))
            for d in state.get('duties', []):
                c.execute('INSERT INTO duties (id, name, role, task, week) VALUES (?, ?, ?, ?, ?)',
                          (d['id'], d['name'], d['role'], d['task'], d['week']))
            for s in state.get('students', []):
                c.execute('INSERT INTO students (id, name, cls, stream, house, date) VALUES (?, ?, ?, ?, ?, ?)',
                          (s['id'], s['name'], s['cls'], s['stream'], s['house'], s['date']))
            for m in state.get('messages', []):
                c.execute('INSERT INTO messages (id, from_user, to_user, content, date, time, read) VALUES (?, ?, ?, ?, ?, ?, ?)',
                          (m['id'], m['from_user'], m['to_user'], m['content'], m['date'], m['time'], m['read']))
            c.execute('UPDATE state SET totalCollected=?, totalExpenditure=?, financePin=? WHERE id=1',
                      (state.get('totalCollected', 0), state.get('totalExpenditure', 0), state.get('financePin')))
            conn.commit()
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON file'}), 400
    return jsonify({'message': 'Data imported'})

@app.route('/download_receipt', methods=['POST'])
def download_receipt():
    text = request.form.get('text')
    if not text:
        return jsonify({'error': 'No receipt text provided'}), 400
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    lines = text.split('\n')
    y = 750
    for line in lines:
        c.drawString(30, y, line)
        y -= 15
    c.save()
    buffer.seek(0)
    return send_file(buffer, download_name='receipt.pdf', as_attachment=True)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)