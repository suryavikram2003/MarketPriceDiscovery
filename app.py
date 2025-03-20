from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import requests
from datetime import datetime, timedelta
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///market.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'

# Initialize database and login manager
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Database Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)

class MarketData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    commodity = db.Column(db.String(100))
    market = db.Column(db.String(100))
    price = db.Column(db.Float)
    date = db.Column(db.String(20))
    state = db.Column(db.String(100))
    district = db.Column(db.String(100))

# Create database tables
with app.app_context():
    db.create_all()
    # Create a test user if none exists
    if not User.query.filter_by(username='admin').first():
        test_user = User(
            username='admin',
            password='admin123',
            email='admin@example.com'
        )
        db.session.add(test_user)
        db.session.commit()
        logger.info("Admin user created successfully")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class MarketAPI:
    BASE_URL = "https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24"
    API_KEY = "579b464db66ec23bdd000001ae581df7f2744e205d6478735786d3ae"
    
    def fetch_market_data(self, state=None, district=None, date=None, commodity=None):
        """Fetch market data with fallback to yesterday if today's data not found"""
        today = datetime.now().strftime('%d/%m/%Y')
        data = self.fetch_data_for_date(today, state, district, commodity)
        
        if not data.get('records'):
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%d/%m/%Y')
            data = self.fetch_data_for_date(yesterday, state, district, commodity)
            
            if not data.get('records'):
                for days_back in range(2, 10):
                    previous_date = (datetime.now() - timedelta(days=days_back)).strftime('%d/%m/%Y')
                    data = self.fetch_data_for_date(previous_date, state, district, commodity)
                    if data.get('records'):
                        logger.info(f"Using data from {previous_date}")
                        break
        
        return data

    def fetch_data_for_date(self, date, state=None, district=None, commodity=None):
        """Fetch market data for a specific date"""
        try:
            logger.info(f"Fetching market data for date: {date}")
            params = {
                'api-key': self.API_KEY,
                'format': 'json',
                'filters[Arrival_Date]': date,
                'limit': 1000
            }
            
            # Add optional filters with defaults
            if state:
                params['filters[State]'] = state
            else:
                params['filters[State]'] = 'Tamil Nadu'
                
            if district:
                params['filters[District]'] = district
            else:
                params['filters[District]'] = 'Salem'
                
            if commodity:
                params['filters[Commodity]'] = commodity

            # Make API request
            logger.info(f"API request params: {params}")
            response = requests.get(
                self.BASE_URL,
                headers={'Accept': 'application/json'},
                params=params,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"API error: Status {response.status_code}, Response: {response.text[:200]}")
                return {'records': [], 'total': 0, 'error': f"API returned status code {response.status_code}"}
                
            data = response.json()

            if data and 'records' in data:
                # Transform records - divide prices by 100 to get per kg prices
                transformed_records = []
                for index, record in enumerate(data['records']):
                    try:
                        transformed_record = {
                            'id': index,
                            'state': record.get('State', ''),
                            'district': record.get('District', ''),
                            'market': record.get('Market', ''),
                            'commodity': record.get('Commodity', ''),
                            'variety': record.get('Variety', ''),
                            'grade': record.get('Grade', ''),
                            'arrival_date': datetime.strptime(record['Arrival_Date'], '%d/%m/%Y').strftime('%Y-%m-%d'),
                            'min_price': float(record.get('Min_Price', 0)),
                            'max_price': float(record.get('Max_Price', 0)),
                            'modal_price': float(record.get('Modal_Price', 0)),
                            'min_price_per_kg': float(record.get('Min_Price', 0)) / 100.0,
                            'max_price_per_kg': float(record.get('Max_Price', 0)) / 100.0,
                            'modal_price_per_kg': float(record.get('Modal_Price', 0)) / 100.0,
                            'price_per_kg': float(record.get('Modal_Price', 0)) / 100.0,  # Added for consistency
                            'commodity_code': record.get('Commodity_Code', ''),
                            'date': record.get('Arrival_Date', ''),
                            'price_change': 0  # Default value, will be calculated later
                        }
                        transformed_records.append(transformed_record)
                    except (KeyError, ValueError) as e:
                        logger.warning(f"Error transforming record: {str(e)}")
                        continue
                
                data['records'] = transformed_records
                logger.info(f"Successfully fetched {len(transformed_records)} records for date {date}")
                return data
            else:
                logger.warning(f"No records found for date {date}")
                return {'records': [], 'total': 0}

        except requests.exceptions.RequestException as e:
            logger.error(f"Data fetch error: {str(e)}")
            return {'records': [], 'total': 0, 'error': str(e)}
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {'records': [], 'total': 0, 'error': str(e)}

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password:
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        
        flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('register'))
            
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return redirect(url_for('register'))
        
        new_user = User(username=username, password=password, email=email)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        api = MarketAPI()
        data = api.fetch_market_data(state='Tamil Nadu', district='Salem')
        
        dashboard_data = []
        if data and 'records' in data:
            # Calculate price changes
            commodities = {}
            for record in data['records']:
                commodity = record['commodity']
                if commodity not in commodities:
                    commodities[commodity] = []
                commodities[commodity].append(record)
            
            # Sort by date and calculate price changes
            for commodity, records in commodities.items():
                sorted_records = sorted(records, key=lambda x: x['arrival_date'])
                
                for i, record in enumerate(sorted_records):
                    price_change = 0
                    if i > 0:
                        prev_price = sorted_records[i-1]['price_per_kg']
                        curr_price = record['price_per_kg']
                        if prev_price > 0:
                            price_change = ((curr_price - prev_price) / prev_price) * 100
                    
                    dashboard_data.append({
                        'commodity': record['commodity'],
                        'market': record['market'],
                        'price_per_kg': record['price_per_kg'],
                        'price_change': round(price_change, 2),
                        'date': record['date']
                    })
        
        # Calculate statistics
        stats = {
            'total_records': len(dashboard_data),
            'avg_price': sum(d['price_per_kg'] for d in dashboard_data) / len(dashboard_data) if dashboard_data else 0,
            'max_price': max((d['price_per_kg'] for d in dashboard_data), default=0),
            'min_price': min((d['price_per_kg'] for d in dashboard_data), default=0),
            'commodities_count': len(set(d['commodity'] for d in dashboard_data))
        }
        
        logger.info(f"Dashboard data: {len(dashboard_data)} records, {stats['commodities_count']} commodities")
        
    except Exception as e:
        logger.error(f"Error in dashboard: {str(e)}")
        dashboard_data = []
        stats = {
            'total_records': 0,
            'avg_price': 0,
            'max_price': 0,
            'min_price': 0,
            'commodities_count': 0
        }
    
    return render_template('dashboard.html',
                         market_data=dashboard_data,
                         stats=stats,
                         current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/market-analysis')
@login_required
def market_analysis():
    try:
        api = MarketAPI()
        data = api.fetch_market_data(state='Tamil Nadu', district='Salem')
        
        commodity_stats = []
        markets = set()
        
        if data and 'records' in data:
            commodities = {}
            
            for record in data['records']:
                commodity = record['commodity']
                price = record['price_per_kg']
                market = record['market']
                
                if commodity not in commodities:
                    commodities[commodity] = {
                        'prices': [],
                        'markets': set()
                    }
                
                commodities[commodity]['prices'].append(price)
                commodities[commodity]['markets'].add(market)
                markets.add(market)
            
            for commodity, data in commodities.items():
                prices = data['prices']
                commodity_stats.append({
                    'name': commodity,
                    'avg_price': sum(prices) / len(prices) if prices else 0,
                    'max_price': max(prices) if prices else 0,
                    'min_price': min(prices) if prices else 0,
                    'market_count': len(data['markets']),
                    'price_trend': prices
                })
        
        total_markets = len(markets)
        logger.info(f"Market analysis: {len(commodity_stats)} commodities, {total_markets} markets")
        
    except Exception as e:
        logger.error(f"Error in market analysis: {str(e)}")
        commodity_stats = []
        total_markets = 0
    
    return render_template('market_analysis.html', 
                         commodity_stats=commodity_stats,
                         total_markets=total_markets)

@app.route('/price-trends')
@login_required
def price_trends():
    try:
        api = MarketAPI()
        data = api.fetch_market_data(state='Tamil Nadu', district='Salem')
        
        trends = {}
        if data and 'records' in data:
            for record in data['records']:
                commodity = record['commodity']
                if commodity not in trends:
                    trends[commodity] = []
                
                trends[commodity].append({
                    'date': record['date'],
                    'price': record['price_per_kg'],
                    'market': record['market']
                })
        
        # Sort each commodity's data by date
        for commodity in trends:
            trends[commodity].sort(key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y'))
        
        commodities = list(trends.keys())
        logger.info(f"Price trends: {len(commodities)} commodities")
        
    except Exception as e:
        logger.error(f"Error in price trends: {str(e)}")
        trends = {}
        commodities = []
    
    return render_template('price_trends.html', 
                         trends=trends,
                         commodities=commodities)

@app.route('/reports')
@login_required
def reports():
    try:
        report_type = request.args.get('type', 'daily')
        api = MarketAPI()
        data = api.fetch_market_data(state='Tamil Nadu', district='Salem')
        
        reports = []
        if data and 'records' in data:
            for record in data['records']:
                reports.append({
                    'date': record['date'],
                    'commodity': record['commodity'],
                    'market': record['market'],
                    'price': record['price_per_kg']
                })
        
        logger.info(f"Reports: {len(reports)} records, type: {report_type}")
        
    except Exception as e:
        logger.error(f"Error in reports: {str(e)}")
        reports = []
    
    return render_template('reports.html', 
                         reports=reports,
                         current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/api/market-data')
def get_market_data():
    """Get market data with optional filters"""
    try:
        # Get query parameters
        state = request.args.get('state', 'Tamil Nadu')
        district = request.args.get('district', 'Salem')
        date = request.args.get('date')
        commodity = request.args.get('commodity')
        
        # Fetch data
        api = MarketAPI()
        data = api.fetch_market_data(state, district, date, commodity)
        
        return jsonify(data)
    
    except Exception as e:
        logger.error(f"Error fetching market data: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/api/commodities')
def get_commodities():
    """Get list of unique commodities from current market data"""
    try:
        # Fetch market data
        api = MarketAPI()
        data = api.fetch_market_data()
        
        # Extract unique commodities
        commodities = []
        seen = set()
        for record in data.get('records', []):
            if record['commodity'] not in seen:
                seen.add(record['commodity'])
                commodities.append({
                    "id": record['commodity_code'],
                    "name": record['commodity'],
                    "variety": record['variety']
                })
        
        return jsonify(commodities)
    
    except Exception as e:
        logger.error(f"Error fetching commodities: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/api/markets')
def get_markets():
    """Get list of unique markets from current market data"""
    try:
        # Fetch market data
        api = MarketAPI()
        data = api.fetch_market_data()
        
        # Extract unique markets
        markets = []
        seen = set()
        for record in data.get('records', []):
            market_key = f"{record['market']}_{record['district']}_{record['state']}"
            if market_key not in seen:
                seen.add(market_key)
                markets.append({
                    "id": f"MKT{len(seen):03d}",
                    "name": record['market'],
                    "district": record['district'],
                    "state": record['state']
                })
        
        return jsonify(markets)
    
    except Exception as e:
        logger.error(f"Error fetching markets: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/api/market-stats')
def get_market_stats():
    """Get market statistics summary"""
    try:
        # Fetch market data
        api = MarketAPI()
        data = api.fetch_market_data()
        records = data.get('records', [])
        
        if not records:
            return jsonify({
                "total_records": 0,
                "commodities": 0,
                "markets": 0,
                "states": 0,
                "avg_price": 0,
                "min_price": 0,
                "max_price": 0
            })
        
        # Calculate statistics
        commodities = set(record['commodity'] for record in records)
        markets = set(record['market'] for record in records)
        states = set(record['state'] for record in records)
        
        prices = [record['price_per_kg'] for record in records]
        avg_price = sum(prices) / len(prices) if prices else 0
        min_price = min(prices) if prices else 0
        max_price = max(prices) if prices else 0
        
        return jsonify({
            "total_records": len(records),
            "commodities": len(commodities),
            "markets": len(markets),
            "states": len(states),
            "avg_price": round(avg_price, 2),
            "min_price": round(min_price, 2),
            "max_price": round(max_price, 2),
            "last_updated": datetime.now().isoformat()
        })
    
    except Exception as e:
        logger.error(f"Error generating market statistics: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/add-market-data', methods=['GET', 'POST'])
@login_required
def add_market_data():
    if request.method == 'POST':
        try:
            new_data = MarketData(
                state='Tamil Nadu',
                district='Salem',
                market=request.form['market'],
                commodity=request.form['commodity'],
                price=float(request.form['price']),
                date=datetime.now().strftime('%d/%m/%Y')
            )
            db.session.add(new_data)
            db.session.commit()
            flash('Market data added successfully!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Error adding market data: {str(e)}', 'error')
    
    return render_template('add_market_data.html')

@app.route('/edit-market-data/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_market_data(id):
    data = MarketData.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            data.market = request.form['market']
            data.commodity = request.form['commodity']
            data.price = float(request.form['price'])
            db.session.commit()
            flash('Market data updated successfully!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Error updating market data: {str(e)}', 'error')
    
    return render_template('edit_market_data.html', data=data)

@app.route('/delete-market-data/<int:id>')
@login_required
def delete_market_data(id):
    try:
        data = MarketData.query.get_or_404(id)
        db.session.delete(data)
        db.session.commit()
        flash('Market data deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting market data: {str(e)}', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/api/health')
def health_check():
    """API health check endpoint"""
    return jsonify({
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Market Price Discovery on port {port}")
    app.run(debug=True, host="0.0.0.0", port=port)
