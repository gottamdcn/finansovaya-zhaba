import sqlite3

conn = sqlite3.connect('zhaba.db')

try:
    conn.execute('ALTER TABLE users ADD COLUMN last_seen TEXT')
    print('Колонка last_seen добавлена')
except Exception as e:
    print(f'Колонка уже есть: {e}')

try:
    conn.execute('ALTER TABLE debts ADD COLUMN initial_amount REAL')
    conn.execute('UPDATE debts SET initial_amount = amount WHERE initial_amount IS NULL')
    print('Колонка initial_amount добавлена')
except Exception as e:
    print(f'Колонка уже есть: {e}')

conn.execute("UPDATE users SET last_seen = date('now') WHERE last_seen IS NULL")
conn.commit()
conn.close()
print('done')
