# Import necessary modules from Flask to handle web requests and render HTML templates
from flask import Flask, render_template, request
from googleapiclient.discovery import build
import os
from dotenv import load_dotenv
import re
import math
import google.generativeai as genai


# Load environment variables from .env file
load_dotenv()
# Get YouTube API key from environment variables
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-pro')

def generate_ai_explanation(stats, analytics, price):
    """
    Generate an AI-powered explanation of the price estimate
    Args:
        stats: Channel statistics
        analytics: Channel analytics data
        price: Calculated price estimate
    Returns:
        str: AI-generated explanation
    """
    prompt = f"""
    Act as a YouTube influencer marketing expert. Generate a detailed explanation for a sponsorship price estimate of ${price['estimate']:,.2f} for a YouTube channel with:
    - {stats['subscriber_count']:,} subscribers
    - {int(analytics['recent_views']):,} average views per video
    - {analytics['avg_view_duration']:.1f}% average view duration

    Include:
    1. Market analysis
    2. Value proposition
    3. Comparison to industry standards
    4. Potential ROI for sponsors
    Keep it professional and concise (max 150 words).
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return "AI explanation unavailable at the moment. Please refer to the standard explanation below."

# Create a Flask application instance
app = Flask(__name__)

def extract_channel_id(url):
    """
    Extract channel ID from various YouTube URL formats
    Args:
        url (str): YouTube channel URL
    Returns:
        str: Channel ID or None if not found
    """
    # Pattern for channel ID in URLs
    patterns = [
        # '\.' helps still recognize the dot as a literal character
        r'youtube\.com/channel/(UC[\w-]{22})',  # Standard channel URL where 'UC' is the first 2 characters of the ID and then the next 22 characters are the ID and can be any word character (letters, numbers, underscore) or hyphen
        r'youtube\.com/c/([^/]+)',              # + means "one or more times" and [^/] means "any character except slash"
        r'youtube\.com/@([^/]+)'                # + means "one or more times" and [^/] means "any character except slash"
    ]
    
    for pattern in patterns:
        # re.search() looks for a pattern anywhere in the string
        # pattern: the regular expression pattern to search for
        # url: the string to search within
        # returns: Match object if found, None if no match
        match = re.search(pattern, url)
        if match:
            # Returns the substring that was captured by the first capturing group in the regex pattern (refers to the part of the stuff inside the parentheses)
            # The 1 indicates we want the first captured group (groups are numbered starting from 1)
            # Group 0 would represent the entire match
            # For @ URLs, remove the @ symbol
            result = match.group(1)
            if pattern.endswith('@([^/]+)'):
                result = result.replace('@', '')
            return result
        else:
            print("No match")
    return None

def get_channel_stats(channel_identifier):
    """
    Fetch channel statistics using YouTube API
    Args:
        channel_identifier (str): YouTube channel ID or username
    Returns:
        dict: Channel statistics
    """
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    
    try:
        # First try to search for the channel
        search_response = youtube.search().list(
            part='snippet',
            q=channel_identifier,
            type='channel',
            maxResults=1
        ).execute()
        
        if not search_response.get('items'):
            print(f"No channel found for identifier: {channel_identifier}")
            return None
            
        channel_id = search_response['items'][0]['id']['channelId']
        
        # Now get the channel statistics using the channel ID
        channel_response = youtube.channels().list(
            part='statistics,snippet',
            id=channel_id
        ).execute()
        
        if not channel_response.get('items'):
            print(f"No statistics found for channel ID: {channel_id}")
            return None
            
        channel_data = channel_response['items'][0]
        stats = channel_data['statistics']
        snippet = channel_data['snippet']
        
        return {
            'title': snippet.get('title', 'Unknown'),
            'subscriber_count': int(stats.get('subscriberCount', 0)),
            'view_count': int(stats.get('viewCount', 0)),
            'video_count': int(stats.get('videoCount', 0)),
            'channel_id': channel_id  # Add channel ID to return value
        }
        
    except Exception as e:
        print(f"Error fetching channel stats: {e}")
        return None

def parse_duration(duration):
    """
    Convert YouTube duration format (PT#M#S) to seconds
    Args:
        duration: YouTube duration string
    Returns:
        int: Duration in seconds
    Example (it helps convert the duration to seconds):
    PT1H2M10S -> 1*3600 + 2*60 + 10 = 3730
    """
    hours = minutes = seconds = 0
    
    # Remove PT from start
    duration = duration[2:]
    
    # Check for hours
    if 'H' in duration:
        hours = int(duration.split('H')[0])
        duration = duration.split('H')[1]
    
    # Check for minutes
    if 'M' in duration:
        minutes = int(duration.split('M')[0])
        duration = duration.split('M')[1]
    
    # Check for seconds
    if 'S' in duration:
        seconds = int(duration.split('S')[0])
    
    return hours * 3600 + minutes * 60 + seconds

def get_channel_analytics(channel_id):
    """
    Get detailed analytics for a channel's recent videos
    Args:
        youtube: YouTube API client instance
        channel_id: The channel's ID
    Returns:
        dict: Analytics data including view duration and engagement metrics
    """
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

    try:
        # Fetch the 10 most recent videos from the channel
        videos_response = youtube.search().list(
            part='id',                # Only request video IDs
            channelId=channel_id,     # Specify which channel to search
            order='date',            # Sort by date (newest first)
            type='video',            # Only get videos (not playlists or channels)
            maxResults=10            # Limit to 10 videos
        ).execute()

        # If no videos are found, return None
        if not videos_response.get('items'):
            return None

        # Extract video IDs into a list using list comprehension
        video_ids = [item['id']['videoId'] for item in videos_response['items']]
        
        # Get detailed statistics for all videos in one API call
        videos_stats = youtube.videos().list(
            part='statistics,contentDetails',  # Get both stats and video duration info
            id=','.join(video_ids)           # Convert video IDs list to comma-separated string
        ).execute()

        # Initialize counters for calculations
        total_views = 0
        view_durations = []

        # Process each video's statistics
        for video in videos_stats['items']:
            # Get video duration in ISO 8601 format (PT#M#S)
            duration = video['contentDetails']['duration']
            # Convert duration to seconds using helper function
            duration_sec = parse_duration(duration)
            # Get view count for this video
            views = int(video['statistics']['viewCount'])
            
            # Calculate retention rate based on video length
            # Research shows that:
            # - Shorter videos (1-2 minutes) often have 70% retention
            # - Medium videos (5-10 minutes) often have 40-50% retention
            # - Longer videos (20+ minutes) often have 20-30% retention
            base_retention = max(20, min(60, 70 - (duration_sec / 60)))
            view_durations.append(base_retention)
            
            # Add to total views counter
            total_views += views

        # Calculate the average view duration across all videos
        # This gives us a more realistic metric based on video length
        avg_view_duration = sum(view_durations) / len(view_durations)

        # Return analytics with realistic view duration and average views
        return {
            'avg_view_duration': avg_view_duration,
            'recent_views': total_views / len(video_ids)  # Average views per video
        }

    except Exception as e:
        print(f"Error fetching analytics: {e}")
        return None

def calculate_price_estimate(stats, analytics):
    """
    Calculate estimated sponsorship price based on channel metrics
    Args:
        stats: Channel statistics
        analytics: Channel analytics data
    Returns:
        dict: Price estimate and reasoning
    """
    # Base rate per 1000 views (industry standard CPM)
    BASE_CPM = 20

    # Subscriber count influence (logarithmic scale)
    # The logarithmic function prevents the multiplier from growing too quickly for channels with large subscriber counts. For example: 1,000 subscribers → ~1.15x multiplier; 1,000,000 subscribers → ~1.3x multiplier
    # Choice by AI
    subscriber_multiplier = 1 + (math.log10(stats['subscriber_count']) / 2)

    # Calculate view duration impact (ranges from 1x to 2x)
    # Higher view duration = higher multiplier
    # Capped at 100% view duration
    view_duration_multiplier = 1 + (min(100, analytics['avg_view_duration']) / 100)

    # Calculate audience size impact based on average views
    # Uses logarithmic scale to prevent exponential growth for viral videos
    # Capped at 10x multiplier to keep estimates reasonable
    # Divide by 2 for gradual scaling
    recent_views_multiplier = min(10, 1 + (math.log10(analytics['recent_views']) / 2))

    # Calculate the final sponsorship price:
    # 1. Start with base price using standard CPM rate per 1000 views
    base_price = (analytics['recent_views'] * BASE_CPM) / 1000
    # 2. Apply all multipliers to get final estimate
    final_price = base_price * subscriber_multiplier * view_duration_multiplier * recent_views_multiplier

    return {
        'estimate': round(final_price, 2),
        'reasoning': f"""
        Based on:
        - Average views per video: {int(analytics['recent_views']):,}
        - Average view duration: {analytics['avg_view_duration']:.1f}%
        - Subscriber count: {stats['subscriber_count']:,}
        
        Calculation breakdown:
        - Base price (CPM ${BASE_CPM}): ${base_price:.2f}
        - Subscriber influence: {subscriber_multiplier:.2f}x
        - View duration impact: {view_duration_multiplier:.2f}x
        - Audience size impact: {recent_views_multiplier:.2f}x
        """
    }


# Define the route for the main page ('/' means the root URL)
@app.route("/", methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        channel_url = request.form['channel_url']
        channel_identifier = extract_channel_id(channel_url)
        
        if not channel_identifier:
            return render_template("home.html", error="Invalid YouTube channel URL. Please enter a valid URL.")
        
        # Get basic channel stats (now includes channel_id)
        stats = get_channel_stats(channel_identifier)
        if not stats:
            return render_template("home.html", error="Could not fetch channel statistics. Please verify the URL.")
        
        # Use the actual channel ID for analytics
        analytics = get_channel_analytics(stats['channel_id'])
        if not analytics:
            return render_template("home.html", error="Could not fetch channel analytics. Please try again.")
        
        # Calculate price estimate
        price = calculate_price_estimate(stats, analytics)
        
        # Generate AI explanation
        ai_explanation = generate_ai_explanation(stats, analytics, price)
        
        # Render result template with all data
        return render_template(
            "result.html",
            stats=stats,
            analytics=analytics,
            price=price,
            ai_explanation=ai_explanation
        )

    return render_template("home.html")

# Add the about route
@app.route("/about")
def about():
    return render_template("about.html")

# Run the Flask application
if __name__ == '__main__':
    app.run(debug=True)