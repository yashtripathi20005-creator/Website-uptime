from flask import Flask, render_template, request, jsonify
import requests
import json
import time
from datetime import datetime
import threading
import os

app = Flask(__name__)

# Store monitoring data
monitored_sites = {}
monitoring_threads = {}
CHECK_INTERVAL = 60  # seconds

class SiteMonitor:
    def __init__(self, url, name=None):
        self.url = url
        self.name = name if name else url
        self.status_history = []
        self.current_status = {
            'status': 'unknown',
            'response_time': None,
            'last_check': None,
            'uptime_percentage': 100.0
        }
        self.running = False
        self.thread = None
        
    def check_site(self):
        try:
            start_time = time.time()
            response = requests.get(self.url, timeout=10, allow_redirects=True)
            response_time = time.time() - start_time
            
            is_up = response.status_code == 200
            
            status_data = {
                'timestamp': datetime.now().isoformat(),
                'status': 'up' if is_up else 'down',
                'status_code': response.status_code,
                'response_time': round(response_time * 1000, 2),  # in milliseconds
                'url': self.url
            }
            
            self.status_history.append(status_data)
            
            # Keep only last 1000 entries
            if len(self.status_history) > 1000:
                self.status_history = self.status_history[-1000:]
            
            # Update current status
            self.current_status = {
                'status': 'up' if is_up else 'down',
                'response_time': round(response_time * 1000, 2),
                'last_check': status_data['timestamp'],
                'status_code': response.status_code
            }
            
            # Calculate uptime percentage (last 24 hours)
            self.calculate_uptime()
            
            return status_data
            
        except requests.exceptions.Timeout:
            status_data = {
                'timestamp': datetime.now().isoformat(),
                'status': 'down',
                'status_code': 'timeout',
                'response_time': None,
                'url': self.url
            }
            self.status_history.append(status_data)
            self.current_status = {
                'status': 'down',
                'response_time': None,
                'last_check': status_data['timestamp'],
                'status_code': 'timeout'
            }
            self.calculate_uptime()
            return status_data
            
        except requests.exceptions.ConnectionError:
            status_data = {
                'timestamp': datetime.now().isoformat(),
                'status': 'down',
                'status_code': 'connection_error',
                'response_time': None,
                'url': self.url
            }
            self.status_history.append(status_data)
            self.current_status = {
                'status': 'down',
                'response_time': None,
                'last_check': status_data['timestamp'],
                'status_code': 'connection_error'
            }
            self.calculate_uptime()
            return status_data
            
        except Exception as e:
            status_data = {
                'timestamp': datetime.now().isoformat(),
                'status': 'down',
                'status_code': str(e),
                'response_time': None,
                'url': self.url
            }
            self.status_history.append(status_data)
            self.current_status = {
                'status': 'down',
                'response_time': None,
                'last_check': status_data['timestamp'],
                'status_code': str(e)
            }
            self.calculate_uptime()
            return status_data
    
    def calculate_uptime(self):
        """Calculate uptime percentage for the last 24 hours"""
        if not self.status_history:
            self.current_status['uptime_percentage'] = 100.0
            return
        
        # Get last 24 hours of data
        cutoff_time = datetime.now().timestamp() - (24 * 60 * 60)
        recent_checks = []
        
        for check in reversed(self.status_history):
            check_time = datetime.fromisoformat(check['timestamp']).timestamp()
            if check_time >= cutoff_time:
                recent_checks.append(check)
            else:
                break
        
        if not recent_checks:
            self.current_status['uptime_percentage'] = 100.0
            return
        
        up_count = sum(1 for check in recent_checks if check['status'] == 'up')
        total_count = len(recent_checks)
        
        if total_count > 0:
            self.current_status['uptime_percentage'] = round((up_count / total_count) * 100, 2)
        else:
            self.current_status['uptime_percentage'] = 100.0
    
    def monitor_loop(self):
        """Continuously monitor the site"""
        self.running = True
        while self.running:
            self.check_site()
            time.sleep(CHECK_INTERVAL)
    
    def start_monitoring(self):
        """Start the monitoring thread"""
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.monitor_loop, daemon=True)
            self.thread.start()
            return True
        return False
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
            return True
        return False
    
    def get_recent_checks(self, limit=10):
        """Get the most recent checks"""
        return self.status_history[-limit:] if self.status_history else []
    
    def to_dict(self):
        """Convert monitor to dictionary for JSON response"""
        return {
            'name': self.name,
            'url': self.url,
            'status': self.current_status.get('status', 'unknown'),
            'response_time': self.current_status.get('response_time'),
            'last_check': self.current_status.get('last_check'),
            'uptime_percentage': self.current_status.get('uptime_percentage', 100.0),
            'status_code': self.current_status.get('status_code'),
            'recent_checks': self.get_recent_checks(5)
        }


@app.route('/')
def index():
    """Home page"""
    return render_template('index.html', sites=monitored_sites)


@app.route('/add', methods=['POST'])
def add_site():
    """Add a new site to monitor"""
    url = request.form.get('url', '').strip()
    name = request.form.get('name', '').strip()
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    # Add http:// if no protocol specified
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Check if already monitoring
    if url in monitored_sites:
        return jsonify({'error': 'Site is already being monitored'}), 400
    
    # Create and start monitor
    monitor = SiteMonitor(url, name)
    monitor.start_monitoring()
    monitored_sites[url] = monitor
    
    # Do initial check
    monitor.check_site()
    
    return jsonify({
        'message': 'Site added successfully',
        'site': monitor.to_dict()
    })


@app.route('/remove/<path:url>', methods=['DELETE'])
def remove_site(url):
    """Remove a site from monitoring"""
    if url in monitored_sites:
        monitored_sites[url].stop_monitoring()
        del monitored_sites[url]
        return jsonify({'message': 'Site removed successfully'})
    return jsonify({'error': 'Site not found'}), 404


@app.route('/status')
def get_status():
    """Get status of all monitored sites"""
    statuses = {}
    for url, monitor in monitored_sites.items():
        statuses[url] = monitor.to_dict()
    return jsonify(statuses)


@app.route('/status/<path:url>')
def get_site_status(url):
    """Get status of a specific site"""
    if url in monitored_sites:
        return jsonify(monitored_sites[url].to_dict())
    return jsonify({'error': 'Site not found'}), 404


@app.route('/history/<path:url>')
def get_site_history(url):
    """Get full history of a specific site"""
    if url in monitored_sites:
        limit = request.args.get('limit', default=100, type=int)
        history = monitored_sites[url].status_history[-limit:]
        return jsonify(history)
    return jsonify({'error': 'Site not found'}), 404


@app.route('/results')
def results():
    """Display results page"""
    return render_template('results.html', sites=monitored_sites)


if __name__ == '__main__':
    # Create templates folder if it doesn't exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    if not os.path.exists('static'):
        os.makedirs('static')
    
    app.run(debug=True, host='0.0.0.0', port=5000)
