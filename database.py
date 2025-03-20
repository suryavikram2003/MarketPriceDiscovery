import sqlite3

def init_db():
    conn = sqlite3.connect('market_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS market_prices
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  state TEXT,
                  district TEXT,
                  market TEXT,
                  commodity TEXT,
                  price REAL,
                  date TEXT)''')
    conn.commit()
    conn.close()

def insert_market_data(data):
    conn = sqlite3.connect('market_data.db')
    c = conn.cursor()
    c.execute('''INSERT INTO market_prices 
                 (state, district, market, commodity, price, date)
                 VALUES (?, ?, ?, ?, ?, ?)''',
                 (data['state'], data['district'], data['market'],
                  data['commodity'], data['price'], data['date']))
    conn.commit()
    conn.close()
