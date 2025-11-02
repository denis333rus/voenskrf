from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)

# Конфигурация из переменных окружения
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# Конфигурация БД
DATABASE = os.environ.get('DATABASE_URL', 'gvsu.db')
# Railway использует DATABASE_URL для PostgreSQL, но у нас SQLite
# Если DATABASE_URL существует и это не SQLite, можно будет добавить поддержку PostgreSQL
if DATABASE.startswith('postgres://') or DATABASE.startswith('postgresql://'):
    # Для PostgreSQL нужна другая библиотека, пока используем SQLite
    DATABASE = 'gvsu.db'

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Таблица новостей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            date TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица пользователей (регистрация)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            experience TEXT,
            education TEXT,
            rank TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Добавить поле status если его нет (для существующих БД)
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN status TEXT DEFAULT "pending"')
    except sqlite3.OperationalError:
        pass  # Поле уже существует
    
    # Таблица сотрудников
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            position TEXT NOT NULL,
            department TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица дел
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            case_number TEXT,
            assigned_to INTEGER,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (assigned_to) REFERENCES employees(id)
        )
    ''')
    
    # Таблица протоколов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS protocols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            protocol_number TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (case_id) REFERENCES cases(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # Таблица админов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')
    
    # Создать дефолтного админа, если его нет
    cursor.execute('SELECT COUNT(*) FROM admins')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO admins (username, password) VALUES (?, ?)', 
                      ('admin', 'admin123'))
    
    conn.commit()
    conn.close()

def get_db():
    """Получить соединение с БД"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Инициализация БД при старте
init_db()

@app.route('/')
def index():
    """Главная страница"""
    conn = get_db()
    news = conn.execute('SELECT * FROM news ORDER BY date DESC LIMIT 5').fetchall()
    conn.close()
    return render_template('base.html', news=news)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Регистрация пользователя"""
    if request.method == 'POST':
        conn = get_db()
        # Проверка существования пользователя
        existing_user = conn.execute('SELECT * FROM users WHERE username = ?', 
                                    (request.form['username'],)).fetchone()
        if existing_user:
            flash('Пользователь с таким логином уже существует', 'error')
            return render_template('register.html')
        
        # Создание пользователя со статусом pending
        conn.execute('''
            INSERT INTO users (full_name, username, password, experience, education, rank, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
        ''', (
            request.form['full_name'],
            request.form['username'],
            request.form['password'],
            request.form.get('experience', ''),
            request.form.get('education', ''),
            request.form.get('rank', '')
        ))
        conn.commit()
        conn.close()
        flash('Регистрация успешна! Ваша заявка отправлена администратору на одобрение. Вы получите доступ после проверки.', 'success')
        return redirect(url_for('index'))
    
    return render_template('register.html')

@app.route('/user/login', methods=['GET', 'POST'])
def user_login():
    """Вход пользователя"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                           (username, password)).fetchone()
        conn.close()
        
        if user:
            if user['status'] == 'pending':
                flash('Ваш аккаунт еще не одобрен администратором. Ожидайте проверки.', 'error')
            elif user['status'] == 'rejected':
                flash('Ваш аккаунт был отклонен администратором.', 'error')
            elif user['status'] == 'approved':
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash('Вы успешно вошли в систему', 'success')
                return redirect(url_for('user_dashboard'))
            else:
                flash('Неверный логин или пароль', 'error')
        else:
            flash('Неверный логин или пароль', 'error')
    
    return render_template('user/login.html')

@app.route('/user/logout')
def user_logout():
    """Выход пользователя"""
    session.pop('user_id', None)
    session.pop('username', None)
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

@app.route('/user/dashboard')
def user_dashboard():
    """Дэшборд пользователя"""
    if not session.get('user_id'):
        return redirect(url_for('user_login'))
    
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    cases = conn.execute('''
        SELECT c.*, e.full_name as assigned_employee 
        FROM cases c 
        LEFT JOIN employees e ON c.assigned_to = e.id 
        ORDER BY c.created_at DESC
    ''').fetchall()
    
    # Получить протоколы текущего пользователя
    protocols = conn.execute('''
        SELECT p.*, c.title as case_title, c.case_number as case_number
        FROM protocols p
        JOIN cases c ON p.case_id = c.id
        WHERE p.user_id = ?
        ORDER BY p.created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    conn.close()
    
    return render_template('user/dashboard.html', user=user, cases=cases, protocols=protocols)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Вход в админ панель"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db()
        admin = conn.execute('SELECT * FROM admins WHERE username = ? AND password = ?', 
                            (username, password)).fetchone()
        conn.close()
        
        if admin:
            session['admin'] = True
            flash('Вы успешно вошли в систему', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Неверное имя пользователя или пароль', 'error')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    """Выход из админ панели"""
    session.pop('admin', None)
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
def admin_dashboard():
    """Главная страница админ панели"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    news_count = conn.execute('SELECT COUNT(*) FROM news').fetchone()[0]
    users_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    pending_users_count = conn.execute('SELECT COUNT(*) FROM users WHERE status = "pending"').fetchone()[0]
    employees_count = conn.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
    cases_count = conn.execute('SELECT COUNT(*) FROM cases').fetchone()[0]
    protocols_count = conn.execute('SELECT COUNT(*) FROM protocols').fetchone()[0]
    conn.close()
    
    return render_template('admin/dashboard.html', 
                         news_count=news_count,
                         users_count=users_count,
                         pending_users_count=pending_users_count,
                         employees_count=employees_count,
                         cases_count=cases_count,
                         protocols_count=protocols_count)

@app.route('/admin/news', methods=['GET', 'POST'])
def admin_news():
    """Управление новостями"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''
            INSERT INTO news (title, content, date)
            VALUES (?, ?, ?)
        ''', (
            request.form['title'],
            request.form['content'],
            request.form['date']
        ))
        conn.commit()
        conn.close()
        flash('Новость успешно добавлена', 'success')
        return redirect(url_for('admin_news'))
    
    conn = get_db()
    news = conn.execute('SELECT * FROM news ORDER BY date DESC').fetchall()
    conn.close()
    return render_template('admin/news.html', news=news)

@app.route('/admin/news/delete/<int:news_id>')
def delete_news(news_id):
    """Удаление новости"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM news WHERE id = ?', (news_id,))
    conn.commit()
    conn.close()
    flash('Новость удалена', 'success')
    return redirect(url_for('admin_news'))

@app.route('/admin/employees', methods=['GET', 'POST'])
def admin_employees():
    """Управление сотрудниками"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''
            INSERT INTO employees (full_name, position, department)
            VALUES (?, ?, ?)
        ''', (
            request.form['full_name'],
            request.form['position'],
            request.form.get('department', '')
        ))
        conn.commit()
        conn.close()
        flash('Сотрудник добавлен', 'success')
        return redirect(url_for('admin_employees'))
    
    conn = get_db()
    employees = conn.execute('SELECT * FROM employees ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('admin/employees.html', employees=employees)

@app.route('/admin/employees/<int:emp_id>/delete')
def delete_employee(emp_id):
    """Удаление сотрудника"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM employees WHERE id = ?', (emp_id,))
    conn.commit()
    conn.close()
    flash('Сотрудник удален', 'success')
    return redirect(url_for('admin_employees'))

@app.route('/admin/cases', methods=['GET', 'POST'])
def admin_cases():
    """Управление делами"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''
            INSERT INTO cases (title, description, case_number, assigned_to, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            request.form['title'],
            request.form.get('description', ''),
            request.form.get('case_number', ''),
            request.form.get('assigned_to') if request.form.get('assigned_to') else None,
            request.form.get('status', 'open')
        ))
        conn.commit()
        conn.close()
        flash('Дело успешно создано', 'success')
        return redirect(url_for('admin_cases'))
    
    conn = get_db()
    cases = conn.execute('''
        SELECT c.*, e.full_name as assigned_employee 
        FROM cases c 
        LEFT JOIN employees e ON c.assigned_to = e.id 
        ORDER BY c.created_at DESC
    ''').fetchall()
    employees = conn.execute('SELECT * FROM employees ORDER BY full_name').fetchall()
    conn.close()
    
    return render_template('admin/cases.html', cases=cases, employees=employees)

@app.route('/admin/cases/<int:case_id>/delete')
def delete_case(case_id):
    """Удаление дела"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM cases WHERE id = ?', (case_id,))
    conn.commit()
    conn.close()
    flash('Дело удалено', 'success')
    return redirect(url_for('admin_cases'))

@app.route('/admin/users')
def admin_users():
    """Просмотр и управление пользователями"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    users = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/<int:user_id>/approve', methods=['POST'])
def approve_user(user_id):
    """Одобрение пользователя"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('UPDATE users SET status = ? WHERE id = ?', ('approved', user_id))
    conn.commit()
    conn.close()
    flash('Пользователь одобрен', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/reject', methods=['POST'])
def reject_user(user_id):
    """Отклонение пользователя"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('UPDATE users SET status = ? WHERE id = ?', ('rejected', user_id))
    conn.commit()
    conn.close()
    flash('Пользователь отклонен', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
def edit_user(user_id):
    """Редактирование пользователя"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    
    if request.method == 'POST':
        conn.execute('''
            UPDATE users 
            SET full_name = ?, username = ?, password = ?, experience = ?, education = ?, rank = ?, status = ?
            WHERE id = ?
        ''', (
            request.form['full_name'],
            request.form['username'],
            request.form['password'],
            request.form.get('experience', ''),
            request.form.get('education', ''),
            request.form.get('rank', ''),
            request.form['status'],
            user_id
        ))
        conn.commit()
        conn.close()
        flash('Пользователь обновлен', 'success')
        return redirect(url_for('admin_users'))
    
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    
    if not user:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('admin_users'))
    
    return render_template('admin/edit_user.html', user=user)

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
def delete_user(user_id):
    """Удаление пользователя"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    flash('Пользователь удален', 'success')
    return redirect(url_for('admin_users'))

@app.route('/user/protocols/create', methods=['GET', 'POST'])
def create_protocol():
    """Создание протокола к делу"""
    if not session.get('user_id'):
        return redirect(url_for('user_login'))
    
    conn = get_db()
    
    if request.method == 'POST':
        conn.execute('''
            INSERT INTO protocols (case_id, user_id, title, content, protocol_number)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            request.form['case_id'],
            session['user_id'],
            request.form['title'],
            request.form['content'],
            request.form.get('protocol_number', '')
        ))
        conn.commit()
        conn.close()
        flash('Протокол успешно создан', 'success')
        return redirect(url_for('user_dashboard'))
    
    # Получить список дел для выбора
    cases = conn.execute('SELECT * FROM cases ORDER BY created_at DESC').fetchall()
    conn.close()
    
    return render_template('user/create_protocol.html', cases=cases)

@app.route('/user/protocols/<int:protocol_id>')
def view_protocol(protocol_id):
    """Просмотр протокола"""
    if not session.get('user_id'):
        return redirect(url_for('user_login'))
    
    conn = get_db()
    protocol = conn.execute('''
        SELECT p.*, c.title as case_title, c.case_number as case_number, u.full_name as user_name
        FROM protocols p
        JOIN cases c ON p.case_id = c.id
        JOIN users u ON p.user_id = u.id
        WHERE p.id = ? AND p.user_id = ?
    ''', (protocol_id, session['user_id'])).fetchone()
    conn.close()
    
    if not protocol:
        flash('Протокол не найден', 'error')
        return redirect(url_for('user_dashboard'))
    
    return render_template('user/view_protocol.html', protocol=protocol)

@app.route('/user/protocols/<int:protocol_id>/delete', methods=['POST'])
def delete_protocol(protocol_id):
    """Удаление протокола"""
    if not session.get('user_id'):
        return redirect(url_for('user_login'))
    
    conn = get_db()
    # Проверяем, что протокол принадлежит текущему пользователю
    protocol = conn.execute('SELECT * FROM protocols WHERE id = ? AND user_id = ?', 
                           (protocol_id, session['user_id'])).fetchone()
    
    if protocol:
        conn.execute('DELETE FROM protocols WHERE id = ?', (protocol_id,))
        conn.commit()
        flash('Протокол удален', 'success')
    else:
        flash('Протокол не найден или у вас нет прав на его удаление', 'error')
    
    conn.close()
    return redirect(url_for('user_dashboard'))

@app.route('/admin/protocols')
def admin_protocols():
    """Просмотр всех протоколов (админ)"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    protocols = conn.execute('''
        SELECT p.*, c.title as case_title, c.case_number as case_number, 
               u.full_name as user_name, u.username as user_username
        FROM protocols p
        JOIN cases c ON p.case_id = c.id
        JOIN users u ON p.user_id = u.id
        ORDER BY p.created_at DESC
    ''').fetchall()
    conn.close()
    
    return render_template('admin/protocols.html', protocols=protocols)

@app.route('/admin/protocols/<int:protocol_id>')
def admin_view_protocol(protocol_id):
    """Просмотр конкретного протокола (админ)"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    protocol = conn.execute('''
        SELECT p.*, c.title as case_title, c.case_number as case_number, 
               u.full_name as user_name, u.username as user_username
        FROM protocols p
        JOIN cases c ON p.case_id = c.id
        JOIN users u ON p.user_id = u.id
        WHERE p.id = ?
    ''', (protocol_id,)).fetchone()
    conn.close()
    
    if not protocol:
        flash('Протокол не найден', 'error')
        return redirect(url_for('admin_protocols'))
    
    return render_template('admin/view_protocol.html', protocol=protocol)

@app.route('/admin/protocols/<int:protocol_id>/delete', methods=['POST'])
def admin_delete_protocol(protocol_id):
    """Удаление протокола (админ)"""
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    conn.execute('DELETE FROM protocols WHERE id = ?', (protocol_id,))
    conn.commit()
    conn.close()
    flash('Протокол удален', 'success')
    return redirect(url_for('admin_protocols'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
