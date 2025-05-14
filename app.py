import requests
import time
import json
import random
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urlencode
import re
from flask_cors import CORS

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    # Consider logging to stdout/stderr for Render.com to pick up logs easily
    # filename='flight_scraper.log' 
    handlers=[logging.StreamHandler()] 
)
logger = logging.getLogger('flight_scraper')

app = Flask(__name__)
CORS(app)

# Configuration
GOOGLE_FLIGHTS_BASE_URL = "https://www.google.com/travel/flights" # Ensure this is the correct base
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
]

# Rate limiting settings
MIN_WAIT_TIME = 7  # Increased slightly
MAX_WAIT_TIME = 15 # Increased slightly
MAX_REQUESTS_PER_HOUR = 15 # Reduced slightly to be more cautious

request_timestamps = []

def enforce_rate_limit():
    global request_timestamps
    current_time = time.time()
    request_timestamps = [ts for ts in request_timestamps if current_time - ts < 3600]
    
    if len(request_timestamps) >= MAX_REQUESTS_PER_HOUR:
        sleep_time = 3600 - (current_time - request_timestamps[0]) + random.uniform(1, 60) # Add jitter
        logger.warning(f"Hourly rate limit reached ({MAX_REQUESTS_PER_HOUR}/hr). Sleeping for {sleep_time:.2f} seconds.")
        time.sleep(sleep_time)
        request_timestamps = [ts for ts in request_timestamps if time.time() - ts < 3600] # Re-check after sleep
    
    sleep_duration = random.uniform(MIN_WAIT_TIME, MAX_WAIT_TIME)
    logger.info(f"Rate limiting: sleeping for {sleep_duration:.2f} seconds before request.")
    time.sleep(sleep_duration)
    request_timestamps.append(time.time())

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'DNT': '1', # Do Not Track
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none', # Was 'same-origin' if directly navigating on Google, 'none' for initial
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'no-cache', # Be explicit about not wanting cached results
        'Pragma': 'no-cache'
    }

def build_search_url(origin, destination, date_str, return_date_str=None, adults=1):
    """
    Build the Google Flights search URL.
    WARNING: Google Flights URL parameters are complex and change frequently.
    This function attempts a common structure but may need significant adjustments.
    The 'tfs' parameter is typically the most reliable if you can construct it,
    but it's heavily encoded. A query-based URL is a fallback.
    """
    # Example of path-based structure (often more stable for direct searches if known)
    # /travel/flights/search?tfs=CVFoZWJoWkRjMDFuUkZWR1JFNURSMG94YWkxaGJrSkZURXhVTVZSRGNHbDNSVkJCUjJ4SFJWRkNUMHd0TmpCVU1GUXhRemRvYVc1NU1EMXhabWcxTm1zeE5YQmZSMDR0TUMwdExURTFNQVV5TWpkZk5qZ3ZSazVETURVNU1URXhHZ1pXV2pVek1UTXlNRGJDTWpNeU1URXVNelF1YXpVemFXSnNhVzVtYjNOckNnb0VCREk2TFMwS1IwSkxaRVJqT3JNQk1SOHhEUDR0TUMwdExURTFNQVV5TWpkZk5qZ3ZSazVETURVNU1URXhHZ3JDQ2dzSXdqRXRCQlJYSVZNdWNHbDNSVkJDVTNReE5qbENUMHd0TmpCVU1GUXhRemRvYVc1NU1EQjFhVzA1TWpzeE5YQmZSMDR0TUMwdExURTFNQVV5TWpkZk5qZ3ZSazVETURVNU1URXhLSFVGUlZNaUNnWXhPU0JpYkcxSlBReGdSVk1pQ2dZeE9TQmlla05GUFFrPQ
    
    # Using query parameters:
    # This will likely take you to a search results page that then might do its own internal fetches.
    # It's less direct than knowing the deep-link structure.
    params = {
        'hl': 'en',
        # The 'q' parameter is for general, human-readable search queries.
        # For structured data, this is less reliable than specific flight parameters.
        'q': f"flights from {origin} to {destination} on {date_str}"
    }
    if adults > 1:
      params['q'] += f" for {adults} adults"

    # For one-way, only departure date is needed in 'q'
    # For round-trip, Google often uses a different structure or encodes both dates.
    # If your `return_date_str` is provided, you might append "returning {return_date_str}" to q,
    # or use specific date parameters if you discover them.
    if return_date_str:
        params['q'] += f" returning {return_date_str}"
        # Google might also use separate date fields in some URL formats e.g., d1=YYYY-MM-DD&d2=YYYY-MM-DD

    # The 'tfs' parameter you had before is extremely specific and usually generated by Google's UI.
    # Replicating it dynamically is very hard.
    # params['tfs'] = "CAEQARoKEggSBAj-ARABGAEaaRIHCgNBTlkSAhIBGhIKCC9tLzBsNHdrEghMYSBHdWFyZBIHCgNBTlkSAhIBGhIKCAIEEgYI_gEQAhoGCgQQAhAAIhIKCC9tLzBsNHdrEghMYSBHdWFyZCoSCggCBBIGCP4BEAIaBggEEAIQAA"

    # Constructing the URL
    # Google Flights uses a path often like /travel/flights/search or just /flights
    # For example: https://www.google.com/flights/search?hl=en&q=flights+from+JFK+to+LAX+on+2024-12-01
    url = f"{GOOGLE_FLIGHTS_BASE_URL}/search?{urlencode(params)}"
    logger.info(f"Built Google Flights Search URL: {url}")
    return url

def extract_flight_data(html_content, origin, destination, date_str):
    """
    Extract flight information from the HTML content.
    WARNING: These selectors are EXAMPLES and are VERY LIKELY TO BREAK.
    You MUST inspect the live Google Flights HTML and update them frequently.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    flights = []
    
    # --- SELECTOR WARNING ---
    # The following selectors are common patterns but are NOT guaranteed to work.
    # Google Flights' HTML is dynamic and changes. Use your browser's DevTools to find current selectors.
    # Look for stable attributes like 'data-*', 'aria-label', or structural patterns.
    # Avoid relying on highly dynamic or obfuscated CSS class names like 'xyz123'.

    # Attempt to find main flight result list items.
    # Common patterns: 'div[role="listitem"]', or specific classes Google might use for flight cards.
    # Sometimes results are in <ul> with <li> elements.
    flight_containers = soup.select('div[jscontroller][role="listitem"], li[data-flight-id]') # Example, try to find unique attributes
    
    if not flight_containers:
        logger.warning(f"No flight containers found using primary selectors. HTML structure might have changed. Page content length: {len(html_content)}")
        # You could try other, broader selectors here as a fallback, but they might be less precise.
        # e.g., flight_containers = soup.select('.some-flight-card-class') # If you find one

    logger.info(f"Found {len(flight_containers)} potential flight containers.")

    for index, container in enumerate(flight_containers):
        airline, departure_time, arrival_time, duration, stops_str, price_str = None, None, None, None, "Nonstop", None
        try:
            # Airline: Often in an element with class related to airline name or in an aria-label.
            # Or look for an img tag with alt text containing the airline.
            airline_element = container.select_one('div[aria-label*="airline"], span[class*="carrier"], div[class*="airline"]')
            if airline_element:
                airline = airline_element.text.strip()
                if not airline: # Try another common pattern
                    img_alt_airline = container.select_one('img[alt*="airline"], img[aria-label*="airline"]')
                    if img_alt_airline: airline = img_alt_airline.get('alt', '').replace('logo', '').strip()
            if not airline: logger.debug(f"Container {index}: Airline not found.")

            # Times: Look for elements clearly indicating departure and arrival.
            # These are often within spans or divs with specific formatting or aria-labels.
            # Google might use a parent div for departure and another for arrival.
            time_elements = container.select('span[aria-hidden="true"]') # This is a common pattern for visible text
            actual_times = []
            for el in time_elements:
                if re.match(r'^\d{1,2}:\d{2}\s*(?:AM|PM)?$', el.text.strip()):
                    actual_times.append(el.text.strip())
            
            if len(actual_times) >= 2:
                departure_time = actual_times[0]
                arrival_time = actual_times[1] # Assuming order, this might be wrong for multi-leg.
            else: # Fallback based on aria-labels
                dep_el = container.select_one('div[aria-label*="Departs at"], span[aria-label*="Departs at"]')
                if dep_el: departure_time = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', dep_el.get('aria-label','')).group(1) if dep_el.get('aria-label') else dep_el.text.strip()

                arr_el = container.select_one('div[aria-label*="Arrives at"], span[aria-label*="Arrives at"]')
                if arr_el: arrival_time = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)', arr_el.get('aria-label','')).group(1) if arr_el.get('aria-label') else arr_el.text.strip()

            if not departure_time: logger.debug(f"Container {index}: Departure time not found.")
            if not arrival_time: logger.debug(f"Container {index}: Arrival time not found.")


            # Duration: Often explicitly stated.
            duration_element = container.select_one('div[aria-label*="duration"], span[aria-label*="duration"]')
            if duration_element:
                duration_match = re.search(r'(\d+h\s*\d*m?)', duration_element.get('aria-label', '') or duration_element.text)
                if duration_match: duration = duration_match.group(1)
            if not duration: logger.debug(f"Container {index}: Duration not found.")

            # Stops: Look for "Nonstop", "1 stop", "2 stops".
            stops_element = container.select_one('span[aria-label*="stop"], div[aria-label*="stop"], span[class*="stops"]')
            if stops_element:
                stops_text_content = (stops_element.get('aria-label', '') or stops_element.text).lower()
                if "nonstop" in stops_text_content:
                    stops_str = "Nonstop"
                else:
                    stops_match = re.search(r'(\d+)\s*stop(s)?', stops_text_content)
                    if stops_match:
                        stops_str = f"{stops_match.group(1)} stop{'s' if int(stops_match.group(1)) > 1 else ''}"
            if stops_str == "Nonstop" and not stops_element: logger.debug(f"Container {index}: Stops element not found, defaulted to Nonstop.")


            # Price: Often in an element with aria-label containing currency or a specific class.
            price_element = container.select_one('div[aria-label*="$"], span[aria-label*="$"], div[class*="price"]')
            if price_element:
                price_text_content = price_element.get('aria-label', '') or price_element.text
                price_match = re.search(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', price_text_content)
                if price_match:
                    price_str = f"${price_match.group(1)}"
            if not price_str: logger.debug(f"Container {index}: Price not found.")

            if airline and departure_time and arrival_time and duration and price_str:
                flight_data = {
                    "airline": airline,
                    "departure_time": departure_time,
                    "arrival_time": arrival_time,
                    "duration": duration,
                    "stops": stops_str, # Will be parsed by frontend (e.g., "1 stop" to 1)
                    "price": price_str  # Will be parsed by frontend (e.g., "$100" to 100)
                }
                flights.append(flight_data)
                logger.info(f"Successfully extracted flight: Airline: {airline}, Price: {price_str}")
            else:
                logger.warning(f"Container {index}: Missing essential data. Airline: {airline}, Dep: {departure_time}, Arr: {arrival_time}, Dur: {duration}, Price: {price_str}. Skipping.")
                # For debugging, log the container's HTML snippet if data is missing
                # logger.debug(f"Container HTML for missing data (index {index}):\n{container.prettify()[:1000]}\n------------------")

        except Exception as e:
            logger.error(f"Error extracting data for one flight entry (index {index}): {str(e)}", exc_info=True)
            # logger.debug(f"Problematic Container HTML (index {index}):\n{container.prettify()[:1000]}\n------------------")
            continue
    
    if not flights and flight_containers:
        logger.warning(f"Found {len(flight_containers)} containers but extracted 0 flights. Selectors for individual fields likely need update.")
    elif not flights and not flight_containers:
        logger.warning("No flight containers found AND no flights extracted. Check primary container selectors and page content.")

    return flights

def scrape_flights(origin, destination, date_str, return_date_str=None, adults=1):
    logger.info(f"Attempting to scrape flights: {origin} to {destination} on {date_str}, Return: {return_date_str}, Adults: {adults}")
    
    enforce_rate_limit()
    
    url = build_search_url(origin, destination, date_str, return_date_str, adults)
    
    try:
        headers = get_headers()
        logger.info(f"Requesting URL: {url}")
        response = requests.get(url, headers=headers, timeout=20) # timeout
        
        response.raise_for_status() # Will raise an HTTPError if the HTTP request returned an unsuccessful status code

        # For debugging, save the HTML content
        # with open(f"google_flights_response_{origin}_{destination}_{date_str}.html", "w", encoding="utf-8") as f:
        #    f.write(response.text)
        # logger.info("Saved HTML response for debugging.")

        flights = extract_flight_data(response.text, origin, destination, date_str)
        
        logger.info(f"Scraping complete for {origin}-{destination} on {date_str}. Found {len(flights)} flights.")
        return {
            "origin": origin,
            "destination": destination,
            "date": date_str, # This is the DEPARTURE date
            "return_date": return_date_str, # Pass this through as well
            "flights": flights,
            "timestamp": datetime.now().isoformat(),
            "results_count": len(flights)
        }
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error fetching Google Flights page: {e}. Status: {e.response.status_code}. URL: {url}")
        logger.error(f"Response content (first 500 chars): {e.response.text[:500]}")
        return {"error": f"Failed to fetch data from Google Flights (HTTP {e.response.status_code}). Access may be blocked or page structure changed."}
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching Google Flights page: {e}. URL: {url}")
        return {"error": f"Network request error when trying to reach Google Flights: {str(e)}"}
    except Exception as e:
        logger.exception(f"An unexpected error occurred during the scraping process for {url}")
        return {"error": f"An unexpected critical error occurred during scraping: {str(e)}"}

@app.route('/api/search', methods=['GET'])
def search_flights_api():
    origin = request.args.get('origin')
    destination = request.args.get('destination')
    date_str = request.args.get('date') # Expects YYYY-MM-DD from frontend
    return_date_str = request.args.get('return_date') # Optional
    adults_str = request.args.get('adults', '1')

    if not all([origin, destination, date_str]):
        logger.warning("API /api/search: Missing required parameters.")
        return jsonify({"error": "Missing required parameters: origin, destination, and date are required."}), 400
    
    try:
        # Validate date format (simple check)
        datetime.strptime(date_str, '%Y-%m-%d')
        if return_date_str:
            datetime.strptime(return_date_str, '%Y-%m-%d')
    except ValueError:
        logger.warning(f"API /api/search: Invalid date format. Date: {date_str}, Return Date: {return_date_str}")
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

    try:
        adults = int(adults_str)
        if adults < 1:
            raise ValueError("Number of adults must be at least 1.")
    except ValueError:
        logger.warning(f"API /api/search: Invalid number of adults: {adults_str}")
        return jsonify({"error": "Invalid number of adults. Must be a positive integer."}), 400

    logger.info(f"API /api/search request: O={origin}, D={destination}, Date={date_str}, Return={return_date_str}, Adults={adults}")
    
    result = scrape_flights(origin, destination, date_str, return_date_str, adults)
    
    if "error" in result:
        # Error message is already logged by scrape_flights
        return jsonify(result), 500 # Propagate error from scraper
            
    return jsonify(result)

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == "__main__":
    # For local development:
    # Ensure Flask-CORS is installed: pip install Flask-CORS
    app.run(host='0.0.0.0', port=5000, debug=True)
    # For Render.com, your Procfile would use gunicorn, e.g.:
    # web: gunicorn app:app  (if your file is named app.py)
