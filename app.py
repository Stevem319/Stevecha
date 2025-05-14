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
from flask_cors import CORS # <--- Added this import

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='flight_scraper.log'
)
logger = logging.getLogger('flight_scraper')

app = Flask(__name__)
CORS(app) # <--- Initialized CORS here

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
    # It's generally not a good idea to hardcode complex query parameters like 'tfs'
    # as they can change. Google Flights URLs are complex.
    # This might be a source of issues if Google changes their URL structure.
    # For this example, I'm keeping what you had.
    params.append(f"tfs=CAEQARoKEggSBAj-ARABGAEaaRIHCgNBTlkSAhIBGhIKCC9tLzBsNHdrEghMYSBHdWFyZBIHCgNBTlkSAhIBGhIKCAIEEgYI_gEQAhoGCgQQAhAAIhIKCC9tLzBsNHdrEghMYSBHdWFyZCoSCggCBBIGCP4BEAIaBggEEAIQAA")
    
    # Add origin and destination
    # A more robust way to structure the query part might be needed if q=... is not working.
    # Google Flights uses a specific path structure like /flights/search;sel=LAXNYC02024-01-01*NYCLAX02024-01-08
    # For simplicity, I'm keeping your current structure for now.
    params.append(f"q=Flights%20from%20{quote_plus(origin)}%20to%20{quote_plus(destination)}")
    
    # Add departure date
    if isinstance(date, datetime):
        date_str = date.strftime("%Y-%m-%d")
    else:
        date_str = date
    # params.append(f"d={date_str}") # This 'd' parameter might not be what Google Flights expects for the date.
                                    # Often it's part of the path or a more complex parameter.

    # For constructing the query string, it might be better to create a list of tuples
    # and then use urllib.parse.urlencode, but Google Flights URLs are very specific.
    # The actual parameters for date, origin, dest for the /search endpoint are typically embedded in a more complex way
    # like /travel/flights/search?tfs=... where 'tfs' contains encoded flight info.
    # The 'q' parameter is more for general search.
    # The URL you're building might not yield direct flight listings suitable for scraping easily.

    # The example URL structure is more like:
    # /travel/flights/search?hl=en&q=flights+from+JFK+to+LAX+on+2024-12-25
    # Or using the complex 'tfs' parameter if you have it.
    # For a one-way trip, it might be:
    # .../flights/JFK-LAX.2024-12-25.{P}*LAX-JFK.{P} (P is passenger count)
    # The date format in the path is YYYY-MM-DD.
    # Your current `build_search_url` is likely not forming the correct URL structure that Google Flights uses
    # for its queryable search results page, especially for scraping.

    # For simplicity, let's assume your previous URL structure was working for your scraping target.
    # If not, this URL construction is a key area to revisit.
    # To make it more like the 'q' parameter example for general search:
    query_string = f"flights from {origin} to {destination} on {date_str}"
    if adults > 1:
        query_string += f" for {adults} adults"
    if return_date:
        if isinstance(return_date, datetime):
            return_date_str = return_date.strftime("%Y-%m-%d")
        else:
            return_date_str = return_date
        query_string += f" returning on {return_date_str}"

    # Clear previous params and rebuild for the 'q' style
    params = [f"hl=en", f"q={quote_plus(query_string)}"]
    # The 'tfs' parameter you had is very specific and might lock searches to specific pre-defined routes.
    # If you want dynamic search, using only 'q' might be better, or you need to construct 'tfs' dynamically.

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
    
    # This selector 'div[role="listitem"]' might be too generic or might change.
    # Robust scraping requires careful inspection of the Google Flights HTML structure,
    # which is complex and subject to change.
    # The selectors below are examples and might need adjustment.
    # Google Flights often uses dynamically generated class names.
    flight_containers = soup.select('div[role="listitem"]') # This is a very common pattern, but might not be specific enough
    
    # Alternative: Look for a more specific container for flight results.
    # You might need to inspect the page structure on Google Flights to find reliable selectors.
    # For example, Google Flights uses complex, often obfuscated, class names.
    # You might need to find elements by data attributes or more stable structural patterns.

    if not flight_containers:
        logger.info("No primary flight containers found with 'div[role=\"listitem\"]'. Trying common alternative patterns.")
        # Try looking for common flight card patterns - these are illustrative and WILL LIKELY NEED UPDATING
        # based on actual Google Flights HTML structure.
        # Example: flight_containers = soup.select('.xyz123abc') # if you find a stable class
        # Example: flight_containers = soup.find_all('li', class_=lambda x: x and 'result-item' in x)

    logger.info(f"Found {len(flight_containers)} potential flight containers.")

    for container_index, container in enumerate(flight_containers):
        try:
            # Extract price
            # Price is often within a span or div with a specific structure or data attribute.
            # The 'aria-label*="$"' selector is a good attempt.
            price_element = container.select_one('div[aria-label*="$"], span[aria-label*="$"]') # Check spans too
            price = None
            if price_element:
                price_text = price_element.get('aria-label', '') or price_element.text
                price_match = re.search(r'\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', price_text) # More robust regex
                if price_match:
                    price = f"${price_match.group(1)}" # Store with $
            
            # Extract airline
            # Airline name might be in an img alt text or a div with a specific class
            airline_element = container.select_one('div[class*="airline"], span[class*="airline"], div[aria-label*="airline"], span[aria-label*="airline"]')
            airline = None
            if airline_element:
                airline = airline_element.text.strip()
                # Often, the airline is part of a larger string, e.g., "Delta, operated by SkyWest"
                # You might want to clean this up.
                if not airline: # Check alt text of an image if text is empty
                    img_logo = container.select_one('img[alt*="logo"]')
                    if img_logo and "airline" in img_logo.get("alt", "").lower():
                         airline = img_logo.get("alt").replace("logo", "").strip()


            # Extract departure and arrival times
            # Times are tricky. Google uses specific formats and sometimes relative times.
            # `div[aria-label*="Departs"] span` is a good start.
            # Need to find distinct departure and arrival blocks.
            time_elements = container.select('div[jscontroller] div[role="text"] > span:not([class])') # Example selector, very likely to change
            
            departure_time = None
            arrival_time = None

            # This part needs very careful selector crafting based on live Google Flights HTML
            # The following is a placeholder for likely structure
            segments = container.select('div.segment-class-placeholder') # Replace with actual segment class
            if segments:
                # This logic assumes a simple one-segment flight for simplicity.
                # Real multi-segment flights will require iterating through segments.
                
                # Departure time (often the first time-like string in the segment)
                dep_time_el = segments[0].select_one('span.departure-time-class') # Replace with actual
                if dep_time_el: departure_time = dep_time_el.text.strip()

                # Arrival time (often the second time-like string in the segment)
                arr_time_el = segments[0].select_one('span.arrival-time-class') # Replace with actual
                if arr_time_el: arrival_time = arr_time_el.text.strip()

            # Fallback if the above specific selectors don't work
            if not departure_time or not arrival_time:
                all_spans_in_container = container.find_all('span')
                possible_times = []
                for span in all_spans_in_container:
                    # Regex for time format like "10:00 AM" or "10:00"
                    if re.match(r'\d{1,2}:\d{2}(\s*(?:AM|PM))?', span.text.strip()):
                        possible_times.append(span.text.strip())
                if len(possible_times) >= 2:
                    departure_time = possible_times[0]
                    arrival_time = possible_times[1] # This is a guess, order matters.


            # Extract duration
            duration_element = container.select_one('div[aria-label*="Duration"], span[aria-label*="Duration"]')
            duration = None
            if duration_element:
                duration = duration_element.text.strip()
            else: # Fallback if aria-label not found
                # Duration is often like "Xh Ym"
                all_text_nodes = container.find_all(string=True)
                for text_node in all_text_nodes:
                    if re.search(r'\d+h(\s+\d+m)?', text_node.strip()):
                        duration = text_node.strip()
                        break
            
            # Extract stops
            stops_element = container.select_one('div[aria-label*="stop"], span[aria-label*="stop"]')
            stops = "Nonstop" # Default
            if stops_element:
                stops_text = stops_element.text.strip().lower()
                if "nonstop" in stops_text:
                    stops = "Nonstop"
                elif "1 stop" in stops_text:
                    stops = "1 stop"
                elif re.search(r'\d+\s+stops', stops_text):
                    stops = re.search(r'(\d+\s+stops)', stops_text).group(1)
            else: # Fallback
                all_text_nodes_stops = container.find_all(string=True)
                for text_node in all_text_nodes_stops:
                    text_content = text_node.strip().lower()
                    if "nonstop" in text_content:
                        stops = "Nonstop"
                        break
                    if "stop" in text_content and re.search(r'\d+', text_content):
                        stops = text_node.strip() # e.g., "1 stop over JFK"
                        break
            
            # Only add if essential data is found (e.g., price and times)
            if price and airline and departure_time and arrival_time and duration:
                flight_data = {
                    "airline": airline,
                    "departure_time": departure_time,
                    "arrival_time": arrival_time,
                    "duration": duration,
                    "stops": stops,
                    "price": price
                }
                flights.append(flight_data)
                logger.info(f"Extracted flight: {flight_data}")
            else:
                logger.warning(f"Could not extract all essential data for a flight entry in container {container_index}. Price: {price}, Airline: {airline}, Dep: {departure_time}, Arr: {arrival_time}, Dur: {duration}")

        except Exception as e:
            logger.error(f"Error extracting data for one flight entry: {str(e)} from container: {container.prettify()[:500]}") # Log part of container for debug
            continue
    
    if not flights:
        logger.warning(f"No flights extracted. HTML content might have changed or selectors are no longer valid. Soup text length: {len(soup.text)}")
    return flights

def scrape_flights(origin, destination, date, return_date=None, adults=1):
    """
    Scrape flight information from Google Flights
    """
    logger.info(f"Scraping flights from {origin} to {destination} on {date} for {adults} adult(s)")
    
    # Respect robots.txt and rate limiting - Google is very sensitive to scraping.
    enforce_rate_limit()
    
    # Build the search URL
    url = build_search_url(origin, destination, date, return_date, adults)
    
    try:
        # Make the request
        headers = get_headers()
        logger.info(f"Requesting URL: {url} with headers: {headers}")
        response = requests.get(url, headers=headers, timeout=30) # Increased timeout
        
        # Check if request was successful
        if response.status_code != 200:
            logger.error(f"Failed to fetch data: Status code {response.status_code} for URL {url}. Response text: {response.text[:500]}")
            # It might be useful to save response.text to a file for debugging if scraping fails
            # with open(f"error_page_{response.status_code}.html", "w", encoding="utf-8") as f:
            #    f.write(response.text)
            return {"error": f"Failed to fetch data from Google Flights: Status code {response.status_code}. The page structure may have changed or access was blocked."}
        
        # Save HTML for inspection if needed, especially during development
        # with open(f"flights_page_{origin}_{destination}_{date}.html", "w", encoding="utf-8") as f:
        #    f.write(response.text)
        # logger.info(f"Saved HTML content to flights_page_{origin}_{destination}_{date}.html")

        # Parse the HTML and extract flight data
        flights = extract_flight_data(response.text)
        
        logger.info(f"Found {len(flights)} flights after parsing.")
        return {
            "origin": origin,
            "destination": destination,
            "date": date,
            "return_date": return_date, # Ensure this is passed through
            "flights": flights,
            "timestamp": datetime.now().isoformat(),
            "results_count": len(flights)
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return {"error": f"Request error: {str(e)}"}
    except Exception as e:
        logger.exception(f"Unexpected error during scraping process") # Use logger.exception to include stack trace
        return {"error": f"An unexpected error occurred: {str(e)}"}

@app.route('/api/search', methods=['GET'])
def search_flights_api(): # Renamed to avoid conflict with function name
    """API endpoint to search for flights"""
    try:
        # Get parameters from request
        origin = request.args.get('origin')
        destination = request.args.get('destination')
        date = request.args.get('date') # Expected format YYYY-MM-DD
        return_date = request.args.get('return_date') # Optional, YYYY-MM-DD
        adults_str = request.args.get('adults', '1')
        
        # Validate required parameters
        if not all([origin, destination, date]):
            logger.warning("Missing required parameters in API request")
            return jsonify({"error": "Missing required parameters: origin, destination, and date are required."}), 400
        
        try:
            adults = int(adults_str)
            if adults < 1:
                raise ValueError("Number of adults must be at least 1.")
        except ValueError:
            logger.warning(f"Invalid number of adults: {adults_str}")
            return jsonify({"error": "Invalid number of adults. Must be a positive integer."}), 400

        # Log incoming request
        logger.info(f"Received API request: origin={origin}, destination={destination}, date={date}, return_date={return_date}, adults={adults}")
        
        # Scrape flights
        result = scrape_flights(origin, destination, date, return_date, adults)
        
        if "error" in result:
            logger.error(f"Scraping returned an error: {result['error']}")
            return jsonify(result), 500 # Keep 500 for server-side errors from scraping
            
        logger.info(f"Successfully returned {result.get('results_count', 0)} flights for query.")
        return jsonify(result)
        
    except Exception as e:
        logger.exception("Unhandled API error") # Use logger.exception for full stack trace
        return jsonify({"error": f"An internal server error occurred: {str(e)}"}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """API endpoint for health checks"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# Add a simple test endpoint
@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """Simple test endpoint to verify connectivity"""
    return jsonify({
        "status": "connected",
        "message": "Successfully connected to Flight Scraper API",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == "__main__":
    # Install requirements first:
    # pip install flask flask-cors requests beautifulsoup4 gunicorn
    
    # Run the Flask app (Gunicorn is typically used for production, not with app.run directly)
    # For local development:
    app.run(host='0.0.0.0', port=5000, debug=True)
    # For Render.com, your Procfile would typically use gunicorn, e.g.:
    # web: gunicorn your_script_name:app
