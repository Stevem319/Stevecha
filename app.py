import requests
import time
import json
import random
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import re

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='flight_scraper.log'
)
logger = logging.getLogger('flight_scraper')

app = Flask(__name__)

# Configuration
GOOGLE_FLIGHTS_BASE_URL = "https://www.google.com/travel/flights"
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15'
]

# Rate limiting settings
MIN_WAIT_TIME = 5  # Minimum seconds between requests
MAX_WAIT_TIME = 10  # Maximum seconds between requests
MAX_REQUESTS_PER_HOUR = 20  # Maximum number of requests per hour

# Store request timestamps for rate limiting
request_timestamps = []

def enforce_rate_limit():
    """Enforce rate limits to be respectful"""
    global request_timestamps
    
    # Clean up old timestamps
    current_time = time.time()
    request_timestamps = [ts for ts in request_timestamps if current_time - ts < 3600]
    
    # Check if we're exceeding our hourly limit
    if len(request_timestamps) >= MAX_REQUESTS_PER_HOUR:
        sleep_time = 3600 - (current_time - request_timestamps[0]) + 1
        logger.warning(f"Rate limit reached. Sleeping for {sleep_time:.2f} seconds")
        time.sleep(sleep_time)
    
    # Add random delay between requests
    sleep_duration = random.uniform(MIN_WAIT_TIME, MAX_WAIT_TIME)
    logger.info(f"Rate limiting: sleeping for {sleep_duration:.2f} seconds")
    time.sleep(sleep_duration)
    
    # Add current timestamp to the list
    request_timestamps.append(time.time())

def get_headers():
    """Generate request headers with random user agent"""
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
    }

def build_search_url(origin, destination, date, return_date=None, adults=1):
    """Build the Google Flights search URL"""
    base_url = f"{GOOGLE_FLIGHTS_BASE_URL}/search?"
    params = []
    
    # Add required parameters
    params.append(f"hl=en")  # Language (English)
    params.append(f"tfs=CAEQARoKEggSBAj-ARABGAEaaRIHCgNBTlkSAhIBGhIKCC9tLzBsNHdrEghMYSBHdWFyZBIHCgNBTlkSAhIBGhIKCAIEEgYI_gEQAhoGCgQQAhAAIhIKCC9tLzBsNHdrEghMYSBHdWFyZCoSCggCBBIGCP4BEAIaBggEEAIQAA")
    
    # Add origin and destination
    params.append(f"q=Flights%20from%20{quote_plus(origin)}%20to%20{quote_plus(destination)}")
    
    # Add departure date
    if isinstance(date, datetime):
        date_str = date.strftime("%Y-%m-%d")
    else:
        date_str = date
    params.append(f"d={date_str}")
    
    # Add return date if round trip
    if return_date:
        if isinstance(return_date, datetime):
            return_date_str = return_date.strftime("%Y-%m-%d")
        else:
            return_date_str = return_date
        params.append(f"r={return_date_str}")
    
    # Add number of passengers
    params.append(f"p={adults}")
    
    # Join all parameters
    url = base_url + "&".join(params)
    logger.info(f"Built URL: {url}")
    return url

def extract_flight_data(html_content):
    """
    Extract flight information from the HTML content
    Return a structured list of flight options
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    flights = []
    
    # Find flight containers
    flight_containers = soup.select('div[role="listitem"]')
    
    for container in flight_containers:
        try:
            # Extract price
            price_element = container.select_one('div[aria-label*="$"]')
            price = None
            if price_element:
                price_text = price_element.get('aria-label', '')
                price_match = re.search(r'\$\d+(?:,\d+)?', price_text)
                if price_match:
                    price = price_match.group(0)
            
            # Extract airline
            airline_element = container.select_one('div[aria-label*="airline"]')
            airline = airline_element.text if airline_element else None
            
            # Extract departure and arrival times
            time_elements = container.select('div[aria-label*="Departs"] span, div[aria-label*="Arrives"] span')
            departure_time = time_elements[0].text if len(time_elements) > 0 else None
            arrival_time = time_elements[1].text if len(time_elements) > 1 else None
            
            # Extract duration
            duration_element = container.select_one('div[aria-label*="Duration"]')
            duration = duration_element.text if duration_element else None
            
            # Extract stops
            stops_element = container.select_one('div[aria-label*="stop"]')
            stops = stops_element.text if stops_element else "Nonstop"
            
            flight_data = {
                "airline": airline,
                "departure_time": departure_time,
                "arrival_time": arrival_time,
                "duration": duration,
                "stops": stops,
                "price": price
            }
            
            flights.append(flight_data)
        except Exception as e:
            logger.error(f"Error extracting flight data: {str(e)}")
            continue
    
    return flights

def scrape_flights(origin, destination, date, return_date=None, adults=1):
    """
    Scrape flight information from Google Flights
    """
    logger.info(f"Scraping flights from {origin} to {destination} on {date}")
    
    # Respect robots.txt and rate limiting
    enforce_rate_limit()
    
    # Build the search URL
    url = build_search_url(origin, destination, date, return_date, adults)
    
    try:
        # Make the request
        headers = get_headers()
        response = requests.get(url, headers=headers, timeout=30)
        
        # Check if request was successful
        if response.status_code != 200:
            logger.error(f"Failed to fetch data: Status code {response.status_code}")
            return {"error": f"Failed to fetch data: Status code {response.status_code}"}
        
        # Parse the HTML and extract flight data
        flights = extract_flight_data(response.text)
        
        return {
            "origin": origin,
            "destination": destination,
            "date": date,
            "return_date": return_date,
            "flights": flights,
            "timestamp": datetime.now().isoformat(),
            "results_count": len(flights)
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return {"error": f"Request error: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {"error": f"Unexpected error: {str(e)}"}

@app.route('/api/search', methods=['GET'])
def search_flights():
    """API endpoint to search for flights"""
    try:
        # Get parameters from request
        origin = request.args.get('origin')
        destination = request.args.get('destination')
        date = request.args.get('date')
        return_date = request.args.get('return_date')
        adults = int(request.args.get('adults', 1))
        
        # Validate required parameters
        if not all([origin, destination, date]):
            return jsonify({"error": "Missing required parameters"}), 400
        
        # Scrape flights
        result = scrape_flights(origin, destination, date, return_date, adults)
        
        if "error" in result:
            return jsonify(result), 500
            
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """API endpoint for health checks"""
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    # Run the Flask app
    app.run(host='0.0.0.0', port=5000)